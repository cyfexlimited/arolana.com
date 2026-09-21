import re
from urllib.parse import urlparse

from django.db import transaction

from catalog_imports.extractors.registry import get_extractor
from catalog_imports.models import (
    BrandVerificationProfile,
    ImportAuditEvent,
    ImportEvidence,
    ImportItem,
    ImportSource,
)
from catalog_imports.schema import UniversalProductDraft
from catalog_imports.services.cleaning import clean_source_identity
from catalog_imports.services.contamination import scan_source_identity
from catalog_imports.services.evidence import (
    compare_identity,
    merge_authoritative_draft,
    official_domain_matches,
    readiness_decision,
    supporting_urls,
)
from catalog_imports.services.http_fetch import FetchBlocked, UnsafeURL, fetch_html
from catalog_imports.services.official_documents import enrich_manufacturer_from_official_documents
from catalog_imports.services.pricing import calculate_price, calculate_price_breakdown
from catalog_imports.services.web_evidence import (
    discover_manufacturer_web_identity,
    retrieve_manufacturer_web_evidence,
    retrieve_retailer_web_evidence,
)
from catalog_imports.services.official_media_acquisition import acquire_official_media
from catalog_imports.services.product_data_completion import (
    build_product_data_completion_report,
    enrich_verified_draft_from_specs,
)
from catalog_imports.services.product_draft_sync import sync_verified_product_draft
from catalog_imports.services.quality import validate_draft
from catalog_imports.services.source_detection import source_for_url


def _log(item, event_type, message="", payload=None):
    ImportAuditEvent.objects.create(
        item=item,
        event_type=event_type,
        message=message[:500],
        payload=payload or {},
    )


def _patterns_for(extractor, draft):
    patterns = []
    if extractor and hasattr(extractor, "contamination_patterns"):
        patterns.extend(extractor.contamination_patterns())
    if draft.source_name:
        patterns.append(r"\b" + re.escape(draft.source_name) + r"(?:\.com)?\b")
    return patterns


def _profile_for(item, *drafts):
    profiles = BrandVerificationProfile.objects.filter(is_active=True).order_by("brand_name")
    brands = []
    for draft in drafts:
        if not draft:
            continue
        for value in (draft.brand, draft.manufacturer):
            value = str(value or "").strip()
            if value and value.lower() not in {x.lower() for x in brands}:
                brands.append(value)

    for brand in brands:
        profile = profiles.filter(brand_name__iexact=brand).first()
        if profile:
            return profile

    haystack = str(item.input_value or "").lower()
    for profile in profiles:
        tokens = [profile.brand_name] + list(profile.aliases or [])
        if any(str(token or "").strip().lower() in haystack for token in tokens if str(token or "").strip()):
            return profile
    return None


def _evidence(item, *, role, url="", status, source_name="", authoritative=False, payload=None, error="", http_status=None, notes=""):
    return ImportEvidence.objects.create(
        item=item,
        role=role,
        url=url,
        source_name=source_name,
        is_authoritative=bool(authoritative),
        status=status,
        http_status=http_status,
        extracted_payload=payload or {},
        error_message=str(error or ""),
        notes=notes,
    )


def _fetch_generic(url, *, timeout=12, user_agent="ArolanaProductImporter/3.0 (+https://arolana.com)"):
    fetch = fetch_html(url, timeout=timeout, user_agent=user_agent)
    draft = get_extractor("generic").extract(
        url=fetch.url,
        html=fetch.text,
        context={"default_currency": "NGN"},
    )
    draft.source_url = fetch.url
    return fetch, draft


def _reset_item_for_analysis(item):
    item.status = ImportItem.STATUS_EXTRACTING
    item.error_message = ""
    item.hold_reason = ""
    item.identity_verified = False
    item.specifications_verified = False
    item.price_verified = False
    item.raw_payload = {}
    item.normalized_payload = {}
    item.verification_report = {}
    item.contamination_report = {}
    item.image_report = {}
    item.duplicate_report = {}
    item.source_price = None
    item.source_currency = ""
    item.calculated_price = None
    item.pricing_rule = None
    item.save()
    item.evidence_records.all().delete()


def analyse_item(item: ImportItem):
    _reset_item_for_analysis(item)
    _log(item, "analysis_started", "Product evidence analysis started.")

    value = (item.input_value or "").strip()
    if not value.lower().startswith(("http://", "https://")):
        item.status = ImportItem.STATUS_BLOCKED
        item.hold_reason = "discovery_connector_required"
        item.error_message = (
            "Product-name discovery requires a configured permitted search/API provider. "
            "Paste a direct product URL until a discovery provider is configured."
        )
        item.verification_report = {"phase": "discovery", "ready": False, "reason": item.hold_reason}
        item.save()
        _log(item, "discovery_required", item.error_message)
        return item

    source = item.source or source_for_url(value)
    if source:
        item.source = source
    item.source_url = value
    item.save(update_fields=["source", "source_url", "updated_at"])

    extractor_key = "generic"
    if source and source.extraction_mode == ImportSource.MODE_ADAPTER and source.adapter_key:
        extractor_key = source.adapter_key
    extractor = get_extractor(extractor_key)

    timeout = int((source.configuration or {}).get("timeout_seconds", 12)) if source else 12
    user_agent = (
        (source.configuration or {}).get("user_agent", "ArolanaProductImporter/3.0 (+https://arolana.com)")
        if source else "ArolanaProductImporter/3.0 (+https://arolana.com)"
    )

    retailer_draft = None
    source_access_error = ""
    try:
        fetch = fetch_html(value, timeout=timeout, user_agent=user_agent)
        retailer_draft = extractor.extract(
            url=fetch.url,
            html=fetch.text,
            context={"default_currency": source.default_currency if source else "NGN"},
        )
        retailer_draft.source_url = fetch.url
        retailer_draft.source_name = source.name if source else (urlparse(fetch.url).hostname or "")
        if not retailer_draft.source_currency:
            retailer_draft.source_currency = source.default_currency if source else "NGN"
        _evidence(
            item,
            role=ImportEvidence.ROLE_RETAILER,
            url=fetch.url,
            status=ImportEvidence.STATUS_FETCHED,
            source_name=retailer_draft.source_name,
            payload=retailer_draft.to_dict(),
            http_status=fetch.status,
        )
    except (FetchBlocked, UnsafeURL, ValueError, LookupError) as exc:
        source_access_error = str(exc)
        _evidence(
            item,
            role=ImportEvidence.ROLE_RETAILER,
            url=value,
            status=ImportEvidence.STATUS_BLOCKED,
            source_name=source.name if source else "",
            error=source_access_error,
        )
        _log(item, "source_access_blocked", source_access_error)
    except Exception as exc:
        source_access_error = f"Unexpected source extraction failure: {exc}"
        _evidence(
            item,
            role=ImportEvidence.ROLE_RETAILER,
            url=value,
            status=ImportEvidence.STATUS_FAILED,
            source_name=source.name if source else "",
            error=source_access_error,
        )
        _log(item, "source_access_failed", source_access_error)

    retailer_web_report = {"status": "not_needed"}
    if retailer_draft is None and source_access_error:
        web_result = retrieve_retailer_web_evidence(item, source=source)
        retailer_web_report = {
            key: value
            for key, value in web_result.items()
            if key not in {"draft"}
        }
        if web_result.get("verified") and web_result.get("draft"):
            retailer_draft = web_result["draft"]
            retailer_draft.source_name = source.name if source else retailer_draft.source_name
            retailer_draft.source_url = value
            if not retailer_draft.source_currency:
                retailer_draft.source_currency = source.default_currency if source else "NGN"

            evidence_url = str(
                web_result.get("retailer_product_url")
                or ((web_result.get("evidence_urls") or [value])[0])
                or value
            ).strip()
            _evidence(
                item,
                role=ImportEvidence.ROLE_RETAILER,
                url=evidence_url,
                status=ImportEvidence.STATUS_FETCHED,
                source_name=source.name if source else (urlparse(evidence_url).hostname or ""),
                authoritative=False,
                payload=retailer_draft.to_dict(),
                notes=(
                    "Exact retailer identity/price recovered from already-indexed "
                    "public web evidence restricted to the selected retailer domain. "
                    "Direct HTTP access remained blocked; no anti-bot bypass was attempted."
                ),
            )
            _log(
                item,
                "retailer_web_fallback_verified",
                "Blocked retailer listing recovered from restricted indexed web evidence.",
                retailer_web_report,
            )

    profile = _profile_for(item, retailer_draft)

    # Phase 5.3: when the admin did not provide a manufacturer URL, try to
    # discover the exact official product page automatically. This is a
    # discovery-only step: it does not publish, does not touch retailer price,
    # and accepts a page only after exact identity + brand/domain safeguards.
    manufacturer_discovery_report = {"status": "not_needed"}
    if (
        item.batch.verify_against_manufacturer
        and not str(item.manufacturer_url or "").strip()
    ):
        manufacturer_discovery_report = discover_manufacturer_web_identity(
            item,
            profile=profile,
        )
        if manufacturer_discovery_report.get("verified"):
            item.manufacturer_url = str(
                manufacturer_discovery_report.get("official_product_url") or ""
            ).strip()
            item.save(update_fields=["manufacturer_url", "updated_at"])

    manufacturer_draft = None
    manufacturer_report = {
        "requested": bool(item.batch.verify_against_manufacturer),
        "url": item.manufacturer_url,
        "profile": profile.brand_name if profile else "",
        "official_domain": profile.official_domain if profile else "",
        "status": "not_requested" if not item.batch.verify_against_manufacturer else "not_configured",
    }

    # If the selected source itself is the configured official manufacturer,
    # it can serve as both retailer/source evidence and manufacturer evidence.
    source_is_official = bool(
        retailer_draft
        and profile
        and profile.official_domain
        and official_domain_matches(retailer_draft.source_url, profile.official_domain)
    )
    if source_is_official:
        manufacturer_draft = retailer_draft
        item.identity_verified = True
        item.specifications_verified = bool(
            retailer_draft.specifications or retailer_draft.specifications_html
        )
        manufacturer_report.update({
            "status": "verified_from_source",
            "authoritative_domain": True,
            "identity": {"passed": True, "reason": "Source is configured official manufacturer domain."},
        })

    elif item.batch.verify_against_manufacturer and item.manufacturer_url:
        authoritative_domain = bool(
            profile and profile.official_domain and official_domain_matches(item.manufacturer_url, profile.official_domain)
        )
        try:
            mfetch, manufacturer_draft = _fetch_generic(item.manufacturer_url, timeout=timeout, user_agent=user_agent)
            if profile:
                if not manufacturer_draft.brand:
                    manufacturer_draft.brand = profile.brand_name
                if not manufacturer_draft.manufacturer:
                    manufacturer_draft.manufacturer = profile.manufacturer_name or profile.brand_name
            identity = compare_identity(
                retailer_draft,
                manufacturer_draft,
                input_hint=value,
                expected_brand=profile.brand_name if profile else "",
                official_domain_ok=authoritative_domain,
            )
            item.identity_verified = bool(authoritative_domain and identity["passed"])

            official_document_report = {"status": "not_attempted"}
            if (
                item.identity_verified
                and not (manufacturer_draft.specifications or manufacturer_draft.specifications_html)
                and profile
                and profile.official_domain
            ):
                official_document_report = enrich_manufacturer_from_official_documents(
                    manufacturer_draft,
                    manufacturer_html=mfetch.text,
                    manufacturer_url=mfetch.url,
                    official_domain=profile.official_domain,
                    timeout=timeout,
                    user_agent=user_agent,
                )
                verified_document = official_document_report.get("verified_document") or {}
                if verified_document:
                    _evidence(
                        item,
                        role=ImportEvidence.ROLE_SECONDARY,
                        url=verified_document.get("url", ""),
                        status=ImportEvidence.STATUS_FETCHED,
                        source_name=(profile.brand_name + " official specifications").strip(),
                        authoritative=True,
                        payload={
                            "document_kind": "official_manufacturer_specification_document",
                            "content_type": verified_document.get("content_type", ""),
                            "identity": verified_document.get("identity", {}),
                            "specifications": verified_document.get("specifications", {}),
                        },
                        http_status=verified_document.get("status"),
                        notes=(
                            "Auto-discovered from the official manufacturer product page. "
                            "Used only after same-domain and product-identity verification."
                        ),
                    )

            item.specifications_verified = bool(
                item.identity_verified
                and (manufacturer_draft.specifications or manufacturer_draft.specifications_html)
            )
            manufacturer_report.update({
                "status": "verified" if item.identity_verified else "needs_confirmation",
                "authoritative_domain": authoritative_domain,
                "identity": identity,
                "official_document_fallback": official_document_report,
            })
            _evidence(
                item,
                role=ImportEvidence.ROLE_MANUFACTURER,
                url=mfetch.url,
                status=ImportEvidence.STATUS_FETCHED,
                source_name=profile.brand_name if profile else (urlparse(mfetch.url).hostname or ""),
                authoritative=authoritative_domain,
                payload=manufacturer_draft.to_dict(),
                http_status=mfetch.status,
            )
        except (FetchBlocked, UnsafeURL, ValueError, LookupError) as exc:
            manufacturer_report.update({"status": "blocked", "error": str(exc)})
            _evidence(
                item,
                role=ImportEvidence.ROLE_MANUFACTURER,
                url=item.manufacturer_url,
                status=ImportEvidence.STATUS_BLOCKED,
                source_name=profile.brand_name if profile else "",
                authoritative=authoritative_domain,
                error=str(exc),
            )
        except Exception as exc:
            manufacturer_report.update({"status": "failed", "error": str(exc)})
            _evidence(
                item,
                role=ImportEvidence.ROLE_MANUFACTURER,
                url=item.manufacturer_url,
                status=ImportEvidence.STATUS_FAILED,
                source_name=profile.brand_name if profile else "",
                authoritative=authoritative_domain,
                error=str(exc),
            )

    # Phase 5.2: never bypass a 403. If direct official-manufacturer retrieval
    # failed or could not verify identity, use a bounded web-search fallback
    # restricted to explicitly trusted manufacturer domains. This can also
    # discover a canonical product URL when a brand website/profile is configured.
    web_manufacturer_report = {"status": "not_needed"}
    if item.batch.verify_against_manufacturer and not item.identity_verified:
        web_result = retrieve_manufacturer_web_evidence(item, profile=profile)
        web_manufacturer_report = {
            key: value
            for key, value in web_result.items()
            if key not in {"draft"}
        }
        if web_result.get("verified") and web_result.get("draft"):
            manufacturer_draft = web_result["draft"]
            item.identity_verified = True
            item.specifications_verified = bool(
                manufacturer_draft.specifications
                or manufacturer_draft.specifications_html
            )

            discovered_url = str(web_result.get("official_product_url") or "").strip()
            if discovered_url and not item.manufacturer_url:
                # Auto-fill only after exact identity + trusted-domain verification.
                item.manufacturer_url = discovered_url

            manufacturer_report.update({
                "status": "verified_via_web_search",
                "url": discovered_url or item.manufacturer_url,
                "authoritative_domain": True,
                "identity": web_result.get("identity") or {},
                "retrieval_method": web_result.get("provider") or "web_search",
                "trusted_domains": web_result.get("allowed_domains") or [],
                "evidence_urls": web_result.get("evidence_urls") or [],
            })

            evidence_url = discovered_url or (
                (web_result.get("evidence_urls") or [item.manufacturer_url])[0]
            )
            _evidence(
                item,
                role=ImportEvidence.ROLE_MANUFACTURER,
                url=evidence_url,
                status=ImportEvidence.STATUS_FETCHED,
                source_name=(
                    profile.brand_name if profile else
                    str(getattr(getattr(item.batch, "default_brand", None), "name", "") or "")
                ),
                authoritative=True,
                payload=manufacturer_draft.to_dict(),
                notes=(
                    "Official manufacturer facts retrieved through a trusted-domain "
                    "web-search fallback because direct HTTP access was blocked. "
                    "No retailer price was requested or accepted."
                ),
            )

    # Secondary evidence is recorded for review but never silently overrides
    # official manufacturer facts or retailer price.
    secondary_reports = []
    for evidence_url in supporting_urls(item.secondary_evidence_urls):
        try:
            efetch, edraft = _fetch_generic(evidence_url, timeout=timeout, user_agent=user_agent)
            secondary_reports.append({"url": efetch.url, "status": "fetched"})
            _evidence(
                item,
                role=ImportEvidence.ROLE_SECONDARY,
                url=efetch.url,
                status=ImportEvidence.STATUS_FETCHED,
                source_name=urlparse(efetch.url).hostname or "",
                payload=edraft.to_dict(),
                http_status=efetch.status,
            )
        except Exception as exc:
            secondary_reports.append({"url": evidence_url, "status": "blocked", "error": str(exc)})
            _evidence(
                item,
                role=ImportEvidence.ROLE_SECONDARY,
                url=evidence_url,
                status=ImportEvidence.STATUS_BLOCKED,
                source_name=urlparse(evidence_url).hostname or "",
                error=str(exc),
            )

    # Merge only authoritative manufacturer evidence. Manufacturer price is
    # explicitly excluded by merge_authoritative_draft.
    final_draft = retailer_draft or UniversalProductDraft(
        source_name=source.name if source else "",
        source_url=value,
        source_currency=source.default_currency if source else "NGN",
    )
    if manufacturer_draft and item.identity_verified and not source_is_official:
        final_draft = merge_authoritative_draft(retailer_draft, manufacturer_draft)
        final_draft.source_name = source.name if source else final_draft.source_name
        final_draft.source_url = value
        if not final_draft.source_currency:
            final_draft.source_currency = source.default_currency if source else "NGN"

    physical_enrichment_report = {"changed": False, "fields": []}
    if item.identity_verified and item.specifications_verified:
        physical_enrichment_report = enrich_verified_draft_from_specs(final_draft)

    # Commercial price must remain tied to the selected retailer/source. A
    # manufacturer MSRP is never substituted. Admin manual price is accepted
    # only with an explicit evidence URL and remains auditable/human-approved.
    if retailer_draft and retailer_draft.source_price is not None:
        final_draft.source_price = retailer_draft.source_price
        final_draft.source_currency = retailer_draft.source_currency or (source.default_currency if source else "NGN")
        item.price_verified = True
        price_report = {
            "status": (
                "verified_via_retailer_web_search"
                if retailer_web_report.get("verified")
                else "verified_from_source"
            ),
            "price": str(final_draft.source_price),
            "currency": final_draft.source_currency,
            "evidence_urls": retailer_web_report.get("evidence_urls") or [],
        }
    elif item.manual_verified_source_price is not None and item.manual_price_evidence_url:
        final_draft.source_price = item.manual_verified_source_price
        final_draft.source_currency = source.default_currency if source else (final_draft.source_currency or "NGN")
        item.price_verified = True
        price_report = {
            "status": "manual_admin_verified",
            "price": str(item.manual_verified_source_price),
            "evidence_url": item.manual_price_evidence_url,
        }
        _evidence(
            item,
            role=ImportEvidence.ROLE_MANUAL_PRICE,
            url=item.manual_price_evidence_url,
            status=ImportEvidence.STATUS_MANUAL,
            source_name=source.name if source else "",
            authoritative=True,
            payload={"price": str(item.manual_verified_source_price), "currency": final_draft.source_currency},
            notes="Price explicitly verified by an Arolana admin; publication still requires human approval.",
        )
    else:
        final_draft.source_price = None
        item.price_verified = False
        price_report = {"status": "unverified", "reason": "Selected source price could not be verified."}

    patterns = _patterns_for(extractor, final_draft)
    cleaned = clean_source_identity(final_draft, patterns) if item.batch.remove_source_identity else final_draft
    quality = validate_draft(cleaned, require_price=False)
    contamination = scan_source_identity(cleaned, extra_patterns=patterns)

    item.raw_payload = {
        "retailer": retailer_draft.to_dict() if retailer_draft else {},
        "manufacturer": manufacturer_draft.to_dict() if manufacturer_draft else {},
        "source_access_error": source_access_error,
    }
    item.normalized_payload = cleaned.to_dict()
    item.contamination_report = contamination
    item.source_price = cleaned.source_price
    item.source_currency = cleaned.source_currency or (source.default_currency if source else "NGN")

    item.calculated_price = None
    item.pricing_rule = None
    pricing_report = {"status": "held"}
    if item.price_verified and cleaned.source_price is not None:
        try:
            breakdown = calculate_price_breakdown(
                cleaned,
                source=source,
                explicit_rule=item.batch.pricing_rule,
            )
            calculated = breakdown["calculated_price"]
            rule = breakdown["rule"]
            item.calculated_price = calculated
            item.pricing_rule = rule
            pricing_report = {
                "status": "calculated",
                "rule": rule.name,
                "source_price": str(breakdown["source_price"]),
                "source_currency": breakdown["source_currency"],
                "converted_source_price": str(breakdown["base_price"]),
                "base_currency": breakdown["base_currency"],
                "conversion": breakdown["conversion"],
                "calculated_price": str(calculated),
            }
        except ValueError as exc:
            quality["errors"].append(str(exc))
            quality["passed"] = False
            pricing_report = {"status": "blocked", "error": str(exc)}

    product_data_completion = build_product_data_completion_report(
        cleaned,
        identity_verified=item.identity_verified,
        specifications_verified=item.specifications_verified,
        price_verified=item.price_verified,
        calculated_price=item.calculated_price,
    )
    product_data_completion["physical_enrichment"] = physical_enrichment_report

    decision = readiness_decision(
        quality_passed=quality["passed"],
        contamination_passed=contamination["passed"],
        price_verified=item.price_verified,
        manufacturer_required=item.batch.verify_against_manufacturer,
        identity_verified=item.identity_verified,
    )

    # Source access can fail without discarding verified manufacturer facts.
    # It becomes a price/evidence hold rather than a total analysis failure.
    item.status = ImportItem.STATUS_READY if decision["ready"] else ImportItem.STATUS_BLOCKED
    item.hold_reason = decision["reasons"][0] if decision["reasons"] else ""
    item.verification_report = {
        "phase": "multi_source_evidence",
        "source_access": {
            "status": (
                "fetched"
                if retailer_draft and not source_access_error
                else (
                    "recovered_via_retailer_web_search"
                    if retailer_draft and retailer_web_report.get("verified")
                    else "blocked"
                )
            ),
            "direct_http_error": source_access_error,
        },
        "retailer_web_fallback": retailer_web_report,
        "manufacturer_discovery": manufacturer_discovery_report,
        "manufacturer": manufacturer_report,
        "manufacturer_web_fallback": web_manufacturer_report,
        "secondary_evidence": secondary_reports,
        "price": price_report,
        "pricing": pricing_report,
        "quality": quality,
        "product_data_completion": product_data_completion,
        "readiness": decision,
    }

    messages = []
    # Source access failures stay visible in verification_report, but once all
    # required identity/spec/price/quality gates have passed they are no longer
    # shown as a current item error.
    if source_access_error and not decision["ready"]:
        messages.append(source_access_error)
    reason_messages = {
        "quality_checks_failed": "Product identity/content quality checks are incomplete.",
        "source_contamination": "Source identity remains in customer-facing draft content.",
        "source_price_unverified": "Current selected-source price is not verified; Arolana price is on hold.",
        "manufacturer_verification_required": "Official manufacturer identity verification is still required.",
    }
    for reason in decision["reasons"]:
        message = reason_messages.get(reason)
        if message and message not in messages:
            messages.append(message)
    item.error_message = " ".join(messages)
    item.save()

    # If this ImportItem already has an inactive/draft Product, safely backfill
    # newly verified facts discovered by re-analysis. Blank fields only; no
    # approval, activation, publication, or admin-value overwrite.
    product_draft_sync = {"status": "not_attempted"}
    if item.created_product_id and decision["ready"]:
        try:
            product_draft_sync = sync_verified_product_draft(item)
        except Exception as exc:
            product_draft_sync = {
                "status": "failed",
                "error": str(exc),
            }

        verification = dict(item.verification_report or {})
        verification["product_draft_sync"] = product_draft_sync
        item.verification_report = verification
        item.save(update_fields=["verification_report", "updated_at"])

    # Phase 5.3 official-media router runs only after evidence readiness. It is
    # bounded and reference-only: discovered images are never published or
    # attached automatically.
    official_media_report = {"status": "not_attempted"}
    if (
        item.status == ImportItem.STATUS_READY
        and item.identity_verified
        and item.batch.generate_or_prepare_images
    ):
        try:
            official_media_report = acquire_official_media(item)
        except Exception as exc:
            official_media_report = {
                "status": "failed",
                "error": str(exc),
            }

        item.image_report = official_media_report
        verification = dict(item.verification_report or {})
        verification["official_media"] = official_media_report
        item.verification_report = verification
        item.save(
            update_fields=[
                "image_report",
                "verification_report",
                "updated_at",
            ]
        )

    _log(
        item,
        "analysis_completed",
        "Ready for review." if item.status == ImportItem.STATUS_READY else "Held for evidence/quality review.",
        item.verification_report,
    )
    return item


@transaction.atomic
def create_items_for_batch(batch, parsed_inputs):
    return [
        ImportItem.objects.create(
            batch=batch,
            input_value=entry["value"],
            source=batch.source,
        )
        for entry in parsed_inputs
    ]


def analyse_batch(batch):
    batch.status = batch.STATUS_ANALYSING
    batch.save(update_fields=["status", "updated_at"])
    for item in batch.items.order_by("id"):
        analyse_item(item)
    statuses = set(batch.items.values_list("status", flat=True))
    if statuses and statuses.issubset({ImportItem.STATUS_FAILED}):
        batch.status = batch.STATUS_FAILED
    else:
        batch.status = batch.STATUS_REVIEW
    batch.save(update_fields=["status", "updated_at"])
    return batch
