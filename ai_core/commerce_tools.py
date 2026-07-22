from decimal import Decimal, InvalidOperation
import re

from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils.html import strip_tags

from installers.models import ServiceProviderProfile, ServiceQuoteRequest
from installers.services import filter_public_providers, suggested_providers_for_product
from notifications.models import Notification
from products.models import Product, VendorProductOffer


UNTRUSTED_PREFIX = "Untrusted marketplace source content: "


def _plain(value, limit=1200):
    return " ".join(strip_tags(str(value or "")).split())[:limit]


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _limit(value, default=5, maximum=10):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(number, maximum))


def _query_tokens(value):
    stop = {
        "show", "find", "search", "recommend", "me", "for", "please", "need",
        "want", "looking", "buy", "get", "a", "an", "the", "do", "you", "have",
    }
    return [
        token
        for token in re.sub(r"[^a-zA-Z0-9\s-]", " ", str(value or "").lower()).split()
        if len(token) > 2 and token not in stop
    ][:6]


def _public_product_queryset():
    return (
        Product.objects
        .filter(is_active=True, approval_status="approved")
        .select_related("category", "brand", "vendor")
        .prefetch_related("vendor_offers__vendor")
    )


def _product_lookup(ref):
    ref = str(ref or "").strip()
    queryset = _public_product_queryset()
    if ref.isdigit():
        return queryset.filter(pk=int(ref)).first()
    return queryset.filter(slug=ref).first()


def _product_url(product):
    try:
        return product.get_absolute_url()
    except Exception:
        return reverse("products:product_detail", kwargs={"slug": product.slug})


def _source(label, obj_type, ref, url=""):
    return {"label": label, "type": obj_type, "ref": str(ref), "url": url}


def _public_offers(product, limit=4):
    offers = []
    queryset = (
        VendorProductOffer.objects
        .filter(product=product, is_active=True, approval_status=VendorProductOffer.STATUS_APPROVED)
        .select_related("vendor")
        .order_by("price")[:limit]
    )
    for offer in queryset:
        vendor = offer.vendor
        offers.append({
            "seller": _plain(getattr(vendor, "display_name", "") or str(vendor), 160),
            "price": str(offer.final_price),
            "currency": offer.currency,
            "condition": offer.condition,
            "stock_status": "in_stock" if offer.available_stock > 0 else "out_of_stock",
            "fulfilment_method": offer.fulfilment_method,
            "warranty": _plain(offer.seller_warranty, 240),
            "delivery_note": _plain(offer.delivery_note, 240),
        })
    return offers


def product_facts(product):
    category = product.category
    brand = product.brand
    url = _product_url(product)
    specs = _plain(getattr(product, "specifications", ""), 2200)
    description = _plain(getattr(product, "description", ""), 1400)
    facts = {
        "public_ref": product.slug,
        "id": product.id,
        "name": _plain(product.name, 240),
        "slug": product.slug,
        "public_url": url,
        "category": _plain(getattr(category, "name", ""), 160) if category else "",
        "brand": _plain(getattr(brand, "name", ""), 160) if brand else "",
        "approval_state": "approved",
        "condition": product.condition,
        "description_summary": f"{UNTRUSTED_PREFIX}{description}" if description else "",
        "normalised_specifications": f"{UNTRUSTED_PREFIX}{specs}" if specs else "",
        "displayed_price": str(product.price),
        "compare_price": str(product.compare_price or ""),
        "stock_status": "in_stock" if getattr(product, "is_in_stock", False) and int(getattr(product, "stock_quantity", 0) or 0) > 0 else "out_of_stock",
        "warranty": {
            "years": getattr(product, "warranty_years", None),
            "description": _plain(getattr(product, "warranty_description", ""), 400),
        },
        "shipping": {
            "lead_time_days": getattr(product, "lead_time_days", None),
            "country_of_origin": _plain(getattr(product, "country_of_origin", ""), 120),
        },
        "approved_public_offers": _public_offers(product),
        "public_media": {
            "manual": product.manual_pdf.url if getattr(product, "manual_pdf", None) else "",
            "video": product.get_video_embed_url() if hasattr(product, "get_video_embed_url") else "",
        },
        "source_references": [_source(product.name, "product", product.slug, url)],
    }
    return facts


def search_products(payload, context=None):
    payload = payload or {}
    queryset = _public_product_queryset()
    query = str(payload.get("query") or "").strip()
    if query:
        query_filter = (
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(specifications__icontains=query)
            | Q(sku__icontains=query)
            | Q(manufacturer_sku__icontains=query)
            | Q(category__name__icontains=query)
            | Q(brand__name__icontains=query)
        )
        token_filter = Q()
        for token in _query_tokens(query):
            token_filter |= (
                Q(name__icontains=token)
                | Q(description__icontains=token)
                | Q(specifications__icontains=token)
                | Q(sku__icontains=token)
                | Q(manufacturer_sku__icontains=token)
                | Q(category__name__icontains=token)
                | Q(brand__name__icontains=token)
            )
        queryset = queryset.filter(query_filter | token_filter)
    if payload.get("category"):
        queryset = queryset.filter(category__name__icontains=str(payload["category"]).strip())
    if payload.get("brand"):
        queryset = queryset.filter(brand__name__icontains=str(payload["brand"]).strip())
    if payload.get("condition"):
        queryset = queryset.filter(condition=str(payload["condition"]).strip())
    min_price = _decimal(payload.get("minimum_price"))
    max_price = _decimal(payload.get("maximum_price"))
    if min_price is not None:
        queryset = queryset.filter(price__gte=min_price)
    if max_price is not None:
        queryset = queryset.filter(price__lte=max_price)
    for feature in payload.get("required_features") or []:
        text = str(feature or "").strip()
        if text:
            queryset = queryset.filter(Q(description__icontains=text) | Q(specifications__icontains=text))
    limit = _limit(payload.get("result_limit"))
    products = [product_facts(product) for product in queryset.order_by("-is_featured", "price")[:limit]]
    return {
        "products": products,
        "source_references": [source for product in products for source in product["source_references"]],
        "warnings": [],
    }


def get_product_facts(payload, context=None):
    product = _product_lookup((payload or {}).get("product_ref"))
    if not product:
        raise ValueError("Approved product not found.")
    facts = product_facts(product)
    return {"product": facts, "source_references": facts["source_references"]}


def compare_products(payload, context=None):
    refs = (payload or {}).get("product_refs") or []
    products = []
    for ref in refs:
        product = _product_lookup(ref)
        if not product:
            raise ValueError("Every comparison product must be active and approved.")
        products.append(product_facts(product))
    labels = [
        ("Price", "displayed_price"),
        ("Brand", "brand"),
        ("Category", "category"),
        ("Condition", "condition"),
        ("Stock status", "stock_status"),
        ("Warranty", "warranty"),
        ("Specifications", "normalised_specifications"),
    ]
    points = []
    for label, key in labels:
        for product in products:
            value = product.get(key)
            if isinstance(value, dict):
                value = ", ".join(f"{k}: {v}" for k, v in value.items() if v not in ("", None))
            points.append({
                "label": label,
                "product": product["public_ref"],
                "confirmed_value": value or "",
                "status": "confirmed" if value else "unavailable",
                "source_references": product["source_references"],
            })
    return {
        "comparison_points": points,
        "source_references": [source for product in products for source in product["source_references"]],
        "warnings": ["No overall winner selected without explicit requirements."],
    }


def _provider_payload(provider):
    services = [
        {
            "name": _plain(service.service_name, 160),
            "category": _plain(getattr(service.category, "name", ""), 160),
            "summary": _plain(getattr(service, "card_excerpt", ""), 240),
            "starting_price": str(service.starting_price or ""),
        }
        for service in provider.services.filter(is_active=True).select_related("category")[:4]
    ]
    return {
        "public_ref": provider.slug,
        "id": provider.id,
        "business_name": _plain(provider.business_name, 180),
        "provider_type": provider.provider_type,
        "location": provider.location_label,
        "service_coverage": _plain(provider.service_coverage, 300),
        "description": f"{UNTRUSTED_PREFIX}{_plain(provider.description, 700)}",
        "verification_status": provider.verification_status,
        "kyc_status": provider.kyc_status,
        "average_rating": str(provider.average_rating),
        "total_reviews": provider.total_reviews,
        "total_completed_jobs": provider.total_completed_jobs,
        "services": services,
        "source_references": [_source(provider.business_name, "service_provider", provider.slug, provider.get_absolute_url())],
    }


def match_providers(payload, context=None):
    payload = payload or {}
    product = _product_lookup(payload.get("product_ref")) if payload.get("product_ref") else None
    if product:
        queryset = suggested_providers_for_product(product, limit=_limit(payload.get("result_limit")))
    else:
        params = {
            "q": payload.get("query", ""),
            "category": payload.get("category", ""),
            "country": payload.get("country", ""),
            "state": payload.get("state", ""),
            "city": payload.get("city", ""),
            "provider_type": payload.get("provider_type", ""),
        }
        queryset = filter_public_providers(params).filter(kyc_status=ServiceProviderProfile.KYC_APPROVED)
    providers = [_provider_payload(provider) for provider in queryset[:_limit(payload.get("result_limit"))]]
    return {
        "providers": providers,
        "source_references": [source for provider in providers for source in provider["source_references"]],
        "warnings": ["Schedule, availability and price are not promised unless a provider confirms them."],
    }


def _quote_duplicate(payload):
    marker = str(payload.get("idempotency_key") or "").strip()
    if not marker:
        return None
    quote = ServiceQuoteRequest.objects.filter(admin_note__icontains=f"idempotency_key={marker}").first()
    return _quote_payload(quote, created=False) if quote else None


def _quote_payload(quote, created):
    if not quote:
        return {}
    return {
        "quote_request": {
            "id": quote.id,
            "status": quote.status,
            "service_needed": quote.service_needed,
            "human_review_required": True,
        },
        "created": created,
        "source_references": [_source("Service quote request", "service_quote_request", quote.id)],
        "warnings": ["Draft request only. No final quotation, order, payment or inventory reservation was created."],
    }


@transaction.atomic
def create_quote_request(payload, context=None):
    from .tools import validate_quote_request_payload

    context = context or {}
    user = context.get("user")
    validate_quote_request_payload(payload, user=user)
    duplicate = _quote_duplicate(payload)
    if duplicate:
        return duplicate
    requirements = payload.get("requirements") or {}
    summary = _plain(requirements.get("summary") or payload.get("requirements_summary"), 1200)
    product = _product_lookup((payload.get("product_refs") or [""])[0]) if payload.get("product_refs") else None
    provider = None
    if payload.get("provider_ref"):
        ref = str(payload.get("provider_ref")).strip()
        provider_qs = ServiceProviderProfile.objects.public().filter(kyc_status=ServiceProviderProfile.KYC_APPROVED)
        provider = provider_qs.filter(pk=int(ref)).first() if ref.isdigit() else provider_qs.filter(slug=ref).first()
    guest = payload.get("guest_contact") or {}
    phone = _plain(
        guest.get("phone")
        or requirements.get("phone")
        or getattr(user, "phone_number", "")
        or "",
        30,
    )
    email = _plain(guest.get("email") or getattr(user, "email", ""), 254)
    if not phone:
        raise ValueError("A phone number is required for human quote-request review.")
    quote = ServiceQuoteRequest.objects.create(
        customer=user if user is not None and getattr(user, "is_authenticated", False) else None,
        provider=provider,
        product=product,
        name=_plain(guest.get("name") or getattr(user, "get_full_name", lambda: "")() or "Arolana customer", 150),
        phone=phone,
        whatsapp=_plain(guest.get("whatsapp") or "", 30),
        email=email,
        state=_plain(requirements.get("state") or requirements.get("location") or "Not supplied", 100),
        city=_plain(requirements.get("city") or requirements.get("location") or "Not supplied", 100),
        address=_plain(requirements.get("address") or "To be confirmed by human review.", 500),
        service_needed=_plain(requirements.get("service_needed") or "Smart Shopping draft service quote request", 220),
        message=(
            f"{summary}\n\nAssumptions: {_plain(requirements.get('assumptions'), 500)}\n"
            f"Missing information: {_plain(requirements.get('missing_information'), 500)}\n"
            "AI provenance: Smart Shopping V1 draft request; requires human/provider/staff review."
        ),
        contact_preference=_plain(requirements.get("contact_preference") or "human review", 80),
        urgency=_plain(requirements.get("urgency") or "normal", 20),
        status="new",
        admin_note=(
            f"ai_tool=quotes.create_quote_request; "
            f"conversation_id={payload.get('conversation_id')}; "
            f"request_id={payload.get('request_id')}; "
            f"idempotency_key={payload.get('idempotency_key')}; "
            f"source_refs={payload.get('source_references') or []}; "
            "human_review_required=true"
        )[:2000],
    )
    try:
        if quote.provider:
            Notification.send(
                quote.provider.user,
                "message",
                "Draft service quote request",
                f"{quote.name} requested {quote.service_needed}. Human review required.",
                link="/installers/dashboard/",
                metadata={"service_quote_request_id": quote.id, "source": "ai_core"},
                priority=3,
            )
    except Exception:
        pass
    return _quote_payload(quote, created=True)


TOOL_HANDLERS = {
    "catalog.search_products": search_products,
    "catalog.get_product_facts": get_product_facts,
    "catalog.compare_products": compare_products,
    "services.match_providers": match_providers,
    "quotes.create_quote_request": create_quote_request,
}
