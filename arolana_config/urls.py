from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.views.static import serve
from django.shortcuts import render
from django.http import JsonResponse

from pages.views import (
    page_by_slug,
    page_detail,
    help_center,
    faq_page,
    article_detail,
    careers_page,
    contact_page,
)
from products import views as products_views
from orders import views as orders_views
import currency.views as currency_views
import core.views as core_views
from core import admin_views as core_admin_views
from accounts import views as accounts_views
from landing_pages import views as landing_page_views

from products.models import Product, Category
from vendors.models import VendorProfile


def health_check(request):
    return JsonResponse({"status": "ok"})


def sitemap_page(request):
    categories = Category.objects.filter(is_active=True, parent=None)[:20]
    products = Product.objects.filter(
        is_active=True,
        approval_status="approved"
    )[:50]
    vendors = VendorProfile.objects.filter(
        is_verified=True,
        is_active=True
    )[:20]

    return render(
        request,
        "pages/sitemap.html",
        {
            "categories": categories,
            "products": products,
            "vendors": vendors,
        },
    )

def home_view(request):
    """Custom home view with video section and proper context"""
    from core.local_cache import local_get_or_set
    from homepage.models import HomepageVideoSection

    video_section = local_get_or_set(
        "homepage:video_section",
        lambda: HomepageVideoSection.objects.filter(is_active=True)
        .order_by("display_order")
        .first(),
        300,
    )

    return render(
        request,
        "base/home.html",
        {
            "video_section": video_section,
        },
    )


def returns_redirect(request, path=None):
    from django.shortcuts import redirect

    return redirect("returns")


def custom_404(request, exception):
    return render(request, "404.html", status=404)


# CKEditor 5 URLs configuration
try:
    from django_ckeditor_5.views import upload_file, browse_files

    CKEDITOR_URLS = [
        re_path(r"^ckeditor5/upload/", upload_file, name="ck_editor_5_upload_file"),
        re_path(r"^ckeditor5/browse/", browse_files, name="ck_editor_5_browse_files"),
    ]
    print("✅ Using django_ckeditor_5 built-in views")

except ImportError:
    from ckeditor_views.views import upload_file, browse_files

    CKEDITOR_URLS = [
        re_path(r"^ckeditor5/upload/", upload_file, name="ck_editor_5_upload_file"),
        re_path(r"^ckeditor5/browse/", browse_files, name="ck_editor_5_browse_files"),
    ]
    print("⚠️ Using custom CKEditor views")


urlpatterns = [
    # Admin & Core
    path("admin/live-stats/", core_views.live_stats, name="live_stats"),
    path(
        "admin/logo-check/",
        TemplateView.as_view(template_name="admin/logo_check.html"),
        name="logo_check",
    ),
    path("admin/upload-logo/", core_admin_views.upload_logo, name="upload_logo"),
    path(
        "admin/avatar-upload/<int:user_id>/",
        core_admin_views.upload_user_avatar,
        name="avatar_upload",
    ),
    path(
        "admin/avatar-delete/<int:user_id>/",
        core_admin_views.delete_user_avatar,
        name="avatar_delete",
    ),
    path("admin/", admin.site.urls),
    path("visitor-analytics/", include("visitor_analytics.urls")),
    # Products API
    path("api/", include("products.urls", namespace="products_api")),
    path("api/smartchat/", include(("smartchat.api_urls", "smartchat_api"), namespace="smartchat_api")),

    # Health check for Railway
    path("health/", health_check, name="health"),

    path(
        "manifest.webmanifest",
        TemplateView.as_view(
            template_name="pwa/manifest.webmanifest",
            content_type="application/manifest+json",
        ),
        name="web_manifest",
    ),
    path(
        "service-worker.js",
        TemplateView.as_view(
            template_name="pwa/service-worker.js",
            content_type="application/javascript",
        ),
        name="service_worker",
    ),


    path("", include("arolana_seo.urls")),

    # Homepage
    path("", home_view, name="home"),
    
    path("sitemap/", sitemap_page, name="sitemap"),
    # Authentication
    path("accounts/", include("accounts.urls")),
    path("accounts/", include("allauth.urls")),

    # App URLs
    path("newsletter/", include("newsletter.urls")),
    path("vendors/", include("vendors.urls")),
    path("products/", include("products.urls")),
    path("orders/", include("orders.urls")),
    path("deliveries/", include("deliveries.urls")),
    path("order-robot/", include("order_robot.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("hero-banners/", include("hero_banners.urls")),
    path("ads/", include("ads.urls")),
    path("pages/", include("pages.urls")),
    path("manufacturers/", include("manufacturers.urls")),
    path("kyc/", include("kyc.urls")),
    path("chat/", include("chat.urls")),
    path("blog/", include("blog.urls")),
    path("currency/", include("currency.urls")),
    path("api/currency/rates/", currency_views.api_currency_rates, name="api_currency_rates"),
    path("api/currency/convert/", currency_views.api_convert_amount, name="api_currency_convert"),
    path("subscriptions/", include("subscriptions.urls")),
    path("videos/", include("videos.urls")),
    path("reports/", include("reports.urls")),
    path("notifications/", include("notifications.urls")),
    path("payments/", include("arolana_payments.urls")),
    path("landing/", include("landing_pages.urls")),
    path(
        "landing-preview/<slug:slug>/",
        landing_page_views.landing_page_preview,
        name="landing_page_preview",
    ),

    # Smart AI Chat
    path("smartchat/", include(("smartchat.urls", "smartchat"), namespace="smartchat")),
    path("support/ai/", include("smartchat.compat_urls")),

    # Social Apps Status
    path(
        "social-apps-status/",
        accounts_views.social_apps_status,
        name="social_apps_status",
    ),

    # CKEditor 5
    *CKEDITOR_URLS,

    # Support Pages
    path(
        "shipping/",
        TemplateView.as_view(template_name="support/shipping.html"),
        name="shipping",
    ),
    path(
        "youtube-embed-test/",
        TemplateView.as_view(template_name="youtube_embed_test.html"),
        name="youtube_embed_test",
    ),
    path("support/", contact_page, name="support"),
    path("contact/", contact_page, name="contact"),
    path("about/", page_by_slug, {"slug": "about"}, name="about"),
    path("privacy/", page_by_slug, {"slug": "privacy"}, name="privacy"),
    path("terms/", page_by_slug, {"slug": "terms"}, name="terms"),
    path("returns/", page_by_slug, {"slug": "returns"}, name="returns"),
    path("faq/", faq_page, name="faq"),
    re_path(r"^returns/.*$", returns_redirect, name="returns_catchall"),

    # Order tracking page
    path("orders/track/", orders_views.track_order, name="track_order"),

    # Mobile Orders API - keep these BEFORE search_ai root include
    path(
        "api/mobile/orders/create/",
        orders_views.mobile_authenticated_order_create_api,
        name="mobile_authenticated_order_create_api",
    ),
    path(
        "api/mobile/orders/history/",
        orders_views.mobile_authenticated_orders_history_api,
        name="mobile_authenticated_orders_history_api",
    ),
    path(
        "api/mobile/orders/receipt/",
        orders_views.mobile_authenticated_order_receipt_pdf_api,
        name="mobile_authenticated_order_receipt_pdf_api",
    ),
    path(
        "api/mobile/orders/cancel/",
        orders_views.mobile_authenticated_order_cancel_api,
        name="mobile_authenticated_order_cancel_api",
    ),

    # Mobile Notifications API
    path(
        "api/mobile/notifications/",
        orders_views.mobile_notifications_api,
        name="mobile_notifications_api",
    ),
    path(
        "api/mobile/push-token/register/",
        orders_views.mobile_register_push_token_api,
        name="mobile_register_push_token_api",
    ),
    path(
        "api/mobile/notifications/mark-read/",
        orders_views.mobile_notifications_mark_read_api,
        name="mobile_notifications_mark_read_api",
    ),
    path(
        "api/mobile/notifications/delete/",
        orders_views.mobile_notifications_delete_api,
        name="mobile_notifications_delete_api",
    ),

    # Mobile Customers API
    path("", include("mobile_customers.urls")),
    path("", include("arolana_ops.urls")),
    path("", include("staff_mobile.urls")),

    # Search routes - keep AFTER mobile API routes
    path("search/", include("search_ai.urls")),
    path("", include("search_ai.urls", namespace="search_ai_legacy")),

    # Help & Debug
    path(
        "color-test/",
        TemplateView.as_view(template_name="products/color_test.html"),
        name="color_test",
    ),
    path(
        "debug-colors/<int:product_id>/",
        products_views.debug_colors,
        name="debug_colors",
    ),
    path("debug/", include("core.urls")),
    path("careers/", careers_page, name="careers"),
    path("help/", help_center, name="help_center"),
    path("faq/", faq_page, name="faq_page"),
    path("article/<slug:slug>/", article_detail, name="article_detail"),
    path("currency/diagnose/", currency_views.diagnose_currency, name="diagnose_currency"),

    # Test Pages
    path(
        "ads-test/",
        TemplateView.as_view(template_name="ads/test.html"),
        name="ads_test",
    ),
    path(
        "image-test/",
        TemplateView.as_view(template_name="ads/direct_test.html"),
        name="image_test",
    ),
    path(
        "social-test/",
        TemplateView.as_view(template_name="socialaccount/test.html"),
        name="social_test",
    ),

    # Landing clean detail must stay near bottom because it catches slugs
    path("<slug:slug>/", landing_page_views.landing_page_detail, name="landing_page_clean_detail"),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

elif getattr(settings, "MEDIA_PROXY_ENABLED", False):
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", core_views.proxy_media, name="proxy_media"),
    ]

elif getattr(settings, "SERVE_MEDIA", False):
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]


# Custom 404 handler
handler404 = "arolana_config.urls.custom_404"
