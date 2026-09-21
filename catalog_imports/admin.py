import json

from django.contrib import admin, messages
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from django.core.files.storage import storages
from django.core.exceptions import PermissionDenied

from .forms import BulkImportForm
from .models import (
    BrandVerificationProfile,
    ImportAuditEvent,
    ImportBatch,
    ImportCategoryMapping,
    ImportEvidence,
    ImportItem,
    ImportMediaCandidate,
    ImportPricingRule,
    ImportSource,
)
from .services.analysis import analyse_batch, analyse_item, create_items_for_batch
from .services.input_parser import parse_inputs
from .services.draft_creation import DraftPreparationError, prepare_arolana_draft
from .services.media_publish import MediaAttachmentError, attach_approved_media
from .services.media_generation import MediaGenerationError, materialize_candidate
from .services.media_creative_fallback import (
    CreativeFallbackError,
    creative_fallback_capability,
    creative_fallback_reference_urls,
    is_creative_fallback_candidate,
    materialize_creative_fallback,
)
from .services.media_references import (
    reference_support_for_view,
    reference_support_report,
)
from .services.official_media_acquisition import acquire_official_media
from .services.manual_creative_downgrade import (
    ManualCreativeDowngradeError,
    can_downgrade_to_manual_creative,
    downgrade_to_manual_creative,
)
from .services.dynamic_verified_slots import (
    dynamic_verified_slot_report,
    reconcile_existing_media_plan,
)
from .services.media_profiles import (
    POLICY_ACTUAL_ONLY,
    POLICY_CREATIVE,
    candidate_display_label,
    candidate_generation_policy,
    candidate_is_actual_only,
    candidate_profile_label,
    get_media_profile,
)
from .services.media_reference_trace import (
    reference_trace_for_candidate,
    text_grounding_trace_for_candidate,
)
from .services.media_review import (
    MediaReviewError, approve_candidate, reject_candidate, reset_candidate_for_retry,
)
from .services.practical_media_completion import practical_media_completion
from .services.admin_completion import build_admin_completion_report


def _profile_aware_support_reason(candidate, support_info):
    """Translate legacy reference-role failures into the category/profile label.

    Reference discovery still uses legacy view-role keys internally for
    compatibility.  The admin should never tell a footwear merchant that an
    outsole failed because "ports/controls" were unavailable.
    """
    if bool((support_info or {}).get("supported")):
        return ""

    label = candidate_display_label(candidate)
    policy = candidate_generation_policy(candidate)

    if candidate_is_actual_only(candidate):
        return (
            f"No trustworthy actual source media was discovered for {label}. "
            "Actual documentary media is required, so AI generation remains blocked."
        )

    if policy == POLICY_CREATIVE:
        return (
            f"No verified manufacturer reference was discovered for {label}. "
            "An explicitly labelled creative fallback may be used when available; "
            "its appearance remains unverified."
        )

    return (
        f"No trustworthy official manufacturer reference was discovered for {label}. "
        "Verified generation is blocked to prevent invented physical details."
    )


def _candidate_review_state(candidate):
    if not getattr(candidate, "asset_storage_name", ""):
        return "Pending generation"

    metadata = getattr(candidate, "metadata", None) or {}
    if metadata.get("_arolana_creative_fallback") or metadata.get("_arolana_manual_creative_downgrade"):
        return "Creative — unverified appearance"

    if getattr(candidate, "exact_identity_verified", False):
        return "Exact identity verified"

    return "Needs human review"


@admin.register(ImportSource)
class ImportSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "domain", "extraction_mode", "adapter_key", "default_currency", "is_active")
    list_filter = ("extraction_mode", "is_active", "default_currency")
    search_fields = ("name", "domain", "adapter_key")
    list_editable = ("is_active",)


@admin.register(BrandVerificationProfile)
class BrandVerificationProfileAdmin(admin.ModelAdmin):
    list_display = ("brand_name", "manufacturer_name", "official_domain", "is_active")
    list_filter = ("is_active",)
    search_fields = ("brand_name", "manufacturer_name", "official_domain")
    list_editable = ("is_active",)


@admin.register(ImportPricingRule)
class ImportPricingRuleAdmin(admin.ModelAdmin):
    list_display = (
        "name", "priority", "source", "brand_match", "fixed_markup",
        "percentage_markup", "rounding_mode", "is_active",
    )
    list_filter = ("is_active", "source", "rounding_mode")
    search_fields = ("name", "brand_match", "category_match", "product_identifier_match")
    list_editable = ("priority", "is_active")


@admin.register(ImportCategoryMapping)
class ImportCategoryMappingAdmin(admin.ModelAdmin):
    list_display = (
        "id", "source", "source_category_match", "source_subcategory_match",
        "target_category", "priority", "is_active",
    )
    list_filter = ("is_active", "source", "target_category")
    search_fields = ("source_category_match", "source_subcategory_match", "target_category__name")
    list_editable = ("priority", "is_active")


@admin.register(ImportMediaCandidate)
class ImportMediaCandidateAdmin(admin.ModelAdmin):
    list_display = (
        "id", "item", "kind", "media_view_label", "status", "provider_key", "generation_attempts",
        "exact_identity_verified", "source_identity_check_passed", "watermark_status",
        "rights_status", "selected_for_product", "attached_product_image", "order",
    )
    list_filter = (
        "kind", "view_role", "status", "provider_key", "exact_identity_verified",
        "source_identity_check_passed", "watermark_status", "rights_status", "selected_for_product",
    )
    search_fields = (
        "item__input_value", "source_url", "generation_prompt", "provider_asset_id", "sha256", "last_error"
    )
    readonly_fields = (
        "item", "kind", "view_role", "status", "order", "source_url", "reference_urls",
        "generation_prompt", "provider_key", "provider_asset_id", "provider_response",
        "generation_attempts", "asset_storage_alias", "asset_storage_name", "asset_original_name",
        "mime_type", "width", "height", "file_size", "sha256", "generated_at",
        "exact_identity_required", "exact_identity_verified", "source_identity_check_passed",
        "watermark_status", "rights_status", "selected_for_product", "reviewed_at",
        "approved_by", "approved_at", "rejected_by", "rejected_at", "rejection_reason",
        "last_error", "attached_product_image", "attached_at", "metadata", "created_at", "updated_at",
    )

    @admin.display(description="View", ordering="view_role")
    def media_view_label(self, obj):
        return candidate_display_label(obj)

    def has_add_permission(self, request):
        return False


class ImportItemInline(admin.TabularInline):
    model = ImportItem
    extra = 0
    fields = (
        "input_value", "source", "status", "hold_reason", "identity_verified",
        "price_verified", "source_price", "calculated_price", "created_product",
    )
    readonly_fields = fields
    show_change_link = True


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    change_list_template = "admin/catalog_imports/importbatch/change_list.html"
    list_display = (
        "id", "created_by", "source", "input_mode", "status", "target_vendor",
        "default_category", "max_images", "verify_against_manufacturer",
        "require_human_approval", "created_at",
    )
    list_filter = ("status", "input_mode", "source", "verify_against_manufacturer", "require_human_approval")
    search_fields = ("original_input", "notes")
    readonly_fields = ("created_at", "updated_at")
    inlines = (ImportItemInline,)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "import-products/",
                self.admin_site.admin_view(self.import_products_view),
                name="catalog_imports_import_products",
            ),
        ]
        return custom + urls

    def import_products_view(self, request):
        if request.method == "POST":
            form = BulkImportForm(request.POST)
            if form.is_valid():
                parsed = parse_inputs(form.cleaned_data["products"], maximum=50)
                batch = ImportBatch.objects.create(
                    created_by=request.user,
                    source=form.cleaned_data["source"],
                    input_mode=ImportBatch.MODE_MIXED,
                    original_input=form.cleaned_data["products"],
                    pricing_rule=form.cleaned_data["pricing_rule"],
                    target_vendor=form.cleaned_data["target_vendor"],
                    default_category=form.cleaned_data["default_category"],
                    default_brand=form.cleaned_data["default_brand"],
                    max_images=form.cleaned_data["max_images"],
                    verify_against_manufacturer=form.cleaned_data["verify_against_manufacturer"],
                    generate_or_prepare_images=form.cleaned_data["generate_or_prepare_images"],
                    reject_watermarked_images=form.cleaned_data["reject_watermarked_images"],
                    remove_source_identity=form.cleaned_data["remove_source_identity"],
                    require_human_approval=True,
                )
                create_items_for_batch(batch, parsed)
                analyse_batch(batch)
                ready = batch.items.filter(status=ImportItem.STATUS_READY).count()
                blocked = batch.items.filter(status=ImportItem.STATUS_BLOCKED).count()
                failed = batch.items.filter(status=ImportItem.STATUS_FAILED).count()
                messages.success(
                    request,
                    f"Batch #{batch.pk} analysed: {ready} ready, {blocked} held/blocked, {failed} failed. Nothing was published.",
                )
                return redirect(reverse("admin:catalog_imports_importbatch_change", args=[batch.pk]))
        else:
            form = BulkImportForm()
        context = {
            **self.admin_site.each_context(request),
            "title": "Universal Product Importer",
            "form": form,
            "opts": self.model._meta,
        }
        return render(request, "admin/catalog_imports/importbatch/import_products.html", context)


class ImportEvidenceInline(admin.TabularInline):
    model = ImportEvidence
    extra = 0
    can_delete = False
    fields = (
        "role", "source_name", "url", "is_authoritative", "status", "http_status",
        "error_message", "created_at",
    )
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class ImportMediaCandidateInline(admin.TabularInline):
    model = ImportMediaCandidate
    extra = 0
    can_delete = False
    fields = (
        "kind", "media_view_label", "status", "provider_key", "generation_attempts",
        "source_url", "width", "height", "review_state",
        "source_identity_check_passed", "watermark_status", "rights_status",
        "selected_for_product", "attached_product_image", "last_error", "order",
    )
    readonly_fields = fields
    show_change_link = True

    @admin.display(description="View")
    def media_view_label(self, obj):
        return candidate_display_label(obj)

    @admin.display(description="Trust / review")
    def review_state(self, obj):
        return _candidate_review_state(obj)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ImportItem)
class ImportItemAdmin(admin.ModelAdmin):
    change_form_template = "admin/catalog_imports/importitem/change_form.html"
    list_display = (
        "id", "batch", "short_input", "source", "status", "hold_reason",
        "identity_verified", "specifications_verified", "price_verified",
        "source_price", "calculated_price", "existing_product_match", "created_product",
    )
    list_filter = (
        "status", "hold_reason", "source", "source_currency",
        "identity_verified", "specifications_verified", "price_verified",
    )
    search_fields = (
        "input_value", "source_url", "source_external_id", "manufacturer_url",
        "manual_price_evidence_url", "error_message",
    )
    readonly_fields = (
        "created_at", "updated_at", "raw_payload_pretty", "normalized_payload_pretty",
        "verification_report_pretty", "contamination_report_pretty", "image_report_pretty",
        "duplicate_report_pretty", "draft_preparation_report_pretty",
        "created_product", "existing_product_match", "draft_prepared_at", "media_plan_prepared_at",
        "error_message", "identity_verified", "specifications_verified", "price_verified", "hold_reason",
        "admin_completion_status",
    )
    inlines = (ImportEvidenceInline, ImportMediaCandidateInline)
    fieldsets = (
        ("Import identity", {
            "fields": ("batch", "input_value", "source", "source_url", "source_external_id", "status"),
        }),
        ("Evidence & verification inputs", {
            "fields": (
                "manufacturer_url", "secondary_evidence_urls",
                "manual_verified_source_price", "manual_price_evidence_url",
            ),
            "description": (
                "Use an official manufacturer product page for exact identity/spec verification. "
                "A manual source price is accepted only with an evidence URL and never bypasses human approval."
            ),
        }),
        ("Draft destination", {
            "fields": ("target_vendor", "target_category", "target_brand", "existing_product_match"),
            "description": (
                "These fields affect only importer-created Arolana drafts. Existing manual Product/Vendor flows are unchanged. "
                "Vendor and category must resolve before a draft can be prepared."
            ),
        }),
        ("Verification state", {
            "fields": (
                "identity_verified", "specifications_verified", "price_verified", "hold_reason",
                "source_price", "source_currency", "pricing_rule", "calculated_price",
            ),
        }),
        ("Evidence reports", {
            "fields": (
                "raw_payload_pretty", "normalized_payload_pretty", "verification_report_pretty",
                "contamination_report_pretty", "image_report_pretty", "duplicate_report_pretty",
                "draft_preparation_report_pretty", "error_message",
            ),
            "classes": ("collapse",),
        }),
        ("Result", {
            "fields": (
                "admin_completion_status", "created_product",
                "draft_prepared_at", "media_plan_prepared_at",
                "created_at", "updated_at"
            ),
        }),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<path:object_id>/admin-completion/",
                self.admin_site.admin_view(self.admin_completion_view),
                name="catalog_imports_importitem_admin_completion",
            ),
            path(
                "<path:object_id>/reanalyse/",
                self.admin_site.admin_view(self.reanalyse_view),
                name="catalog_imports_importitem_reanalyse",
            ),
            path(
                "<path:object_id>/prepare-draft/",
                self.admin_site.admin_view(self.prepare_draft_view),
                name="catalog_imports_importitem_prepare_draft",
            ),
            path(
                "<path:object_id>/generate-media/",
                self.admin_site.admin_view(self.generate_media_view),
                name="catalog_imports_importitem_generate_media",
            ),
            path(
                "<path:object_id>/acquire-official-media/",
                self.admin_site.admin_view(self.acquire_official_media_view),
                name="catalog_imports_importitem_acquire_official_media",
            ),
            path(
                "<path:object_id>/apply-dynamic-verified-slots/",
                self.admin_site.admin_view(self.apply_dynamic_verified_slots_view),
                name="catalog_imports_importitem_apply_dynamic_verified_slots",
            ),
            path(
                "<path:object_id>/media/<int:candidate_id>/downgrade-manual-creative/",
                self.admin_site.admin_view(self.downgrade_manual_creative_view),
                name="catalog_imports_importitem_downgrade_manual_creative",
            ),
            path(
                "<path:object_id>/generate-candidate/<int:candidate_id>/",
                self.admin_site.admin_view(self.generate_candidate_view),
                name="catalog_imports_importitem_generate_candidate",
            ),
            path(
                "<path:object_id>/generate-candidate/<int:candidate_id>/creative-fallback/",
                self.admin_site.admin_view(self.generate_creative_fallback_view),
                name="catalog_imports_importitem_generate_creative_fallback",
            ),
            path(
                "<path:object_id>/media-review/",
                self.admin_site.admin_view(self.media_review_view),
                name="catalog_imports_importitem_media_review",
            ),
            path(
                "<path:object_id>/media-preview/<int:candidate_id>/",
                self.admin_site.admin_view(self.media_preview_view),
                name="catalog_imports_importitem_media_preview",
            ),
            path(
                "<path:object_id>/attach-approved-media/",
                self.admin_site.admin_view(self.attach_media_view),
                name="catalog_imports_importitem_attach_media",
            ),
        ]
        return custom + urls

    @admin.display(description="Final importer status")
    def admin_completion_status(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "-"
        report = build_admin_completion_report(obj)
        status = report.get("status")
        label = report.get("label") or "Review importer status"
        if status == "ready_for_approval_review":
            return format_html(
                '<strong style="color:#0a7a31;">{}</strong>',
                label,
            )
        if status == "ready_for_admin_completion":
            return format_html(
                '<strong style="color:#9a6700;">{}</strong>',
                label,
            )
        if status == "verification_attention":
            return format_html(
                '<strong style="color:#b42318;">{}</strong>',
                label,
            )
        return label

    def admin_completion_view(self, request, object_id):
        obj = get_object_or_404(ImportItem, pk=object_id)
        if not self.has_view_permission(request, obj):
            raise PermissionDenied

        report = build_admin_completion_report(obj)
        product = obj.created_product

        context = {
            **self.admin_site.each_context(request),
            "title": report.get("label") or "Admin completion",
            "item": obj,
            "report": report,
            "product": product,
            "opts": self.model._meta,
            "change_url": reverse(
                "admin:catalog_imports_importitem_change",
                args=[obj.pk],
            ),
            "reanalyse_url": reverse(
                "admin:catalog_imports_importitem_reanalyse",
                args=[obj.pk],
            ),
            "prepare_draft_url": reverse(
                "admin:catalog_imports_importitem_prepare_draft",
                args=[obj.pk],
            ),
            "generate_media_url": (
                reverse(
                    "admin:catalog_imports_importitem_generate_media",
                    args=[obj.pk],
                )
                if product else ""
            ),
            "review_media_url": (
                reverse(
                    "admin:catalog_imports_importitem_media_review",
                    args=[obj.pk],
                )
                if product else ""
            ),
            "attach_media_url": (
                reverse(
                    "admin:catalog_imports_importitem_attach_media",
                    args=[obj.pk],
                )
                if product else ""
            ),
            "product_change_url": (
                reverse(
                    "admin:products_product_change",
                    args=[product.pk],
                )
                if product else ""
            ),
        }

        return render(
            request,
            "admin/catalog_imports/importitem/admin_completion.html",
            context,
        )

    def reanalyse_view(self, request, object_id):
        """Re-run evidence analysis for one import item.

        This endpoint deliberately never publishes a product.  It is exposed as
        an admin object-tool link because some admin themes (including Jazzmin)
        can break nested POST forms placed in the object-tools area.  The
        operation is a repeatable diagnostic/recalculation of importer-owned
        draft data only.
        """
        obj = get_object_or_404(ImportItem, pk=object_id)
        change_url = reverse("admin:catalog_imports_importitem_change", args=[obj.pk])

        analyse_item(obj)
        obj.refresh_from_db()
        if obj.status == ImportItem.STATUS_READY:
            messages.success(
                request,
                "Evidence re-analysed. Item is ready for human review; nothing was published.",
            )
        else:
            messages.warning(
                request,
                f"Evidence re-analysed. Item remains on hold: "
                f"{obj.hold_reason or obj.error_message or 'review required'}.",
            )
        return redirect(change_url + "#verification-state-tab")

    def prepare_draft_view(self, request, object_id):
        obj = get_object_or_404(ImportItem, pk=object_id)
        change_url = reverse("admin:catalog_imports_importitem_change", args=[obj.pk])

        # Draft creation changes database state, so unlike evidence re-analysis
        # it requires an explicit POST confirmation on its own page. This avoids
        # nested-form/Jazzmin issues without turning a GET link into a write.
        if request.method != "POST":
            context = {
                **self.admin_site.each_context(request),
                "title": "Prepare Arolana Product draft",
                "item": obj,
                "opts": self.model._meta,
                "change_url": change_url,
            }
            return render(
                request,
                "admin/catalog_imports/importitem/prepare_draft_confirm.html",
                context,
            )

        try:
            product = prepare_arolana_draft(obj, actor=request.user)
        except DraftPreparationError as exc:
            obj.refresh_from_db()
            messages.warning(request, str(exc))
            anchor = "#draft-destination-tab" if "destination" in str(exc).lower() or "vendor" in str(exc).lower() or "category" in str(exc).lower() else "#result-tab"
            return redirect(change_url + anchor)
        messages.success(
            request,
            f"Arolana Product draft #{product.pk} prepared safely. It is inactive and approval_status=draft; nothing was published.",
        )
        return redirect(change_url + "#result-tab")

    def acquire_official_media_view(self, request, object_id):
        if request.method != "POST":
            return JsonResponse(
                {"ok": False, "error": "POST required."},
                status=405,
            )

        obj = get_object_or_404(ImportItem, pk=object_id)
        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        report = acquire_official_media(
            obj,
            actor=request.user,
        )
        obj.image_report = report
        verification = dict(obj.verification_report or {})
        verification["official_media"] = report
        obj.verification_report = verification
        obj.save(
            update_fields=[
                "image_report",
                "verification_report",
                "updated_at",
            ]
        )

        count = int(report.get("reference_count") or 0)
        if count:
            messages.success(
                request,
                f"Official manufacturer media refreshed: {count} exact-product "
                "reference image(s) are now available for review/generation.",
            )
        else:
            messages.warning(
                request,
                "Official manufacturer media search completed, but no exact-product "
                "reference images could be safely acquired. Creative support media "
                "remains available where policy permits it.",
            )

        return redirect(
            reverse(
                "admin:catalog_imports_importitem_generate_media",
                args=[obj.pk],
            )
        )

    def downgrade_manual_creative_view(self, request, object_id, candidate_id):
        if request.method != "POST":
            return JsonResponse(
                {"ok": False, "error": "POST required."},
                status=405,
            )

        obj = get_object_or_404(ImportItem, pk=object_id)
        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        candidate = get_object_or_404(
            ImportMediaCandidate,
            pk=candidate_id,
            item=obj,
            kind=ImportMediaCandidate.KIND_GENERATION,
        )

        try:
            downgrade_to_manual_creative(
                candidate,
                actor=request.user,
                reason=(
                    request.POST.get("manual_creative_reason")
                    or request.POST.get("reason", "")
                ),
            )
        except ManualCreativeDowngradeError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"{candidate.get_view_role_display()} is now manual creative / "
                "unverified appearance. Review it again and use the creative "
                "acknowledgement before approval.",
            )

        return redirect(
            reverse(
                "admin:catalog_imports_importitem_media_review",
                args=[obj.pk],
            )
        )

    def apply_dynamic_verified_slots_view(self, request, object_id):
        if request.method != "POST":
            return JsonResponse(
                {"ok": False, "error": "POST required."},
                status=405,
            )

        obj = get_object_or_404(ImportItem, pk=object_id)
        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        result = reconcile_existing_media_plan(
            obj,
            actor=request.user,
        )

        if result.get("applied_count"):
            labels = ", ".join(
                str(row.get("new_label") or row.get("role") or "")
                for row in result.get("applied") or []
            )
            messages.success(
                request,
                f"Applied {result['applied_count']} verified factual slot(s): {labels}. "
                "Only unapproved creative slots were replaced.",
            )
        elif result.get("held"):
            messages.warning(
                request,
                "Verified factual views exist, but no unapproved creative slot can "
                "be replaced safely. Approved/attached media was left unchanged.",
            )
        else:
            messages.info(
                request,
                "The current media plan already represents all available verified factual views.",
            )

        return redirect(
            reverse(
                "admin:catalog_imports_importitem_generate_media",
                args=[obj.pk],
            )
        )

    def generate_media_view(self, request, object_id):
        obj = get_object_or_404(ImportItem, pk=object_id)
        if not self.has_view_permission(request, obj):
            raise PermissionDenied

        change_url = reverse("admin:catalog_imports_importitem_change", args=[obj.pk])
        candidates = list(
            obj.media_candidates.filter(
                kind=ImportMediaCandidate.KIND_GENERATION
            ).order_by("order", "id")
        )

        support = reference_support_report(obj)
        dynamic_slot_report = dynamic_verified_slot_report(
            obj,
            support=support,
        )
        fallback_refs = creative_fallback_reference_urls(obj, max_refs=3)
        profile = get_media_profile(obj)
        media_completion = practical_media_completion(obj)

        queue = []
        rows = []

        action_statuses = {
            ImportMediaCandidate.STATUS_PLANNED,
            ImportMediaCandidate.STATUS_FAILED,
            ImportMediaCandidate.STATUS_REJECTED,
        }

        for candidate in candidates:
            support_info = support.get(candidate.view_role) or {
                "supported": False,
                "reason": "No verified view support is available.",
            }
            exact_supported = bool(support_info.get("supported"))
            generation_policy = candidate_generation_policy(candidate)
            actual_only = candidate_is_actual_only(candidate)
            intentional_creative = generation_policy == POLICY_CREATIVE

            exact_generation_available = (
                candidate.status in action_statuses
                and exact_supported
                and not actual_only
                and not intentional_creative
            )

            capability = creative_fallback_capability(
                obj,
                candidate,
                support_info=support_info,
            )
            # Phase 5.2.4:
            # Reference-grounded creative media still requires a clean visual
            # anchor. Text-grounded creative media (Phase 5.2.3) deliberately
            # has zero visual references, so the old global fallback_refs gate
            # must not hide its action button.
            text_grounded_creative = bool(
                capability.get("text_grounded_creative")
            )
            creative_available = bool(
                capability.get("available")
                and (
                    fallback_refs
                    or text_grounded_creative
                )
            )

            if (
                not media_completion["stop_bulk_generation"]
                and candidate.status == ImportMediaCandidate.STATUS_PLANNED
                and exact_supported
                and not actual_only
                and not intentional_creative
            ):
                queue.append({
                    "id": candidate.pk,
                    "label": candidate_display_label(candidate),
                    "url": reverse(
                        "admin:catalog_imports_importitem_generate_candidate",
                        args=[obj.pk, candidate.pk],
                    ),
                })

            rows.append({
                "candidate": candidate,
                "display_label": candidate_display_label(candidate),
                "profile_label": candidate_profile_label(candidate),
                "generation_policy": generation_policy,
                "actual_only": actual_only,
                "intentional_creative": intentional_creative,
                "exact_supported": exact_supported,
                "exact_generation_available": exact_generation_available,
                "support_reason": _profile_aware_support_reason(candidate, support_info),
                "creative_fallback_available": creative_available,
                "text_grounded_creative": text_grounded_creative,
                "creative_fallback_reason": str(capability.get("reason") or ""),
                "creative_fallback_url": (
                    reverse(
                        "admin:catalog_imports_importitem_generate_creative_fallback",
                        args=[obj.pk, candidate.pk],
                    )
                    if creative_available else ""
                ),
                "optional_after_sufficient": bool(
                    media_completion["sufficient_for_review"]
                    and not candidate.asset_storage_name
                    and candidate.status in action_statuses
                ),
            })

        context = {
            **self.admin_site.each_context(request),
            "title": "Generate planned product media",
            "item": obj,
            "opts": self.model._meta,
            "change_url": change_url,
            "review_url": reverse(
                "admin:catalog_imports_importitem_media_review",
                args=[obj.pk],
            ),
            "rows": rows,
            "media_profile_key": profile.key,
            "media_profile_label": profile.label,
            "media_profile_notes": profile.notes,
            "queue_json": json.dumps(queue),
            "acquire_official_media_url": reverse(
                "admin:catalog_imports_importitem_acquire_official_media",
                args=[obj.pk],
            ),
            "official_media_report": obj.image_report or {},
            "dynamic_slot_report": dynamic_slot_report,
            "apply_dynamic_verified_slots_url": reverse(
                "admin:catalog_imports_importitem_apply_dynamic_verified_slots",
                args=[obj.pk],
            ),
            "media_completion": media_completion,
            "product_change_url": (
                reverse(
                    "admin:products_product_change",
                    args=[obj.created_product_id],
                )
                if obj.created_product_id else ""
            ),
        }
        return render(
            request,
            "admin/catalog_imports/importitem/generate_media.html",
            context,
        )

    def generate_candidate_view(self, request, object_id, candidate_id):
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": "POST required."}, status=405)
        obj = get_object_or_404(ImportItem, pk=object_id)
        if not self.has_change_permission(request, obj):
            raise PermissionDenied
        candidate = get_object_or_404(
            ImportMediaCandidate, pk=candidate_id, item=obj, kind=ImportMediaCandidate.KIND_GENERATION
        )
        try:
            materialize_candidate(candidate)
            candidate.refresh_from_db()
            preview_url = reverse(
                "admin:catalog_imports_importitem_media_preview",
                args=[obj.pk, candidate.pk],
            )
            return JsonResponse({
                "ok": True,
                "candidate_id": candidate.pk,
                "status": candidate.status,
                "status_label": candidate.get_status_display(),
                "preview_url": preview_url,
                "width": candidate.width,
                "height": candidate.height,
                "generation_attempts": candidate.generation_attempts,
            })
        except MediaGenerationError as exc:
            candidate.refresh_from_db()
            return JsonResponse({
                "ok": False,
                "candidate_id": candidate.pk,
                "status": candidate.status,
                "status_label": candidate.get_status_display(),
                "error": str(exc),
            }, status=400)

    def generate_creative_fallback_view(self, request, object_id, candidate_id):
        if request.method != "POST":
            return JsonResponse(
                {"ok": False, "error": "POST required."},
                status=405,
            )

        obj = get_object_or_404(ImportItem, pk=object_id)
        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        candidate = get_object_or_404(
            ImportMediaCandidate,
            pk=candidate_id,
            item=obj,
            kind=ImportMediaCandidate.KIND_GENERATION,
        )

        try:
            materialize_creative_fallback(candidate)
            candidate.refresh_from_db()
            preview_url = reverse(
                "admin:catalog_imports_importitem_media_preview",
                args=[obj.pk, candidate.pk],
            )
            return JsonResponse({
                "ok": True,
                "creative_fallback": True,
                "candidate_id": candidate.pk,
                "status": candidate.status,
                "status_label": candidate.get_status_display(),
                "mode_label": "Creative fallback — unverified perspective",
                "provider_key": candidate.provider_key,
                "preview_url": preview_url,
                "width": candidate.width,
                "height": candidate.height,
                "generation_attempts": candidate.generation_attempts,
            })
        except CreativeFallbackError as exc:
            candidate.refresh_from_db()
            return JsonResponse({
                "ok": False,
                "creative_fallback": True,
                "candidate_id": candidate.pk,
                "status": candidate.status,
                "status_label": candidate.get_status_display(),
                "error": str(exc),
            }, status=400)

    def media_review_view(self, request, object_id):
        obj = get_object_or_404(ImportItem, pk=object_id)
        if request.method == "POST":
            if not self.has_change_permission(request, obj):
                raise PermissionDenied
        elif not self.has_view_permission(request, obj):
            raise PermissionDenied
        change_url = reverse("admin:catalog_imports_importitem_change", args=[obj.pk])
        generate_url = reverse("admin:catalog_imports_importitem_generate_media", args=[obj.pk])

        if request.method == "POST":
            candidate_id = request.POST.get("candidate_id")
            action = str(request.POST.get("action") or "").strip().lower()
            candidate = get_object_or_404(
                ImportMediaCandidate, pk=candidate_id, item=obj, kind=ImportMediaCandidate.KIND_GENERATION
            )
            try:
                if action == "approve":
                    approve_candidate(
                        candidate,
                        actor=request.user,
                        exact_identity_verified=request.POST.get("exact_identity_verified") == "on",
                        watermark_clear=request.POST.get("watermark_clear") == "on",
                        source_identity_clear=request.POST.get("source_identity_clear") == "on",
                        rights_confirmed=request.POST.get("rights_confirmed") == "on",
                        creative_fallback_ack=request.POST.get("creative_fallback_ack") == "on",
                    )
                    messages.success(request, f"{candidate_display_label(candidate)} approved for Product media.")
                elif action == "reject":
                    reject_candidate(candidate, actor=request.user, reason=request.POST.get("rejection_reason", ""))
                    messages.warning(request, f"{candidate_display_label(candidate)} rejected.")
                elif action == "retry":
                    reset_candidate_for_retry(candidate, actor=request.user)
                    messages.info(request, f"{candidate_display_label(candidate)} returned to the generation queue.")
                    return redirect(generate_url)
                else:
                    raise MediaReviewError("Unknown media review action.")
            except MediaReviewError as exc:
                messages.warning(request, str(exc))
            return redirect(reverse("admin:catalog_imports_importitem_media_review", args=[obj.pk]))

        candidates = list(
            obj.media_candidates.filter(kind=ImportMediaCandidate.KIND_GENERATION).order_by("order", "id")
        )
        rows = []
        for candidate in candidates:
            reference_trace = reference_trace_for_candidate(candidate)
            text_grounding_trace = text_grounding_trace_for_candidate(candidate)
            provider_response = candidate.provider_response or {}
            is_text_grounded_creative = bool(
                provider_response.get("_arolana_text_grounded_creative")
                or text_grounding_trace.get("recorded")
            )
            preview_url = (
                reverse(
                    "admin:catalog_imports_importitem_media_preview",
                    args=[obj.pk, candidate.pk],
                )
                if candidate.asset_storage_alias and candidate.asset_storage_name
                else ""
            )
            current_support = reference_support_for_view(
                obj,
                candidate.view_role,
            )
            strict_reference_ok = bool(
                candidate.view_role == ImportMediaCandidate.VIEW_MAIN
                or is_creative_fallback_candidate(candidate)
                or current_support.get("supported")
            )

            rows.append({
                "candidate": candidate,
                "display_label": candidate_display_label(candidate),
                "profile_label": candidate_profile_label(candidate),
                "generation_policy": candidate_generation_policy(candidate),
                "actual_only": candidate_is_actual_only(candidate),
                "preview_url": preview_url,
                "download_url": (
                    preview_url + "?download=1"
                    if preview_url else ""
                ),
                "reference_trace": reference_trace,
                "reference_urls_used": reference_trace.get("reference_urls", []),
                "text_grounding_trace": text_grounding_trace,
                "is_text_grounded_creative": is_text_grounded_creative,
                "is_creative_fallback": is_creative_fallback_candidate(candidate),
                "strict_reference_ok": strict_reference_ok,
                "strict_reference_reason": str(current_support.get("reason") or ""),
                "can_downgrade_manual_creative": can_downgrade_to_manual_creative(candidate),
                "downgrade_manual_creative_url": reverse(
                    "admin:catalog_imports_importitem_downgrade_manual_creative",
                    args=[obj.pk, candidate.pk],
                ),
            })
        context = {
            **self.admin_site.each_context(request),
            "title": "Review generated product media",
            "item": obj,
            "opts": self.model._meta,
            "change_url": change_url,
            "generate_url": generate_url,
            "attach_url": reverse("admin:catalog_imports_importitem_attach_media", args=[obj.pk]),
            "rows": rows,
        }
        return render(request, "admin/catalog_imports/importitem/media_review.html", context)

    def media_preview_view(self, request, object_id, candidate_id):
        obj = get_object_or_404(ImportItem, pk=object_id)
        if not self.has_view_permission(request, obj):
            raise PermissionDenied
        candidate = get_object_or_404(ImportMediaCandidate, pk=candidate_id, item=obj)
        alias = str(candidate.asset_storage_alias or "").strip()
        name = str(candidate.asset_storage_name or "").strip()
        if not alias or not name:
            raise Http404("Generated review asset is not available.")
        try:
            storage = storages[alias]
            handle = storage.open(name, "rb")
        except Exception as exc:
            raise Http404("Generated review asset could not be opened.") from exc
        response = FileResponse(
            handle,
            content_type=candidate.mime_type or "image/webp",
        )
        disposition = (
            "attachment"
            if str(request.GET.get("download") or "") == "1"
            else "inline"
        )
        response["Content-Disposition"] = (
            f'{disposition}; filename="{candidate.asset_original_name or "review.webp"}"'
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    def attach_media_view(self, request, object_id):
        obj = get_object_or_404(ImportItem, pk=object_id)
        if request.method == "POST":
            if not self.has_change_permission(request, obj):
                raise PermissionDenied
        elif not self.has_view_permission(request, obj):
            raise PermissionDenied
        change_url = reverse("admin:catalog_imports_importitem_change", args=[obj.pk])
        if request.method != "POST":
            context = {
                **self.admin_site.each_context(request),
                "title": "Attach approved import media",
                "item": obj,
                "opts": self.model._meta,
                "change_url": change_url,
            }
            return render(
                request,
                "admin/catalog_imports/importitem/attach_media_confirm.html",
                context,
            )
        try:
            attached = attach_approved_media(obj)
        except MediaAttachmentError as exc:
            messages.warning(request, str(exc))
            return redirect(change_url + "#import-media-candidates-tab")
        messages.success(
            request,
            f"Attached {len(attached)} fully approved image(s) to the inactive Product draft. Nothing was published.",
        )
        return redirect(change_url + "#result-tab")

    @admin.display(description="Input")
    def short_input(self, obj):
        value = obj.input_value or ""
        return value if len(value) <= 70 else f"{value[:67]}..."

    def _pretty(self, value):
        return format_html(
            "<pre style='white-space:pre-wrap;max-width:1000px'>{}</pre>",
            json.dumps(value or {}, indent=2, ensure_ascii=False),
        )

    @admin.display(description="Raw source/evidence payload")
    def raw_payload_pretty(self, obj): return self._pretty(obj.raw_payload)
    @admin.display(description="Normalized Arolana draft")
    def normalized_payload_pretty(self, obj): return self._pretty(obj.normalized_payload)
    @admin.display(description="Verification report")
    def verification_report_pretty(self, obj): return self._pretty(obj.verification_report)
    @admin.display(description="Source contamination report")
    def contamination_report_pretty(self, obj): return self._pretty(obj.contamination_report)
    @admin.display(description="Image report")
    def image_report_pretty(self, obj): return self._pretty(obj.image_report)
    @admin.display(description="Duplicate report")
    def duplicate_report_pretty(self, obj): return self._pretty(obj.duplicate_report)
    @admin.display(description="Arolana draft preparation report")
    def draft_preparation_report_pretty(self, obj): return self._pretty(obj.draft_preparation_report)


@admin.register(ImportEvidence)
class ImportEvidenceAdmin(admin.ModelAdmin):
    list_display = (
        "id", "item", "role", "source_name", "status", "is_authoritative", "http_status", "created_at",
    )
    list_filter = ("role", "status", "is_authoritative", "created_at")
    search_fields = ("item__input_value", "url", "source_name", "error_message")
    readonly_fields = (
        "item", "role", "url", "source_name", "is_authoritative", "status", "http_status",
        "extracted_payload", "error_message", "notes", "created_at", "updated_at",
    )


@admin.register(ImportAuditEvent)
class ImportAuditEventAdmin(admin.ModelAdmin):
    list_display = ("id", "item", "event_type", "message", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("message", "item__input_value")
    readonly_fields = ("item", "event_type", "message", "payload", "created_at", "updated_at")
