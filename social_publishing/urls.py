from django.urls import path

from . import api_views

app_name = "social_publishing"

urlpatterns = [
    path("accounts/status/", api_views.social_accounts_status, name="accounts_status"),
    path("accounts/<str:platform>/connect/", api_views.social_account_connect_launch, name="account_connect_launch"),
    path("accounts/<str:platform>/", api_views.social_account_disconnect, name="account_disconnect"),
]
