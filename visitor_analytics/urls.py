from django.urls import path

from .views import track_click_event

app_name = "visitor_analytics"

urlpatterns = [
    path("track-click/", track_click_event, name="track_click_event"),
]