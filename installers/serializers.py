from rest_framework import serializers

from core.media_optimization import get_optimized_image_url

from .models import (
    ProviderKYCDocument,
    ProviderProfileChangeRequest,
    ProviderService,
    ServiceCategory,
    ServicePortfolio,
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

    class Meta:
        model = ServiceCategory
        fields = ["id", "name", "slug", "description", "image", "icon", "provider_count"]

    def get_image(self, obj):
        return absolute_optimized_url(self.context.get("request"), obj.image, "category_card")

    def get_provider_count(self, obj):
        return obj.provider_services.filter(
            is_active=True,
            provider__is_active=True,
            provider__is_verified=True,
            provider__verification_status=ServiceProviderProfile.STATUS_APPROVED,
        ).values("provider_id").distinct().count()


class ProviderServiceSerializer(serializers.ModelSerializer):
    category = ServiceCategorySerializer(read_only=True)

    class Meta:
        model = ProviderService
        fields = ["id", "category", "service_name", "description", "starting_price"]


class ServicePortfolioSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = ServicePortfolio
        fields = ["id", "title", "description", "image", "video_url", "project_location", "completed_at"]

    def get_image(self, obj):
        return absolute_optimized_url(self.context.get("request"), obj.image, "category_card")


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
