from django.urls import path

from . import api_views

app_name = "installers_api"

urlpatterns = [
    path("", api_views.ProviderListAPIView.as_view(), name="provider_list"),
    path("categories/", api_views.CategoryListAPIView.as_view(), name="category_list"),
    path("register/", api_views.ProviderRegistrationAPIView.as_view(), name="register"),
    path("quote-request/", api_views.QuoteRequestAPIView.as_view(), name="quote_request"),
    path("reviews/", api_views.ReviewCreateAPIView.as_view(), name="review_create"),
    path("product/<int:product_id>/suggested/", api_views.SuggestedProvidersAPIView.as_view(), name="product_suggested"),
    path("<int:pk>/", api_views.ProviderDetailAPIView.as_view(), name="provider_detail"),
]

