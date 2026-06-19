from django.urls import path
from . import views

app_name = "arolana_seo"

urlpatterns = [
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", views.main_sitemap_xml, name="main_sitemap_xml"),
    path("products/sitemap.xml", views.product_sitemap_xml, name="product_sitemap_xml"),
    path("merchant-feed.xml", views.google_merchant_feed, name="merchant_feed"),
]