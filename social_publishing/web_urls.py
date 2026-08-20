from django.urls import path

from . import web_views

app_name = "social_publishing_web"

urlpatterns = [
    path("accounts/", web_views.accounts_page, name="accounts"),
    path("connect/<str:platform>/", web_views.connect_account, name="connect"),
    path("callback/<str:platform>/", web_views.oauth_callback, name="oauth_callback"),
    path("disconnect/<str:platform>/", web_views.disconnect_account, name="disconnect"),
    path("meta/deauthorize/", web_views.meta_instagram_deauthorize, name="meta_deauthorize"),
    path("meta/data-deletion/", web_views.meta_instagram_data_deletion, name="meta_data_deletion"),
    path("meta/data-deletion/status/", web_views.meta_instagram_data_deletion_status, name="meta_data_deletion_status"),
]
