from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from core.content_i18n import translated_field
from core.html_sanitization import rich_text_excerpt, rich_text_to_plain_text, sanitize_rich_html
from core.media_optimization import get_optimized_image_url, get_verified_optimized_image_url
from currency.templatetags.currency_filters import currency as format_currency

from .models import (
    ProviderKYCDocument,
    ProviderProfileChangeRequest,
    ProviderService,
    ServiceCategory,
    ServicePortfolio,
    ServiceProjectMedia,
    ServiceProjectProduct,
    ServiceProviderProfile,
    ServiceQuoteRequest,
    ServiceReview,
)
from .project_services import (
    project_video_embed_url,
    resolve_project_card_media,
    resolve_project_gallery_media,
    resolve_project_hero_media,
    resolve_project_primary_video,
    validate_external_project_video_url,
)


def absolute_optimized_url(request, image, preset, verify_exists=False):
    if not image:
        return ""
    try:
        resolver = get_verified_optimized_image_url if verify_exists else get_optimized_image_url
        url = resolver(image, preset)
    except Exception:
        return ""
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return request.build_absolute_uri(url) if request else url


def absolute_url(request, url):
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return request.build_absolute_uri(url) if request else url


class ServiceCategorySerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    provider_count = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()

    class Meta:
        model = ServiceCategory
        fields = ["id", "name", "slug", "description", "image", "icon", "provider_count"]

    def get_image(self, obj):
        return absolute_optimized_url(self.context.get("request"), obj.image, "category_card")

    def get_name(self, obj):
        return translated_field(obj, "name", request=self.context.get("request"))

    def get_description(self, obj):
        return translated_field(obj, "description", request=self.context.get("request"))

    def get_provider_count(self, obj):
        annotated_count = getattr(obj, "public_provider_count", None)
        if annotated_count is not None:
            return annotated_count
        return obj.provider_services.filter(
            is_active=True,
            provider__is_active=True,
            provider__verification_status__in=(
                ServiceProviderProfile.STATUS_APPROVED,
                ServiceProviderProfile.STATUS_VERIFIED,
            ),
        ).values("provider_id").distinct().count()


class ServiceCategorySummarySerializer(ServiceCategorySerializer):
    """Category metadata for nested service cards without count queries."""

    class Meta(ServiceCategorySerializer.Meta):
        fields = ["id", "name", "slug", "description", "image", "icon"]


class ProviderServiceSerializer(serializers.ModelSerializer):
    category = ServiceCategorySummarySerializer(read_only=True)
    service_name = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    description_html = serializers.SerializerMethodField()
    description_text = serializers.SerializerMethodField()
    excerpt = serializers.SerializerMethodField()
    starting_price_formatted = serializers.SerializerMethodField()
    formatted_starting_price = serializers.SerializerMethodField()
    provider = serializers.SerializerMethodField()
    absolute_url = serializers.SerializerMethodField()

    class Meta:
        model = ProviderService
        fields = [
            "id", "category", "service_name", "short_description", "description",
            "description_html", "description_text", "excerpt", "starting_price",
            "starting_price_formatted", "formatted_starting_price", "provider", "absolute_url",
            "is_active", "created_at", "updated_at",
        ]

    def get_service_name(self, obj):
        return translated_field(obj, "service_name", request=self.context.get("request"))

    def get_description(self, obj):
        return translated_field(obj, "description", request=self.context.get("request"))

    def _translated_description(self, obj):
        return translated_field(obj, "description", request=self.context.get("request")) or ""

    def get_description_html(self, obj):
        return sanitize_rich_html(self._translated_description(obj))

    def get_description_text(self, obj):
        return rich_text_to_plain_text(self._translated_description(obj))

    def get_excerpt(self, obj):
        return obj.short_description or rich_text_excerpt(self._translated_description(obj), limit=220)

    def get_starting_price_formatted(self, obj):
        if obj.starting_price is None:
            return ""
        return format_currency(obj.starting_price, self.context.get("request"))

    def get_formatted_starting_price(self, obj):
        return self.get_starting_price_formatted(obj)

    def get_provider(self, obj):
        provider = obj.provider
        return {
            "id": provider.id,
            "name": provider.business_name,
            "slug": provider.slug,
            "verified": provider.is_verified,
            "type": provider.get_provider_type_display(),
            "location": provider.location_label,
            "coverage": provider.service_coverage,
        }

    def get_absolute_url(self, obj):
        url = obj.get_absolute_url()
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url


class ProviderServiceSummarySerializer(ProviderServiceSerializer):
    """Compact marketplace payload; rich HTML is fetched on service detail."""

    class Meta(ProviderServiceSerializer.Meta):
        fields = [
            "id", "category", "service_name", "short_description", "excerpt",
            "starting_price", "starting_price_formatted", "formatted_starting_price",
            "provider", "absolute_url", "is_active", "created_at", "updated_at",
        ]


class ServicePortfolioSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    hero_image_url = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    primary_video = serializers.SerializerMethodField()
    has_video = serializers.SerializerMethodField()
    provider = serializers.SerializerMethodField()
    service_category = ServiceCategorySerializer(read_only=True)
    media = serializers.SerializerMethodField()
    media_groups = serializers.SerializerMethodField()
    products_used = serializers.SerializerMethodField()
    approval_status_label = serializers.CharField(source="get_approval_status_display", read_only=True)
    project_type_label = serializers.CharField(source="get_project_type_display", read_only=True)
    saved = serializers.SerializerMethodField()
    absolute_url = serializers.SerializerMethodField()
    customer_name_display = serializers.SerializerMethodField()

    class Meta:
        model = ServicePortfolio
        fields = [
            "id", "slug", "title", "short_summary", "description", "image", "image_url",
            "thumbnail_url", "hero_image_url",
            "project_type", "project_type_label", "service_category", "country", "state", "city",
            "location_display", "project_location", "completed_at", "project_duration_text",
            "customer_type", "customer_name_display", "show_project_value", "project_value_min",
            "project_value_max", "project_value_currency", "video_source", "video_url",
            "primary_video", "has_video",
            "video_duration", "challenge", "solution", "implementation_process", "project_result",
            "customer_outcome", "technologies_used", "services_performed", "approval_status",
            "approval_status_label", "moderation_notes", "is_verified_project", "is_featured",
            "views_count", "video_views_count", "product_click_count", "provider_click_count",
            "quote_requests_count", "shares_count", "saves_count", "completion_percent",
            "published_at", "created_at", "updated_at", "provider", "media", "media_groups", "products_used",
            "saved", "absolute_url",
        ]
        read_only_fields = [
            "slug", "approval_status", "moderation_notes", "is_verified_project", "is_featured",
            "views_count", "video_views_count", "product_click_count", "provider_click_count",
            "quote_requests_count", "shares_count", "saves_count", "published_at",
        ]

    def get_image(self, obj):
        media = resolve_project_card_media(obj)
        return absolute_url(self.context.get("request"), media.url)

    def get_image_url(self, obj):
        media = resolve_project_card_media(obj)
        return absolute_url(self.context.get("request"), media.url)

    def get_thumbnail_url(self, obj):
        media = resolve_project_card_media(obj)
        return absolute_url(self.context.get("request"), media.thumbnail_url or media.url)

    def get_hero_image_url(self, obj):
        media = resolve_project_hero_media(obj)
        return absolute_url(self.context.get("request"), media.url)

    def get_video_url(self, obj):
        primary_video = resolve_project_primary_video(obj)
        if not primary_video:
            return ""
        return absolute_url(
            self.context.get("request"),
            primary_video.video_url,
        )

    def get_primary_video(self, obj):
        primary_video = resolve_project_primary_video(obj)
        if not primary_video:
            return None
        request = self.context.get("request")
        payload = primary_video.as_dict()
        for key in (
            "url",
            "video_url",
            "thumbnail_url",
            "external_url",
        ):
            payload[key] = absolute_url(request, payload.get(key, ""))
        return payload

    def get_has_video(self, obj):
        return resolve_project_primary_video(obj) is not None

    def get_provider(self, obj):
        provider = obj.provider
        return {
            "id": provider.id,
            "name": provider.business_name,
            "slug": provider.slug,
            "verified": provider.is_verified,
            "provider_type": provider.get_provider_type_display(),
            "rating": provider.average_rating,
            "completed_projects": provider.portfolio_items.filter(
                approval_status=ServicePortfolio.STATUS_APPROVED,
                is_active=True,
            ).count(),
            "location": provider.location_label,
            "logo_url": absolute_optimized_url(self.context.get("request"), provider.business_logo or provider.profile_image, "logo"),
        }

    def get_media(self, obj):
        if obj.approval_status == ServicePortfolio.STATUS_APPROVED:
            request = self.context.get("request")
            return [
                {
                    **item.as_dict(),
                    "url": absolute_url(request, item.url),
                    "image_url": absolute_url(request, item.url) if item.kind == "image" else "",
                    "thumbnail_url": absolute_url(request, item.thumbnail_url),
                    "original_url": absolute_url(request, item.original_url),
                    "video_url": absolute_url(request, item.video_url),
                }
                for item in resolve_project_gallery_media(obj)
            ]
        return ServiceProjectMediaSerializer(
            obj.media_items.all(),
            many=True,
            context=self.context,
        ).data

    def get_media_groups(self, obj):
        items = self.get_media(obj)
        groups = []
        for stage, label in ServiceProjectMedia.STAGE_CHOICES:
            stage_items = [item for item in items if item.get("stage", "general") == stage]
            if stage_items:
                groups.append({"stage": stage, "label": label, "items": stage_items})
        return groups

    def get_products_used(self, obj):
        return ServiceProjectProductSerializer(
            obj.project_products.select_related("product", "product__vendor"),
            many=True,
            context=self.context,
        ).data

    def get_saved(self, obj):
        request = self.context.get("request")
        return bool(
            request
            and request.user.is_authenticated
            and obj.saved_by.filter(user=request.user).exists()
        )

    def get_absolute_url(self, obj):
        request = self.context.get("request")
        url = obj.get_absolute_url()
        return request.build_absolute_uri(url) if request else url

    def get_customer_name_display(self, obj):
        return obj.customer_name_display if obj.customer_consent_to_publish else ""


class ServiceProjectMediaSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    document_url = serializers.SerializerMethodField()
    embed_url = serializers.SerializerMethodField()
    mime_type = serializers.SerializerMethodField()
    is_playable = serializers.SerializerMethodField()
    media_type_label = serializers.CharField(source="get_media_type_display", read_only=True)
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)
    approval_status_label = serializers.CharField(source="get_approval_status_display", read_only=True)
    processing_status_label = serializers.CharField(source="get_processing_status_display", read_only=True)
    facebook_publication = serializers.SerializerMethodField()

    class Meta:
        model = ServiceProjectMedia
        fields = [
            "id", "media_type", "media_type_label", "stage", "stage_label",
            "image_url", "thumbnail_url", "video_url", "document_url",
            "external_video_url", "embed_url", "caption", "alt_text", "display_order",
            "is_featured", "is_cover", "approval_status", "approval_status_label",
            "moderation_note", "approved_at", "processing_status", "processing_status_label",
            "processing_error", "video_duration", "file_size", "mime_type", "is_playable",
            "original_filename", "facebook_publication", "created_at", "updated_at",
        ]

    def get_facebook_publication(self, obj):
        if not self.context.get("include_social_publications"):
            return None
        provider = getattr(getattr(obj, "project", None), "provider", None)
        if not provider or not provider.user_id:
            return None
        from social_publishing.models import SocialPlatform
        from social_publishing.services import publication_summary_for_content

        return publication_summary_for_content(
            obj,
            platform=SocialPlatform.FACEBOOK,
            owner_user_id=provider.user_id,
            owner_role="provider",
        )

    def get_image_url(self, obj):
        return absolute_optimized_url(self.context.get("request"), obj.image, "project_gallery", verify_exists=True)

    def get_thumbnail_url(self, obj):
        return absolute_optimized_url(
            self.context.get("request"),
            obj.thumbnail or obj.image,
            "project_thumb",
            verify_exists=True,
        )

    def get_video_url(self, obj):
        request = self.context.get("request")
        playable_video = obj.playable_video
        if playable_video:
            try:
                url = playable_video.url
                return request.build_absolute_uri(url) if request and not url.startswith(("http://", "https://")) else url
            except Exception:
                return ""
        external_url = str(obj.external_video_url or "").strip()
        return external_url if project_video_embed_url(external_url) else ""

    def get_embed_url(self, obj):
        return project_video_embed_url(obj.external_video_url)

    def get_mime_type(self, obj):
        playable = obj.playable_video
        name = str(getattr(playable, "name", "") or "").lower()
        if name.endswith(".mp4"):
            return "video/mp4"
        if name.endswith(".webm"):
            return "video/webm"
        return str(obj.mime_type or "")

    def get_is_playable(self, obj):
        return bool(obj.playable_video or self.get_embed_url(obj))

    def get_document_url(self, obj):
        if not obj.document:
            return ""
        try:
            return absolute_url(self.context.get("request"), obj.document.url)
        except Exception:
            return ""


class ServiceProjectProductSerializer(serializers.ModelSerializer):
    product = serializers.SerializerMethodField()

    class Meta:
        model = ServiceProjectProduct
        fields = ["id", "product", "usage_note", "quantity_used", "is_primary_product", "display_order"]

    def get_product(self, obj):
        product = obj.product
        request = self.context.get("request")
        image = getattr(product, "main_image", None)
        url = product.get_absolute_url()
        vendor = getattr(product, "vendor", None)
        return {
            "id": product.id,
            "name": product.name,
            "slug": product.slug,
            "price": product.price,
            "stock": getattr(product, "stock_quantity", 0),
            "image_url": absolute_optimized_url(request, image, "product_card"),
            "url": request.build_absolute_uri(url) if request else url,
            "vendor_name": (
                getattr(getattr(vendor, "vendor_profile", None), "business_name", "")
                or getattr(vendor, "get_full_name", lambda: "")()
                or getattr(vendor, "username", "")
            ),
        }


class ServiceProjectWriteSerializer(serializers.ModelSerializer):
    product_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
    )

    class Meta:
        model = ServicePortfolio
        fields = [
            "title", "short_summary", "description", "project_type", "service_category",
            "country", "state", "city", "location_display", "completed_at",
            "project_duration_text", "customer_type", "customer_name_display",
            "customer_name_private", "customer_consent_to_publish", "project_value_min",
            "project_value_max", "project_value_currency", "show_project_value",
            "challenge", "solution", "implementation_process",
            "project_result", "customer_outcome", "technologies_used",
            "services_performed", "product_ids",
        ]

    def validate(self, attrs):
        title = (attrs.get("title") or getattr(self.instance, "title", "") or "").strip()
        if len(title) < 8:
            raise serializers.ValidationError({"title": "Use a descriptive project title of at least 8 characters."})
        category = attrs.get("service_category") or getattr(self.instance, "service_category", None)
        if category and not category.is_active:
            raise serializers.ValidationError({"service_category": "Choose an active service category."})
        return attrs

    def _sync_products(self, project, product_ids):
        if product_ids is None:
            return
        from products.models import Product

        products = Product.objects.filter(
            pk__in=product_ids,
            is_active=True,
            approval_status="approved",
        )
        project.project_products.exclude(product_id__in=products.values("id")).delete()
        existing = set(project.project_products.values_list("product_id", flat=True))
        ServiceProjectProduct.objects.bulk_create([
            ServiceProjectProduct(project=project, product=product, display_order=index)
            for index, product in enumerate(products)
            if product.id not in existing
        ])

    def create(self, validated_data):
        product_ids = validated_data.pop("product_ids", None)
        project = super().create(validated_data)
        self._sync_products(project, product_ids)
        return project

    def update(self, instance, validated_data):
        product_ids = validated_data.pop("product_ids", None)
        project = super().update(instance, validated_data)
        self._sync_products(project, product_ids)
        return project


class ServiceProjectMediaWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceProjectMedia
        fields = [
            "media_type", "stage", "image", "video", "document",
            "external_video_url", "thumbnail", "caption", "alt_text",
            "display_order", "is_featured", "is_cover",
        ]

    def validate(self, attrs):
        instance = self.instance
        media_type = attrs.get("media_type", getattr(instance, "media_type", ServiceProjectMedia.TYPE_IMAGE))
        image = attrs.get("image", getattr(instance, "image", None))
        video = attrs.get("video", getattr(instance, "video", None))
        document = attrs.get("document", getattr(instance, "document", None))
        external_video_url = attrs.get(
            "external_video_url",
            getattr(instance, "external_video_url", ""),
        )

        if external_video_url:
            try:
                external_video_url = validate_external_project_video_url(
                    external_video_url
                )
                attrs["external_video_url"] = external_video_url
            except DjangoValidationError as exc:
                raise serializers.ValidationError(
                    {"external_video_url": getattr(exc, "messages", None) or str(exc)}
                ) from exc

        if media_type == ServiceProjectMedia.TYPE_IMAGE:
            if not image:
                raise serializers.ValidationError({"image": "Upload an image for image media."})
            if video or document or external_video_url:
                raise serializers.ValidationError("Image media cannot contain video or document sources.")
        elif media_type == ServiceProjectMedia.TYPE_VIDEO:
            if not (video or external_video_url or getattr(instance, "processed_video", None)):
                raise serializers.ValidationError({"video": "Upload a video or provide a supported video URL."})
            if image or document:
                raise serializers.ValidationError("Video media cannot contain image or document sources.")
            if video and external_video_url:
                raise serializers.ValidationError("Use either a local video or an external video URL, not both.")
        elif media_type == ServiceProjectMedia.TYPE_DOCUMENT:
            if not document:
                raise serializers.ValidationError({"document": "Upload a supporting document."})
            if image or video or external_video_url:
                raise serializers.ValidationError("Document media cannot contain image or video sources.")
        else:
            raise serializers.ValidationError({"media_type": "Choose a supported media type."})

        if attrs.get("is_cover", getattr(instance, "is_cover", False)) and media_type != ServiceProjectMedia.TYPE_IMAGE:
            raise serializers.ValidationError({"is_cover": "Only an image can be the project cover."})
        stage = attrs.get("stage", getattr(instance, "stage", ServiceProjectMedia.STAGE_GENERAL))
        if stage == ServiceProjectMedia.STAGE_COVER and media_type != ServiceProjectMedia.TYPE_IMAGE:
            raise serializers.ValidationError({"stage": "Only an image can use the cover stage."})
        if stage == ServiceProjectMedia.STAGE_SUPPORTING_DOCUMENT and media_type != ServiceProjectMedia.TYPE_DOCUMENT:
            raise serializers.ValidationError({"stage": "The supporting document stage is only for documents."})
        return attrs


class ServiceReviewSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = ServiceReview
        fields = [
            "id", "rating", "comment", "professionalism_rating",
            "communication_rating", "quality_rating", "timeliness_rating",
            "customer_name", "created_at",
        ]

    def get_customer_name(self, obj):
        if not obj.customer:
            return "Arolana customer"
        return obj.customer.get_full_name() or obj.customer.username


class ServiceProviderListSerializer(serializers.ModelSerializer):
    profile_image = serializers.SerializerMethodField()
    business_logo = serializers.SerializerMethodField()
    business_banner = serializers.SerializerMethodField()
    provider_type_label = serializers.CharField(source="get_provider_type_display", read_only=True)
    location = serializers.CharField(source="location_label", read_only=True)
    services = serializers.SerializerMethodField()
    whatsapp_url = serializers.CharField(read_only=True)
    verified = serializers.BooleanField(source="is_verified", read_only=True)
    profile_completion_percent = serializers.IntegerField(read_only=True)
    can_receive_serious_jobs = serializers.BooleanField(read_only=True)
    approval_allows_dashboard = serializers.BooleanField(read_only=True)
    sensitive_update_locked = serializers.BooleanField(read_only=True)
    sensitive_update_available_at = serializers.DateTimeField(read_only=True)
    description = serializers.SerializerMethodField()
    approved_project_count = serializers.IntegerField(read_only=True)
    rating_label = serializers.SerializerMethodField()
    effective_subscription = serializers.SerializerMethodField()
    absolute_url = serializers.SerializerMethodField()

    class Meta:
        model = ServiceProviderProfile
        fields = [
            "id", "business_name", "slug", "provider_type", "provider_type_label",
            "profile_image", "business_logo", "business_banner", "location", "service_coverage", "description",
            "years_of_experience", "average_rating", "total_reviews", "rating_label",
            "total_completed_jobs", "approved_project_count", "verified", "phone_number", "whatsapp_number",
            "whatsapp_url", "services", "verification_status", "kyc_status",
            "subscription_plan", "subscription_status", "profile_completion_percent",
            "effective_subscription", "absolute_url",
            "availability_status", "is_active", "approval_allows_dashboard",
            "can_receive_serious_jobs", "sensitive_update_locked",
            "sensitive_update_available_at",
        ]

    def get_profile_image(self, obj):
        return absolute_optimized_url(self.context.get("request"), obj.profile_image, "provider_profile")

    def get_description(self, obj):
        return translated_field(obj, "description", request=self.context.get("request"))

    def get_business_logo(self, obj):
        return absolute_optimized_url(self.context.get("request"), obj.business_logo, "provider_logo")

    def get_business_banner(self, obj):
        return absolute_optimized_url(self.context.get("request"), obj.business_banner, "provider_banner")

    def get_rating_label(self, obj):
        return f"{obj.average_rating} ({obj.total_reviews} reviews)" if obj.total_reviews else "No reviews yet"

    def get_effective_subscription(self, obj):
        from subscriptions.lifecycle import get_effective_subscription

        return get_effective_subscription(obj.user, role_context="provider").as_dict()

    def get_absolute_url(self, obj):
        url = obj.get_absolute_url()
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url

    def get_services(self, obj):
        prefetched = getattr(obj, "public_services", None)
        if prefetched is None:
            prefetched = obj.services.filter(is_active=True).select_related("category", "provider")
        return ProviderServiceSummarySerializer(prefetched, many=True, context=self.context).data


class ServiceProviderDetailSerializer(ServiceProviderListSerializer):
    portfolio = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()

    class Meta(ServiceProviderListSerializer.Meta):
        fields = ServiceProviderListSerializer.Meta.fields + [
            "contact_person", "email", "website", "country", "state", "city",
            "address", "portfolio", "reviews", "admin_note", "rejection_reason",
            "changes_requested_note", "submitted_at", "review_due_at", "approved_at",
            "rejected_at", "changes_requested_at", "kyc_note", "kyc_expires_at",
            "subscription_expires_at",
            "preferred_language", "notification_preferences", "business_hours",
            "business_hours_data",
            "availability_note", "support_phone", "support_email", "support_whatsapp",
            "profile_missing_steps",
        ]

    def get_reviews(self, obj):
        queryset = obj.reviews.filter(is_approved=True).select_related("customer")
        return ServiceReviewSerializer(queryset, many=True, context=self.context).data

    def get_portfolio(self, obj):
        queryset = obj.portfolio_items.filter(
            approval_status=ServicePortfolio.STATUS_APPROVED,
            is_active=True,
        ).optimized()
        return ServicePortfolioSerializer(queryset, many=True, context=self.context).data


class ProviderRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceProviderProfile
        fields = [
            "business_name", "contact_person", "provider_type", "phone_number",
            "whatsapp_number", "email", "website", "country", "state", "city",
            "address", "service_coverage", "description", "years_of_experience", "cac_number",
            "preferred_language", "support_phone", "support_email", "support_whatsapp",
            "business_hours", "business_hours_data", "availability_status",
            "availability_note", "notification_preferences",
        ]


class ServiceQuoteRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceQuoteRequest
        fields = [
            "provider", "category", "product", "name", "phone", "whatsapp",
            "email", "state", "city", "address", "service_needed", "message",
            "preferred_date", "preferred_time", "budget", "contact_preference", "urgency",
        ]

    def validate_provider(self, provider):
        if provider and not ServiceProviderProfile.objects.public().filter(pk=provider.pk).exists():
            raise serializers.ValidationError("Select an approved verified provider.")
        return provider


class ServiceReviewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceReview
        fields = [
            "provider", "rating", "comment", "professionalism_rating",
            "communication_rating", "quality_rating", "timeliness_rating",
        ]

    def validate_provider(self, provider):
        if not ServiceProviderProfile.objects.public().filter(pk=provider.pk).exists():
            raise serializers.ValidationError("Provider is not publicly available.")
        return provider


class ProviderChangeRequestSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.business_name", read_only=True)

    class Meta:
        model = ProviderProfileChangeRequest
        fields = [
            "id", "provider", "provider_name", "old_values", "proposed_values",
            "sensitive_fields", "status", "admin_note", "created_at", "reviewed_at",
        ]
        read_only_fields = ["provider", "old_values", "sensitive_fields", "status", "admin_note", "created_at", "reviewed_at"]


class ProviderKYCDocumentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    document_type_label = serializers.CharField(source="get_document_type_display", read_only=True)

    class Meta:
        model = ProviderKYCDocument
        fields = ["id", "document_type", "document_type_label", "file", "file_url", "note", "is_active", "created_at"]
        extra_kwargs = {"file": {"write_only": True}}

    def get_file_url(self, obj):
        request = self.context.get("request")
        if not obj.file:
            return ""
        try:
            url = obj.file.url
        except Exception:
            return ""
        return request.build_absolute_uri(url) if request and not url.startswith(("http://", "https://")) else url


class ProviderQuoteRequestSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    category_name = serializers.CharField(source="category.name", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    completion_photo = serializers.SerializerMethodField()

    class Meta:
        model = ServiceQuoteRequest
        fields = [
            "id", "customer_name", "category", "category_name", "product", "product_name",
            "name", "phone", "whatsapp", "email", "state", "city", "address",
            "service_needed", "message", "preferred_date", "preferred_time", "budget",
            "contact_preference", "urgency", "provider_note", "admin_note",
            "completion_photo", "status", "assigned_at", "accepted_at",
            "completed_at", "created_at", "updated_at",
        ]

    def get_customer_name(self, obj):
        if obj.customer:
            return obj.customer.get_full_name() or obj.customer.username or obj.customer.email
        return obj.name

    def get_completion_photo(self, obj):
        return absolute_optimized_url(self.context.get("request"), obj.completion_photo, "product_card")
