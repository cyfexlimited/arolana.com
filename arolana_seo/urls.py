from django.urls import path
from . import views

app_name = "arolana_seo"

urlpatterns = [
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("merchant-feed.xml", views.google_merchant_feed, name="merchant_feed"),
]
