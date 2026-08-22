from django.urls import path

from . import api_views

app_name = "social_publishing"

urlpatterns = [
    path("instagram/videos/publish/", api_views.publish_instagram_video, name="instagram_video_publish"),
    path("accounts/status/", api_views.social_accounts_status, name="accounts_status"),
    path("accounts/<str:platform>/connect/", api_views.social_account_connect_launch, name="account_connect_launch"),
    path("accounts/<str:platform>/", api_views.social_account_disconnect, name="account_disconnect"),
]
