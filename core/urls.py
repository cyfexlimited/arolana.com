from django.urls import path
from . import views
from . import youtube_views

app_name = "core"

urlpatterns = [
    path("integrations/youtube/connect/", youtube_views.youtube_connect, name="youtube_connect"),
    path("integrations/youtube/oauth/callback/", youtube_views.youtube_oauth_callback, name="youtube_oauth_callback"),
    path("integrations/youtube/status/", youtube_views.youtube_status, name="youtube_status"),
    path("quote/vendor/", views.request_vendor_quote, name="request_vendor_quote"),
    path("quotes/<int:quote_id>/", views.customer_quote_request_detail, name="customer_quote_request_detail"),
    path("debug/", views.debug_home, name="debug_home"),
]
