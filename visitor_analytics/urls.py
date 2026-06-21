from django.urls import path

from .views import debug_cloudflare_headers, track_click_event

app_name = "visitor_analytics"

urlpatterns = [
    path("track-click/", track_click_event, name="track_click_event"),
    path("debug-cloudflare/", debug_cloudflare_headers, name="debug_cloudflare_headers"),
]