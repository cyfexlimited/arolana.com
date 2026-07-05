from rest_framework import serializers

from core.content_i18n import translated_field
from core.media_optimization import get_optimized_image_url

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


def absolute_optimized_url(request, image, preset):
    if not image:
        return ""
    try:
        url = get_optimized_image_url(image, preset)
    except Exception:
        return ""
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
        return obj.provider_services.filter(
            is_active=True,
            provider__is_active=True,
            provider__is_verified=True,
            provider__verification_status=ServiceProviderProfile.STATUS_APPROVED,
        ).values("provider_id").distinct().count()


class ProviderServiceSerializer(serializers.ModelSerializer):
    category = ServiceCategorySerializer(read_only=True)
    service_name = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()

    class Meta:
        model = ProviderService
        fields = ["id", "category", "service_name", "description", "starting_price"]

    def get_service_name(self, obj):
        return translated_field(obj, "service_name", request=self.context.get("request"))

    def get_description(self, obj):
        return translated_field(obj, "description", request=self.context.get("request"))


class ServicePortfolioSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    hero_image_url = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    provider = serializers.SerializerMethodField()
    service_category = ServiceCategorySerializer(read_only=True)
    media = serializers.SerializerMethodField()
    products_used = serializers.SerializerMethodField()
    approval_status_label = serializers.CharField(source="get_approval_status_display", read_only=True)
    project_type_label = serializers.CharField(source="get_project_type_display", read_only=True)
    saved = serializers.SerializerMethodField()
    absolute_url = serializers.SerializerMethodField()
    customer_name_display = serializers.SerializerMethodField()

    class Meta:
        model = ServicePortfolio
        fields = [
            "id", "slug", "title", "short_summary", "description", "image", "hero_image_url",
            "project_type", "project_type_label", "service_category", "country", "state", "city",
            "location_display", "project_location", "completed_at", "project_duration_text",
            "customer_type", "customer_name_display", "show_project_value", "project_value_min",
            "project_value_max", "project_value_currency", "video_source", "video_url",
            "video_duration", "challenge", "solution", "implementation_process", "project_result",
            "customer_outcome", "technologies_used", "services_performed", "approval_status",
            "approval_status_label", "moderation_notes", "is_verified_project", "is_featured",
            "views_count", "video_views_count", "product_click_count", "provider_click_count",
            "quote_requests_count", "shares_count", "saves_count", "completion_percent",
            "published_at", "created_at", "updated_at", "provider", "media", "products_used",
            "saved", "absolute_url",
        ]
        read_only_fields = [
            "slug", "approval_status", "moderation_notes", "is_verified_project", "is_featured",
            "views_count", "video_views_count", "product_click_count", "provider_click_count",
            "quote_requests_count", "shares_count", "saves_count", "published_at",
        ]

    def get_image(self, obj):
        media = obj.featured_media
        source = obj.image or getattr(media, "image", None) or getattr(media, "thumbnail", None)
        return absolute_optimized_url(self.context.get("request"), source, "project_card")

    def get_hero_image_url(self, obj):
        media = obj.featured_media
        source = obj.image or getattr(media, "image", None) or getattr(media, "thumbnail", None)
        return absolute_optimized_url(self.context.get("request"), source, "project_hero")

    def get_video_url(self, obj):
        request = self.context.get("request")
        if obj.local_video:
            try:
                value = obj.local_video.url
                return request.build_absolute_uri(value) if request and not value.startswith(("http://", "https://")) else value
            except Exception:
                pass
        return obj.video_url or ""

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
        return ServiceProjectMediaSerializer(
            obj.public_media if obj.approval_status == ServicePortfolio.STATUS_APPROVED else obj.media_items.all(),
            many=True,
            context=self.context,
        ).data

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
    media_type_label = serializers.CharField(source="get_media_type_display", read_only=True)

    class Meta:
        model = ServiceProjectMedia
        fields = [
            "id", "media_type", "media_type_label", "image_url", "thumbnail_url",
            "video_url", "external_video_url", "caption", "alt_text", "display_order",
            "is_featured", "approval_status", "created_at",
        ]

    def get_image_url(self, obj):
        return absolute_optimized_url(self.context.get("request"), obj.image, "project_gallery")

    def get_thumbnail_url(self, obj):
        return absolute_optimized_url(
            self.context.get("request"),
            obj.thumbnail or obj.image,
            "project_thumb",
        )

    def get_video_url(self, obj):
        request = self.context.get("request")
        if obj.video:
            try:
                url = obj.video.url
                return request.build_absolute_uri(url) if request and not url.startswith(("http://", "https://")) else url
            except Exception:
                return ""
        return obj.external_video_url or ""


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
            "image", "video_source", "video_url", "local_video", "video_thumbnail",
            "video_duration", "challenge", "solution", "implementation_process",
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
            "media_type", "image", "video", "external_video_url", "thumbnail",
            "caption", "alt_text", "display_order", "is_featured",
        ]

    def validate(self, attrs):
        if not any(attrs.get(field) for field in ("image", "video", "external_video_url")):
            raise serializers.ValidationError("Upload an image/video or add a supported video URL.")
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
    services = ProviderServiceSerializer(many=True, read_only=True)
    whatsapp_url = serializers.CharField(read_only=True)
    verified = serializers.BooleanField(source="is_verified", read_only=True)
    profile_completion_percent = serializers.IntegerField(read_only=True)
    can_receive_serious_jobs = serializers.BooleanField(read_only=True)
    approval_allows_dashboard = serializers.BooleanField(read_only=True)
    sensitive_update_locked = serializers.BooleanField(read_only=True)
    sensitive_update_available_at = serializers.DateTimeField(read_only=True)
    description = serializers.SerializerMethodField()

    class Meta:
        model = ServiceProviderProfile
        fields = [
            "id", "business_name", "slug", "provider_type", "provider_type_label",
            "profile_image", "business_logo", "business_banner", "location", "service_coverage", "description",
            "years_of_experience", "average_rating", "total_reviews",
            "total_completed_jobs", "verified", "phone_number", "whatsapp_number",
            "whatsapp_url", "services", "verification_status", "kyc_status",
            "subscription_plan", "subscription_status", "profile_completion_percent",
            "availability_status", "is_active", "approval_allows_dashboard",
            "can_receive_serious_jobs", "sensitive_update_locked",
            "sensitive_update_available_at",
        ]

    def get_profile_image(self, obj):
        return absolute_optimized_url(self.context.get("request"), obj.profile_image, "avatar")

    def get_description(self, obj):
        return translated_field(obj, "description", request=self.context.get("request"))

    def get_business_logo(self, obj):
        return absolute_optimized_url(self.context.get("request"), obj.business_logo, "avatar")

    def get_business_banner(self, obj):
        return absolute_optimized_url(self.context.get("request"), obj.business_banner, "hero")


class ServiceProviderDetailSerializer(ServiceProviderListSerializer):
    portfolio = ServicePortfolioSerializer(source="portfolio_items", many=True, read_only=True)
    reviews = serializers.SerializerMethodField()

    class Meta(ServiceProviderListSerializer.Meta):
        fields = ServiceProviderListSerializer.Meta.fields + [
            "contact_person", "email", "website", "country", "state", "city",
            "address", "portfolio", "reviews", "admin_note", "rejection_reason",
            "changes_requested_note", "submitted_at", "review_due_at", "approved_at",
            "rejected_at", "changes_requested_at", "kyc_note", "kyc_expires_at",
            "subscription_expires_at",
            "preferred_language", "notification_preferences", "business_hours",
            "availability_note", "support_phone", "support_email", "support_whatsapp",
        ]

    def get_reviews(self, obj):
        queryset = obj.reviews.filter(is_approved=True).select_related("customer")
        return ServiceReviewSerializer(queryset, many=True, context=self.context).data


class ProviderRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceProviderProfile
        fields = [
            "business_name", "contact_person", "provider_type", "phone_number",
            "whatsapp_number", "email", "website", "country", "state", "city",
            "address", "service_coverage", "description", "years_of_experience", "cac_number",
            "preferred_language", "support_phone", "support_email", "support_whatsapp",
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
