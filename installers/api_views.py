from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from mobile_customers.views import _auth_mobile_customer_from_request_data
from notifications.models import Notification
from products.models import Product
from arolana_payments.models import PaymentMethod
from arolana_payments.services import gateway_is_available
from subscriptions.lifecycle import (
    activate_free_subscription,
    create_subscription_payment,
    get_effective_subscription,
    get_plan_entitlements,
    official_plans,
)
from subscriptions.models import SubscriptionPlan, VendorSubscription
from .models import (
    ProviderKYCDocument,
    ProviderProfileChangeRequest,
    ServiceCategory,
    ServicePortfolio,
    ServiceProviderProfile,
    ServiceQuoteRequest,
    ProviderService,
)
from .forms import ProviderServiceForm
from .service_offerings import ProviderServicePolicy
from .serializers import (
    ProviderChangeRequestSerializer,
    ProviderKYCDocumentSerializer,
    ProviderQuoteRequestSerializer,
    ProviderRegistrationSerializer,
    ProviderServiceSerializer,
    ServiceCategorySerializer,
    ServicePortfolioSerializer,
    ServiceProviderDetailSerializer,
    ServiceProviderListSerializer,
    ServiceQuoteRequestSerializer,
    ServiceReviewCreateSerializer,
)
from .project_services import ProjectEntitlementService
from .services import (
    assign_service_request,
    filter_public_providers,
    submit_provider_kyc,
    submit_provider_profile,
    update_provider_profile,
    notify_staff_provider_registration,
    notify_staff_service_quote,
    provider_workspace_notifications,
    suggested_categories_for_product,
    suggested_providers_for_product,
)


def request_user_from_mobile_payload(request):
    if request.user and request.user.is_authenticated:
        return request.user
    try:
        customer = _auth_mobile_customer_from_request_data(request.data)
    except Exception:
        return None
    return getattr(customer, "user", None)


def provider_user_from_request(request):
    if request.user and request.user.is_authenticated:
        return request.user
    token = request.headers.get("Authorization", "").replace("Bearer", "").strip() or request.query_params.get("token") or request.data.get("token")
    if token:
        try:
            from staff_mobile.models import StaffMobileToken

            session = StaffMobileToken.objects.select_related("user").filter(token=token, is_active=True).first()
            if session and session.user:
                session.last_used_at = timezone.now()
                session.save(update_fields=["last_used_at", "updated_at"])
                return session.user
        except Exception:
            pass
    return request_user_from_mobile_payload(request)


def provider_from_request(request, require_dashboard=False):
    user = provider_user_from_request(request)
    if not user:
        return None, Response({"detail": "Provider login is required."}, status=status.HTTP_401_UNAUTHORIZED)
    provider = ServiceProviderProfile.objects.filter(user=user).first()
    if not provider:
        return None, Response({"detail": "Provider profile was not found."}, status=status.HTTP_404_NOT_FOUND)
    if require_dashboard and not provider.approval_allows_dashboard:
        return provider, Response({
            "detail": "Provider profile is not approved yet.",
            "provider": ServiceProviderDetailSerializer(provider, context={"request": request}).data,
        }, status=status.HTTP_403_FORBIDDEN)
    return provider, None


def provider_notification_payload(note):
    title = (note.title or "").lower()
    metadata = note.metadata or {}
    if metadata.get("service_quote_request_id"):
        category = "job"
    elif "kyc" in title:
        category = "kyc"
    elif "subscription" in title or "plan" in title:
        category = "subscription"
    elif "support" in title:
        category = "support"
    elif "callback" in title:
        category = "callback"
    elif note.notification_type == "security":
        category = "security"
    else:
        category = "application"
    return {
        "id": note.id,
        "title": note.title,
        "message": note.message,
        "notification_type": note.notification_type,
        "category": category,
        "workspace": "provider",
        "priority": note.priority,
        "is_read": note.is_read,
        "created_at": note.created_at,
        "metadata": metadata,
    }


class ProviderListAPIView(generics.ListAPIView):
    serializer_class = ServiceProviderListSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return filter_public_providers(self.request.query_params).prefetch_related(
            Prefetch(
                "services",
                queryset=ProviderService.objects.filter(is_active=True).select_related("category", "provider"),
                to_attr="public_services",
            )
        )


class CategoryListAPIView(generics.ListAPIView):
    serializer_class = ServiceCategorySerializer
    permission_classes = [permissions.AllowAny]
    queryset = (
        ServiceCategory.objects.filter(is_active=True)
        .annotate(
            public_provider_count=Count(
                "provider_services__provider",
                filter=Q(
                    provider_services__is_active=True,
                    provider_services__provider__is_active=True,
                    provider_services__provider__verification_status__in=(
                        ServiceProviderProfile.STATUS_APPROVED,
                        ServiceProviderProfile.STATUS_VERIFIED,
                    ),
                ),
                distinct=True,
            )
        )
        .order_by("name")
    )
    pagination_class = None


class ProviderDetailAPIView(generics.RetrieveAPIView):
    serializer_class = ServiceProviderDetailSerializer
    permission_classes = [permissions.AllowAny]
    queryset = (
        ServiceProviderProfile.objects.public()
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "services",
                queryset=ProviderService.objects.filter(is_active=True).select_related("category", "provider"),
                to_attr="public_services",
            ),
            "portfolio_items",
            "reviews__customer",
        )
    )


class PublicProviderServiceDetailAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, provider_id, service_id):
        provider = get_object_or_404(
            ServiceProviderProfile.objects.public().select_related("user"),
            pk=provider_id,
        )
        service = get_object_or_404(
            ProviderService.objects.select_related("category", "provider", "provider__user"),
            pk=service_id,
            provider=provider,
            is_active=True,
        )
        return Response({
            "service": ProviderServiceSerializer(service, context={"request": request}).data,
            "provider": ServiceProviderListSerializer(provider, context={"request": request}).data,
        })


class ProviderRegistrationAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        user = provider_user_from_request(request)
        if not user:
            return Response({
                "detail": "Login is required before setting up a Provider profile.",
                "login_required": True,
            }, status=status.HTTP_401_UNAUTHORIZED)
        instance = ServiceProviderProfile.objects.filter(user=user).first()
        if instance and instance.verification_status in {
            ServiceProviderProfile.STATUS_SUBMITTED,
            ServiceProviderProfile.STATUS_PENDING,
        }:
            return Response({
                "detail": "Provider profile is already under review.",
                "provider": ServiceProviderDetailSerializer(instance, context={"request": request}).data,
            }, status=status.HTTP_409_CONFLICT)
        if instance and instance.verification_status in {
            ServiceProviderProfile.STATUS_APPROVED,
            ServiceProviderProfile.STATUS_VERIFIED,
        }:
            return Response({
                "detail": "Provider profile is already active. Use the profile change endpoint for updates.",
                "provider": ServiceProviderDetailSerializer(instance, context={"request": request}).data,
            }, status=status.HTTP_409_CONFLICT)
        if instance and instance.verification_status == ServiceProviderProfile.STATUS_SUSPENDED:
            return Response({
                "detail": "Provider profile is suspended. Contact Arolana support to appeal.",
                "provider": ServiceProviderDetailSerializer(instance, context={"request": request}).data,
            }, status=status.HTTP_403_FORBIDDEN)
        serializer = ProviderRegistrationSerializer(instance, data=request.data, partial=bool(instance))
        serializer.is_valid(raise_exception=True)
        provider = serializer.save(
            user=user,
            verification_status=ServiceProviderProfile.STATUS_PENDING,
            is_verified=False,
        )
        submit_provider_profile(provider)
        return Response({
            "message": "Provider profile submitted for verification.",
            "provider": ServiceProviderDetailSerializer(provider, context={"request": request}).data,
        }, status=status.HTTP_200_OK if instance else status.HTTP_201_CREATED)


class QuoteRequestAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ServiceQuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quote = serializer.save(customer=request_user_from_mobile_payload(request))
        notify_staff_service_quote(quote)
        if quote.provider:
            Notification.send(
                quote.provider.user,
                "message",
                "New service quote request",
                f"{quote.name} requested {quote.service_needed} in {quote.city}, {quote.state}.",
                link="/installers/dashboard/",
                metadata={"service_quote_request_id": quote.id, "product_id": quote.product_id},
                priority=3,
            )
        return Response({"message": "Service quote request sent.", "id": quote.id}, status=status.HTTP_201_CREATED)


class ReviewCreateAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ServiceReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review = serializer.save(customer=request_user_from_mobile_payload(request), is_approved=False)
        return Response({"message": "Review submitted for moderation.", "id": review.id}, status=status.HTTP_201_CREATED)


class SuggestedProvidersAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, product_id):
        product = get_object_or_404(
            Product.objects.select_related("category__parent", "brand"),
            pk=product_id,
            is_active=True,
            approval_status="approved",
        )
        categories = suggested_categories_for_product(product)
        providers = suggested_providers_for_product(product)
        return Response({
            "service_available": bool(categories),
            "related_service_categories": ServiceCategorySerializer(categories, many=True, context={"request": request}).data,
            "suggested_service_providers": ServiceProviderListSerializer(providers, many=True, context={"request": request}).data,
            "request_service_quote_endpoint": request.build_absolute_uri("/api/installers/quote-request/"),
        })


class ProviderMeAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        user = provider_user_from_request(request)
        if not user:
            return Response({"detail": "Provider login is required."}, status=status.HTTP_401_UNAUTHORIZED)
        provider = ServiceProviderProfile.objects.filter(user=user).first()
        if not provider:
            return Response({
                "provider": None,
                "profile_required": True,
                "next_action": "set_up_provider_profile",
                "message": "Set up a Provider / Installer / Engineer profile for this Arolana account.",
            })
        return Response({
            "provider": ServiceProviderDetailSerializer(provider, context={"request": request}).data,
            "profile_required": False,
            "next_action": "view_provider_status" if not provider.approval_allows_dashboard else "provider_dashboard",
            "pending_change_requests": ProviderChangeRequestSerializer(
                provider.profile_change_requests.filter(status=ProviderProfileChangeRequest.STATUS_PENDING),
                many=True,
                context={"request": request},
            ).data,
            "kyc_documents": ProviderKYCDocumentSerializer(provider.kyc_documents.filter(is_active=True), many=True, context={"request": request}).data,
        })


class ProviderProfileAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def patch(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        serializer = ProviderRegistrationSerializer(provider, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            provider, change = update_provider_profile(provider, serializer.validated_data, user=provider.user)
        except DjangoValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        return Response({
            "message": "Profile updated." if not change else "Profile change submitted for admin approval.",
            "provider": ServiceProviderDetailSerializer(provider, context={"request": request}).data,
            "change_request": ProviderChangeRequestSerializer(change, context={"request": request}).data if change else None,
        })


class ProviderChangeRequestAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        queryset = provider.profile_change_requests.all()
        return Response({"change_requests": ProviderChangeRequestSerializer(queryset, many=True, context={"request": request}).data})

    def post(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        try:
            provider, change = update_provider_profile(provider, request.data, user=provider.user)
        except DjangoValidationError as exc:
            message = exc.messages[0] if getattr(exc, "messages", None) else str(exc)
            return Response({"detail": message}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        return Response({
            "message": "Change submitted for approval." if change else "Profile updated.",
            "change_request": ProviderChangeRequestSerializer(change, context={"request": request}).data if change else None,
        }, status=status.HTTP_201_CREATED if change else status.HTTP_200_OK)


class ProviderMediaUploadAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    field_name = ""

    def post(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        upload = request.FILES.get("file") or request.FILES.get(self.field_name)
        if not upload:
            return Response({"detail": "Upload file is required."}, status=status.HTTP_400_BAD_REQUEST)
        if provider.approval_allows_dashboard:
            if provider.sensitive_update_locked:
                available = provider.sensitive_update_available_at
                return Response({"detail": f"Sensitive profile changes are locked until {available:%Y-%m-%d}."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            if provider.profile_change_requests.filter(status=ProviderProfileChangeRequest.STATUS_PENDING).exists():
                return Response(
                    {"detail": "A sensitive profile update is already awaiting Arolana approval."},
                    status=status.HTTP_409_CONFLICT,
                )
            change = ProviderProfileChangeRequest.objects.create(
                provider=provider,
                requested_by=provider.user,
                old_values={self.field_name: getattr(getattr(provider, self.field_name, None), "name", "")},
                proposed_values={self.field_name: getattr(upload, "name", "uploaded file")},
                sensitive_fields=[self.field_name],
                proposed_file=upload,
                proposed_file_field=self.field_name,
            )
            return Response({
                "message": "Upload submitted for admin approval.",
                "change_request": ProviderChangeRequestSerializer(change, context={"request": request}).data,
            }, status=status.HTTP_201_CREATED)
        else:
            setattr(provider, self.field_name, upload)
            provider.save(update_fields=[self.field_name, "updated_at"])
        return Response({
            "message": "Upload saved.",
            "provider": ServiceProviderDetailSerializer(provider, context={"request": request}).data,
        })


class ProviderLogoUploadAPIView(ProviderMediaUploadAPIView):
    field_name = "business_logo"


class ProviderBannerUploadAPIView(ProviderMediaUploadAPIView):
    field_name = "business_banner"


class ProviderProfileImageUploadAPIView(ProviderMediaUploadAPIView):
    field_name = "profile_image"


class ProviderPortfolioAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        queryset = provider.portfolio_items.filter(
            approval_status=ServicePortfolio.STATUS_APPROVED,
            is_active=True,
        ).optimized()
        return Response({
            "portfolio": ServicePortfolioSerializer(
                queryset,
                many=True,
                context={"request": request},
            ).data,
        })

    def post(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        title = str(request.data.get("title", "")).strip()
        image = request.FILES.get("image")
        video_url = str(request.data.get("video_url", "")).strip()
        if not title or (not image and not video_url):
            return Response(
                {"detail": "Add a project title and an image or video URL."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        portfolio = ServicePortfolio.objects.create(
            provider=provider,
            title=title,
            description=str(request.data.get("description", "")).strip(),
            image=image,
            video_url=video_url,
            project_location=str(request.data.get("project_location", "")).strip(),
        )
        return Response({
            "message": "Portfolio project added.",
            "portfolio": ServicePortfolioSerializer(portfolio, context={"request": request}).data,
        }, status=status.HTTP_201_CREATED)


class ProviderServicesAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        categories = (
            ServiceCategory.objects.filter(is_active=True)
            .annotate(
                public_provider_count=Count(
                    "provider_services__provider",
                    filter=Q(
                        provider_services__is_active=True,
                        provider_services__provider__is_active=True,
                        provider_services__provider__verification_status__in=(
                            ServiceProviderProfile.STATUS_APPROVED,
                            ServiceProviderProfile.STATUS_VERIFIED,
                        ),
                    ),
                    distinct=True,
                )
            )
            .order_by("name")
        )
        return Response({
            "services": ProviderServiceSerializer(
                provider.services.select_related("category", "provider"),
                many=True,
                context={"request": request},
            ).data,
            "categories": ServiceCategorySerializer(categories, many=True, context={"request": request}).data,
            "service_access": ProviderServicePolicy(provider).payload(),
        })

    def post(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        service_id = request.data.get("id")
        service = provider.services.filter(pk=service_id).first() if service_id else None
        payload = request.data.copy()
        if "is_active" not in payload:
            payload["is_active"] = True if service is None else service.is_active
        form = ProviderServiceForm(payload, instance=service)
        if not form.is_valid():
            return Response({"detail": "Check the service details.", "errors": form.errors}, status=status.HTTP_400_BAD_REQUEST)
        service = form.save(commit=False)
        service.provider = provider
        access = ProviderServicePolicy(provider).can_activate(service=service)
        if service.is_active and not access.allowed:
            return Response({"detail": access.message, "service_access": access.as_dict()}, status=status.HTTP_403_FORBIDDEN)
        service.save()
        return Response({
            "message": "Service offering saved.",
            "service": ProviderServiceSerializer(service, context={"request": request}).data,
            "service_access": ProviderServicePolicy(provider).payload(service=service),
        }, status=status.HTTP_200_OK if service_id else status.HTTP_201_CREATED)


class ProviderServiceDetailAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def delete(self, request, service_id):
        provider, error = provider_from_request(request)
        if error:
            return error
        service = provider.services.filter(pk=service_id).first()
        if not service:
            return Response({"detail": "Service offering not found."}, status=status.HTTP_404_NOT_FOUND)
        service.is_active = False
        service.save(update_fields=["is_active", "updated_at"])
        return Response({
            "message": "Service deactivated. Historical requests remain intact.",
            "service": ProviderServiceSerializer(service, context={"request": request}).data,
        })

    def patch(self, request, service_id):
        provider, error = provider_from_request(request)
        if error:
            return error
        service = provider.services.filter(pk=service_id).first()
        if not service:
            return Response({"detail": "Service offering not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = {
            "category": service.category_id,
            "service_name": service.service_name,
            "short_description": service.short_description,
            "description": service.description,
            "starting_price": service.starting_price,
            "is_active": service.is_active,
        }
        payload.update({key: value for key, value in request.data.items() if key in payload})
        form = ProviderServiceForm(payload, instance=service)
        if not form.is_valid():
            return Response({"detail": "Check the service details.", "errors": form.errors}, status=status.HTTP_400_BAD_REQUEST)
        service = form.save(commit=False)
        access = ProviderServicePolicy(provider).can_activate(service=service)
        if service.is_active and not access.allowed:
            return Response({"detail": access.message, "service_access": access.as_dict()}, status=status.HTTP_403_FORBIDDEN)
        service.save()
        return Response({
            "message": "Service offering updated.",
            "service": ProviderServiceSerializer(service, context={"request": request}).data,
            "service_access": ProviderServicePolicy(provider).payload(service=service),
        })


class ProviderKYCAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        created_documents = []
        for document_type in dict(ProviderKYCDocument.DOCUMENT_TYPES):
            upload = request.FILES.get(document_type)
            if upload:
                created_documents.append(ProviderKYCDocument.objects.create(provider=provider, document_type=document_type, file=upload))
        if request.FILES.get("file"):
            document_type = request.data.get("document_type") or ProviderKYCDocument.DOCUMENT_OTHER
            created_documents.append(ProviderKYCDocument.objects.create(provider=provider, document_type=document_type, file=request.FILES["file"], note=request.data.get("note", "")))
        if request.data.get("cac_number"):
            provider.cac_number = request.data.get("cac_number")
            provider.save(update_fields=["cac_number", "updated_at"])
        submit_provider_kyc(provider)
        return Response({
            "message": "KYC submitted for Arolana review.",
            "kyc_status": provider.kyc_status,
            "documents": ProviderKYCDocumentSerializer(created_documents, many=True, context={"request": request}).data,
        }, status=status.HTTP_201_CREATED)

    def get(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        return Response({
            "kyc_status": provider.kyc_status,
            "kyc_note": provider.kyc_note,
            "kyc_expires_at": provider.kyc_expires_at,
            "documents": ProviderKYCDocumentSerializer(provider.kyc_documents.filter(is_active=True), many=True, context={"request": request}).data,
        })


class ProviderDashboardAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        quotes = provider.quote_requests.all()
        notifications = provider_workspace_notifications(provider)
        active_jobs = quotes.filter(
            status__in=["assigned", "accepted", "on_the_way", "in_progress"]
        ).select_related("category", "product", "customer").order_by("-created_at")[:3]
        return Response({
            "provider": ServiceProviderDetailSerializer(provider, context={"request": request}).data,
            "access": {
                "dashboard_allowed": provider.approval_allows_dashboard,
                "serious_jobs_allowed": provider.can_receive_serious_jobs,
                "pending_screen_required": not provider.approval_allows_dashboard,
                "status": provider.verification_status,
                "kyc_status": provider.kyc_status,
                "subscription_status": provider.subscription_status,
            },
            "cards": {
                "active_services": provider.services.filter(is_active=True).count(),
                "projects": provider.portfolio_items.count(),
                "approved_projects": provider.approved_project_count,
                "project_media": provider.portfolio_items.aggregate(total=Count("media_items"))["total"] or 0,
                "project_views": provider.project_views_count,
                "video_views": provider.project_video_views_count,
                "project_leads": provider.project_leads_count,
                "reviews": provider.total_reviews,
                "assigned_jobs": quotes.filter(status="assigned").count(),
                "accepted_jobs": quotes.filter(status="accepted").count(),
                "in_progress_jobs": quotes.filter(status="in_progress").count(),
                "completed_jobs": quotes.filter(status__in=["completed", "closed"]).count(),
                "unread_notifications": notifications.filter(is_read=False).count(),
                "profile_completion": provider.profile_completion_percent,
            },
            "profile_completion": {
                "percent": provider.profile_completion_percent,
                "steps": provider.profile_completion_items,
                "missing_steps": provider.profile_missing_steps,
            },
            "entitlements": ProjectEntitlementService(provider).payload(),
            "recent_jobs": ProviderQuoteRequestSerializer(
                active_jobs,
                many=True,
                context={"request": request},
            ).data,
            "recent_notifications": [
                provider_notification_payload(note)
                for note in notifications[:3]
            ],
        })


class ProviderRequestsAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        provider, error = provider_from_request(request, require_dashboard=True)
        if error:
            return error
        queryset = provider.quote_requests.select_related("category", "product", "customer").order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return Response({"requests": ProviderQuoteRequestSerializer(queryset[:100], many=True, context={"request": request}).data})


class ProviderRequestDetailAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get_quote(self, request, quote_id):
        provider, error = provider_from_request(request, require_dashboard=True)
        if error:
            return None, error
        quote = provider.quote_requests.select_related("category", "product", "customer").filter(pk=quote_id).first()
        if not quote:
            return None, Response({"detail": "Service request not found."}, status=status.HTTP_404_NOT_FOUND)
        return quote, None

    def get(self, request, quote_id):
        quote, error = self.get_quote(request, quote_id)
        if error:
            return error
        return Response({"request": ProviderQuoteRequestSerializer(quote, context={"request": request}).data})


class ProviderRequestActionAPIView(ProviderRequestDetailAPIView):
    action = ""

    def post(self, request, quote_id):
        quote, error = self.get_quote(request, quote_id)
        if error:
            return error
        if self.action == "accept":
            if quote.status != "assigned":
                return Response({"detail": "Only newly assigned jobs can be accepted."}, status=status.HTTP_400_BAD_REQUEST)
            quote.status = "accepted"
            quote.accepted_at = timezone.now()
        elif self.action == "reject":
            if quote.status != "assigned":
                return Response({"detail": "Only newly assigned jobs can be rejected."}, status=status.HTTP_400_BAD_REQUEST)
            quote.status = "rejected_by_provider"
        else:
            next_status = request.data.get("status")
            allowed_transitions = {
                "accepted": {"accepted", "on_the_way"},
                "on_the_way": {"on_the_way", "in_progress"},
                "in_progress": {"in_progress", "completed"},
            }
            if next_status not in allowed_transitions.get(quote.status, {quote.status}):
                return Response({"detail": "That job status change is not allowed."}, status=status.HTTP_400_BAD_REQUEST)
            quote.status = next_status
            if next_status == "completed":
                quote.completed_at = timezone.now()
        quote.provider_note = request.data.get("provider_note", quote.provider_note)
        if request.FILES.get("completion_photo"):
            quote.completion_photo = request.FILES["completion_photo"]
        quote.save()
        if quote.customer:
            Notification.send(
                quote.customer,
                "system",
                "Service request updated",
                f"Your service request is now {quote.get_status_display().lower()}.",
                metadata={"service_quote_request_id": quote.id, "status": quote.status},
            )
        return Response({"request": ProviderQuoteRequestSerializer(quote, context={"request": request}).data})


class ProviderRequestAcceptAPIView(ProviderRequestActionAPIView):
    action = "accept"


class ProviderRequestRejectAPIView(ProviderRequestActionAPIView):
    action = "reject"


class ProviderRequestStatusAPIView(ProviderRequestActionAPIView):
    action = "status"


class ProviderSubscriptionPlansAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        user = provider_user_from_request(request)
        current = get_effective_subscription(user, role_context="provider").as_dict() if user else None
        plans = []
        for plan in official_plans():
            plans.append({
                "id": plan.id,
                "tier": plan.tier_key,
                "name": plan.tier_key,
                "display_name": plan.display_name,
                "price_monthly": str(plan.price_monthly),
                "price_yearly": str(plan.price_yearly),
                "currency": "NGN",
                "description": plan.description,
                "benefits": plan.feature_bullets or [],
                "provider_entitlements": get_plan_entitlements(plan, "provider"),
                "is_current": bool(current and current["plan_id"] == plan.id),
                "is_free": plan.tier_key == "free",
            })
        return Response({"plans": plans, "current_subscription": current})


class ProviderSubscriptionSelectAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error

        plan_reference = request.data.get("plan_id") or request.data.get("plan_name") or request.data.get("tier")
        official_plan_ids = [plan.id for plan in official_plans()]
        plans = SubscriptionPlan.objects.filter(is_active=True, id__in=official_plan_ids)
        if str(plan_reference).isdigit():
            plan = plans.filter(pk=plan_reference).first()
        else:
            reference = str(plan_reference or "").strip()
            plan = plans.filter(name__iexact=reference).first() or plans.filter(display_name__iexact=reference).first()
        if not plan:
            return Response(
                {"detail": "Select a valid active provider subscription plan."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        billing_cycle = str(request.data.get("billing_cycle") or VendorSubscription.BILLING_MONTHLY).strip().lower()
        if billing_cycle not in dict(VendorSubscription.BILLING_CYCLE_CHOICES):
            return Response({"detail": "Choose monthly or yearly billing."}, status=status.HTTP_400_BAD_REQUEST)

        selected_price = plan.price_yearly if billing_cycle == VendorSubscription.BILLING_YEARLY else plan.price_monthly
        if selected_price <= 0:
            activate_free_subscription(provider.user, source_platform="provider_mobile")
            provider.refresh_from_db()
            return Response({
                "success": True,
                "message": "Free account subscription selected.",
                "provider": ServiceProviderDetailSerializer(provider, context={"request": request}).data,
                "subscription": get_effective_subscription(provider.user, role_context="provider").as_dict(),
            })

        gateway = str(
            request.data.get("payment_gateway")
            or request.data.get("gateway")
            or PaymentMethod.PAYSTACK
        ).strip().lower()
        if gateway not in PaymentMethod.values:
            return Response({"detail": "Choose a supported Arolana payment gateway."}, status=status.HTTP_400_BAD_REQUEST)
        available, reason = gateway_is_available(gateway)
        if not available:
            return Response({"detail": reason or "This payment gateway is unavailable."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payment = create_subscription_payment(
                provider.user,
                plan,
                billing_cycle,
                gateway,
                source_platform="provider_mobile",
                role_context="provider",
            )
            if gateway == PaymentMethod.MANUAL_CRYPTO:
                checkout_url = ""
            else:
                from staff_mobile.views import _hosted_subscription_checkout_url

                checkout_url = _hosted_subscription_checkout_url(request, payment)
        except (DjangoValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response(
                {"detail": "Unable to start secure subscription checkout. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({
            "success": True,
            "payment_required": True,
            "manual_payment": gateway == PaymentMethod.MANUAL_CRYPTO,
            "plan_id": plan.id,
            "tier": plan.tier_key,
            "billing_cycle": billing_cycle,
            "amount": str(selected_price),
            "currency": "NGN",
            "reference": payment.reference,
            "payment_reference": payment.reference,
            "checkout_url": checkout_url,
            "authorization_url": checkout_url,
            "message": (
                "Manual payment created. Arolana will activate the plan after verification."
                if gateway == PaymentMethod.MANUAL_CRYPTO
                else "Secure subscription checkout initialized."
            ),
        })


class ProviderNotificationsAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        notes = provider_workspace_notifications(provider)
        return Response({
            "unread_count": notes.filter(is_read=False).count(),
            "notifications": [provider_notification_payload(note) for note in notes[:100]],
        })


class ProviderNotificationReadAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, notification_id):
        provider, error = provider_from_request(request)
        if error:
            return error
        note = Notification.objects.filter(id=notification_id, user=provider.user).first()
        if not note:
            return Response({"detail": "Notification not found."}, status=status.HTTP_404_NOT_FOUND)
        note.mark_as_read()
        return Response({"success": True})


class ProviderSettingsAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        return Response({
            "provider": ServiceProviderDetailSerializer(provider, context={"request": request}).data,
            "preferred_language": provider.preferred_language,
            "notification_preferences": provider.notification_preferences,
            "availability_status": provider.availability_status,
            "availability_note": provider.availability_note,
            "business_hours": provider.business_hours,
            "business_hours_data": provider.business_hours_data,
            "support_phone": provider.support_phone,
            "support_email": provider.support_email,
            "support_whatsapp": provider.support_whatsapp,
            "sensitive_update_locked": provider.sensitive_update_locked,
            "sensitive_update_available_at": provider.sensitive_update_available_at,
            "pending_change_requests": ProviderChangeRequestSerializer(
                provider.profile_change_requests.filter(status=ProviderProfileChangeRequest.STATUS_PENDING),
                many=True,
                context={"request": request},
            ).data,
            "kyc_documents": ProviderKYCDocumentSerializer(
                provider.kyc_documents.filter(is_active=True),
                many=True,
                context={"request": request},
            ).data,
        })

    def patch(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        allowed = {
            "preferred_language", "notification_preferences", "availability_status",
            "availability_note", "business_hours", "business_hours_data",
            "support_phone", "support_email", "support_whatsapp", "bank_details",
        }
        for key in allowed:
            if key in request.data:
                setattr(provider, key, request.data[key])
        provider.save(update_fields=[*allowed.intersection(request.data.keys()), "updated_at"])
        return self.get(request)


class ProviderChangePasswordAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        current_password = str(request.data.get("current_password", ""))
        new_password = str(request.data.get("new_password", ""))
        if not provider.user.check_password(current_password):
            return Response(
                {"detail": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_password(new_password, provider.user)
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        provider.user.set_password(new_password)
        provider.user.save(update_fields=["password"])
        from staff_mobile.models import StaffMobileToken

        StaffMobileToken.objects.filter(user=provider.user).update(is_active=False)
        Notification.send(
            provider.user,
            "security",
            "Password changed",
            "Your Arolana password was changed. Sign in again on your devices.",
            metadata={"service_provider_id": provider.id, "workspace": "provider"},
            priority=3,
        )
        return Response({"message": "Password changed. Please sign in again.", "sign_out_required": True})


class ProviderDeactivateRequestAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        reason = str(request.data.get("reason", "")).strip()
        staff = get_user_model().objects.filter(is_active=True, is_staff=True)
        Notification.bulk_create(
            staff,
            "system",
            "Provider deactivation request",
            f"{provider.business_name} requested account deactivation. {reason}".strip(),
            link="/admin/installers/serviceproviderprofile/",
            metadata={"service_provider_id": provider.id, "workspace": "provider"},
        )
        Notification.send(
            provider.user,
            "system",
            "Deactivation request received",
            "Arolana support will review your provider account deactivation request.",
            metadata={"service_provider_id": provider.id, "workspace": "provider"},
        )
        return Response({"message": "Your deactivation request was sent to Arolana support."})
