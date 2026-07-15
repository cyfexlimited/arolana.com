from django.urls import path

from . import api_views
from .project_api_urls import provider_project_urlpatterns

app_name = "installers_api"

urlpatterns = [
    path("", api_views.ProviderListAPIView.as_view(), name="provider_list"),
    path("categories/", api_views.CategoryListAPIView.as_view(), name="category_list"),
    path("register/", api_views.ProviderRegistrationAPIView.as_view(), name="register"),
    path("quote-request/", api_views.QuoteRequestAPIView.as_view(), name="quote_request"),
    path("reviews/", api_views.ReviewCreateAPIView.as_view(), name="review_create"),
    path("product/<int:product_id>/suggested/", api_views.SuggestedProvidersAPIView.as_view(), name="product_suggested"),
    path("<int:provider_id>/services/<int:service_id>/", api_views.PublicProviderServiceDetailAPIView.as_view(), name="public_service_detail"),
    path("<int:pk>/", api_views.ProviderDetailAPIView.as_view(), name="provider_detail"),
]

provider_urlpatterns = [
    path("register/", api_views.ProviderRegistrationAPIView.as_view(), name="provider_register"),
    path("me/", api_views.ProviderMeAPIView.as_view(), name="provider_me"),
    path("profile/", api_views.ProviderProfileAPIView.as_view(), name="provider_profile"),
    path("change-request/", api_views.ProviderChangeRequestAPIView.as_view(), name="provider_change_request"),
    path("change-requests/", api_views.ProviderChangeRequestAPIView.as_view(), name="provider_change_requests"),
    path("upload-logo/", api_views.ProviderLogoUploadAPIView.as_view(), name="provider_upload_logo"),
    path("upload-banner/", api_views.ProviderBannerUploadAPIView.as_view(), name="provider_upload_banner"),
    path("upload-profile-image/", api_views.ProviderProfileImageUploadAPIView.as_view(), name="provider_upload_profile_image"),
    path("portfolio/", api_views.ProviderPortfolioAPIView.as_view(), name="provider_portfolio"),
    path("services/", api_views.ProviderServicesAPIView.as_view(), name="provider_services"),
    path("services/<int:service_id>/", api_views.ProviderServiceDetailAPIView.as_view(), name="provider_service_detail"),
    path("kyc/", api_views.ProviderKYCAPIView.as_view(), name="provider_kyc"),
    path("dashboard/", api_views.ProviderDashboardAPIView.as_view(), name="provider_dashboard"),
    path("requests/", api_views.ProviderRequestsAPIView.as_view(), name="provider_requests"),
    path("requests/<int:quote_id>/", api_views.ProviderRequestDetailAPIView.as_view(), name="provider_request_detail"),
    path("requests/<int:quote_id>/accept/", api_views.ProviderRequestAcceptAPIView.as_view(), name="provider_request_accept"),
    path("requests/<int:quote_id>/reject/", api_views.ProviderRequestRejectAPIView.as_view(), name="provider_request_reject"),
    path("requests/<int:quote_id>/status/", api_views.ProviderRequestStatusAPIView.as_view(), name="provider_request_status"),
    path("subscription-plans/", api_views.ProviderSubscriptionPlansAPIView.as_view(), name="provider_subscription_plans"),
    path("subscription/select/", api_views.ProviderSubscriptionSelectAPIView.as_view(), name="provider_subscription_select"),
    path("notifications/", api_views.ProviderNotificationsAPIView.as_view(), name="provider_notifications"),
    path("notifications/<int:notification_id>/read/", api_views.ProviderNotificationReadAPIView.as_view(), name="provider_notification_read"),
    path("settings/", api_views.ProviderSettingsAPIView.as_view(), name="provider_settings"),
    path("availability/", api_views.ProviderSettingsAPIView.as_view(), name="provider_availability"),
    path("notification-preferences/", api_views.ProviderSettingsAPIView.as_view(), name="provider_notification_preferences"),
    path("change-password/", api_views.ProviderChangePasswordAPIView.as_view(), name="provider_change_password"),
    path("deactivate-request/", api_views.ProviderDeactivateRequestAPIView.as_view(), name="provider_deactivate_request"),
] + provider_project_urlpatterns
