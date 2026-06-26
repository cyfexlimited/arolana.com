from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from mobile_customers.views import _auth_mobile_customer_from_request_data
from notifications.models import Notification
from products.models import Product

from .models import ServiceCategory, ServiceProviderProfile
from .serializers import (
    ProviderRegistrationSerializer,
    ServiceCategorySerializer,
    ServiceProviderDetailSerializer,
    ServiceProviderListSerializer,
    ServiceQuoteRequestSerializer,
    ServiceReviewCreateSerializer,
)
from .services import (
    filter_public_providers,
    notify_staff_provider_registration,
    notify_staff_service_quote,
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


class ProviderListAPIView(generics.ListAPIView):
    serializer_class = ServiceProviderListSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return filter_public_providers(self.request.query_params)


class CategoryListAPIView(generics.ListAPIView):
    serializer_class = ServiceCategorySerializer
    permission_classes = [permissions.AllowAny]
    queryset = ServiceCategory.objects.filter(is_active=True).order_by("name")
    pagination_class = None


class ProviderDetailAPIView(generics.RetrieveAPIView):
    serializer_class = ServiceProviderDetailSerializer
    permission_classes = [permissions.AllowAny]
    queryset = (
        ServiceProviderProfile.objects.public()
        .select_related("user")
        .prefetch_related("services__category", "portfolio_items", "reviews__customer")
    )


class ProviderRegistrationAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        user = request_user_from_mobile_payload(request)
        if not user:
            return Response({"detail": "Login is required to register as a service provider."}, status=status.HTTP_401_UNAUTHORIZED)
        instance = ServiceProviderProfile.objects.filter(user=user).first()
        serializer = ProviderRegistrationSerializer(instance, data=request.data, partial=bool(instance))
        serializer.is_valid(raise_exception=True)
        provider = serializer.save(
            user=user,
            verification_status=ServiceProviderProfile.STATUS_PENDING,
            is_verified=False,
        )
        notify_staff_provider_registration(provider)
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
