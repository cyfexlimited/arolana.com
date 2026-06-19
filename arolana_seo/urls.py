from django.urls import path
from . import views

app_name = "arolana_seo"

urlpatterns = [
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", views.main_sitemap_xml, name="main_sitemap_xml"),
    path("static/sitemap.xml", views.static_sitemap_xml, name="static_sitemap_xml"),
    path("products/sitemap.xml", views.product_sitemap_xml, name="product_sitemap_xml"),
    path("categories/sitemap.xml", views.category_sitemap_xml, name="category_sitemap_xml"),
    path("vendors/sitemap.xml", views.vendor_sitemap_xml, name="vendor_sitemap_xml"),
    path("blog/sitemap.xml", views.blog_sitemap_xml, name="blog_sitemap_xml"),
    path("blog-categories/sitemap.xml", views.blog_category_sitemap_xml, name="blog_category_sitemap_xml"),
    path("landing/sitemap.xml", views.landing_sitemap_xml, name="landing_sitemap_xml"),
    path("manufacturers/sitemap.xml", views.manufacturer_sitemap_xml, name="manufacturer_sitemap_xml"),
    path("pages/sitemap.xml", views.page_sitemap_xml, name="page_sitemap_xml"),
    path("merchant-feed.xml", views.google_merchant_feed, name="merchant_feed"),
]