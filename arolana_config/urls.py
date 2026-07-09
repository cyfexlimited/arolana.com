import logging
import mimetypes
import posixpath

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import include, path, re_path
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_safe
from django.views.generic import TemplateView

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
from installers.api_urls import provider_urlpatterns

from products.models import Product, Category
from vendors.models import VendorProfile


logger = logging.getLogger(__name__)


# ============================================================================
# MEDIA SECURITY POLICY
# ============================================================================
#
# IMPORTANT:
#
# The /media/ endpoint must never behave as:
#
#     "If the object exists, make it public."
#
# Instead, Arolana uses:
#
#     1. Deny sensitive/private namespaces first.
#     2. Allow explicitly approved public namespaces.
#     3. Validate optimized derivatives against their original source namespace.
#     4. Permit staff-only viewing of sensitive files for moderation/admin review.
#     5. Never publicly cache private media.
#
# Do NOT add broad prefixes such as:
#
#     "installers"
#     "orders"
#     "documents"
#
# because those roots may contain private files.
# ============================================================================


PUBLIC_MEDIA_PREFIXES = (
    # Core
    "settings",
    "categories",
    "hero_banners",
    "homepage",
    "brands",
    "avatars",

    # Products and marketplace
    "products",
    "accessories",
    "vendors",
    "manufacturers",

    # Advertising
    "ads",
    "advertisements",
    "promo",

    # Public content
    "blog",
    "landing_pages",
    "uploads",
    "newsletter",
    "videos",
    "support",

    # Reviews pending moderation
    "reviews/videos",
    "reviews/thumbs",

    # Public service marketplace media
    "installers/providers",
    "installers/categories",
    "installers/portfolio",
    "installers/projects/gallery",
    "installers/projects/thumbnails",
    "installers/projects/videos",
    "installers/homepage",

    # Wallet payment display assets
    "crypto_wallet_qr",
)


PRIVATE_MEDIA_PREFIXES = (
    # =========================================================
    # Provider identity / verification
    # =========================================================
    "installers/kyc",
    "installers/verification",
    "installers/profile-change-requests",
    "installers/completions",

    "installers/providers/kyc",
    "installers/providers/private",
    "installers/providers/documents",

    # =========================================================
    # Central KYC
    # =========================================================
    "kyc",

    # =========================================================
    # Delivery rider identity and operational evidence
    # =========================================================
    "delivery/riders/id_documents",
    "delivery/riders/licenses",
    "delivery/riders/vehicle_documents",
    "delivery/riders/photos",
    "delivery/riders/banners",
    "delivery/proofs",

    # =========================================================
    # Chat attachments
    # =========================================================
    "chat/attachments",
    "chat/vendor_attachments",
    "smartchat/images",

    # =========================================================
    # Payment evidence
    # =========================================================
    "payment_proofs",

    # =========================================================
    # Job applications
    # =========================================================
    "job_applications/resumes",

    # =========================================================
    # Customer account media
    # =========================================================
    "mobile_customers/profile_pictures",

    # =========================================================
    # Reviews pending moderation
    #
    # Safer to protect by default until a dedicated approved-
    # review media delivery strategy exists.
    # =========================================================
    "reviews/videos",

    # =========================================================
    # Defensive generic sensitive namespaces
    # =========================================================
    "private",
    "protected",
    "verification",
    "identity",
    "documents/private",

    # Vendor sensitive media
    "vendors/kyc",
    "vendors/private",
    "vendors/documents",

    # Manufacturer sensitive media
    "manufacturers/kyc",
    "manufacturers/private",
    "manufacturers/documents",

    # Account sensitive media
    "accounts/kyc",
    "accounts/private",
    "accounts/documents",
)


def _clean_media_path(path):
    """
    Return a normalized storage-relative path or an empty string when unsafe.

    Security rules:
    - reject missing paths;
    - reject NUL bytes;
    - reject traversal using '..';
    - normalize Windows-style backslashes to POSIX separators;
    - remove a leading /media/ prefix when one is accidentally supplied;
    - preserve filename case because object-storage keys are case-sensitive.
    """
    raw_path = str(path or "").strip()

    if not raw_path:
        return ""

    if "\x00" in raw_path:
        return ""

    # Treat backslashes as separators before checking traversal.
    raw_path = raw_path.replace("\\", "/")

    raw_segments = raw_path.split("/")

    if any(segment == ".." for segment in raw_segments):
        return ""

    normalized_path = posixpath.normpath(raw_path).lstrip("/")

    if (
        not normalized_path
        or normalized_path == "."
        or normalized_path.startswith("../")
        or "/../" in normalized_path
        or normalized_path.endswith("/..")
    ):
        return ""

    if normalized_path.startswith("media/"):
        normalized_path = normalized_path[len("media/"):]

    return normalized_path


def _path_matches_prefix(path, prefixes):
    """
    Return True when path exactly matches or is contained by a prefix.

    Prefix comparisons are case-insensitive, while the original path is
    preserved for object-storage access.
    """
    cleaned_path = _clean_media_path(path)

    if not cleaned_path:
        return False

    comparison_path = cleaned_path.lower()

    for prefix in prefixes:
        clean_prefix = _clean_media_path(prefix)

        if not clean_prefix:
            continue

        comparison_prefix = clean_prefix.lower()

        if (
            comparison_path == comparison_prefix
            or comparison_path.startswith(
                f"{comparison_prefix}/"
            )
        ):
            return True

    return False


def _optimized_source_path(path):
    """
    Recover the source namespace embedded in an optimized image path.

    Example:

        optimized/
            provider_profile/
            installers/providers/2026/06/photo.webp

    becomes:

        installers/providers/2026/06/photo.webp

    Another example:

        optimized/
            seo/
            installers/kyc/2026/06/document.webp

    becomes:

        installers/kyc/2026/06/document.webp

    This prevents somebody from bypassing private-media restrictions by
    requesting an optimized derivative of a sensitive source file.
    """
    cleaned_path = _clean_media_path(path)

    if not cleaned_path:
        return ""

    if not cleaned_path.lower().startswith("optimized/"):
        return ""

    parts = cleaned_path.split("/", 2)

    if len(parts) != 3:
        return ""

    source_path = _clean_media_path(parts[2])

    return source_path


def _is_private_media_path(path):
    """
    Return True when a media path belongs to a protected namespace.

    Both original paths and optimized derivative paths are checked.
    """
    cleaned_path = _clean_media_path(path)

    if not cleaned_path:
        return True

    # Direct private path.
    if _path_matches_prefix(
        cleaned_path,
        PRIVATE_MEDIA_PREFIXES,
    ):
        return True

    # Optimized derivative whose embedded original belongs to a private path.
    source_path = _optimized_source_path(cleaned_path)

    if (
        source_path
        and _path_matches_prefix(
            source_path,
            PRIVATE_MEDIA_PREFIXES,
        )
    ):
        return True

    return False


def _is_public_media_path(path):
    """
    Return True only for explicitly approved public media.

    Optimized media is not automatically public merely because its path starts
    with "optimized/". The embedded source namespace must itself be public.
    """
    cleaned_path = _clean_media_path(path)

    if not cleaned_path:
        return False

    if _is_private_media_path(cleaned_path):
        return False

    # ------------------------------------------------------------------------
    # Optimized derivatives
    # ------------------------------------------------------------------------
    if cleaned_path.lower().startswith("optimized/"):
        source_path = _optimized_source_path(cleaned_path)

        if not source_path:
            return False

        if _is_private_media_path(source_path):
            return False

        return _path_matches_prefix(
            source_path,
            PUBLIC_MEDIA_PREFIXES,
        )

    # ------------------------------------------------------------------------
    # Original public media
    # ------------------------------------------------------------------------
    return _path_matches_prefix(
        cleaned_path,
        PUBLIC_MEDIA_PREFIXES,
    )


def _open_media_response(
    normalized_path,
    *,
    private=False,
):
    """
    Open a storage object and return a streaming response.

    Public media:
        Cache-Control: public, one year, immutable

    Private media:
        Cache-Control: private, no-store
        Vary: Cookie
    """
    try:
        file_obj = default_storage.open(
            normalized_path,
            "rb",
        )
    except Exception as exc:
        raise Http404(
            "Media file not found"
        ) from exc

    content_type, _ = mimetypes.guess_type(
        normalized_path
    )

    response = FileResponse(
        file_obj,
        content_type=content_type or "application/octet-stream",
    )

    response["X-Content-Type-Options"] = "nosniff"

    if private:
        response["Cache-Control"] = (
            "private, no-store, no-cache, must-revalidate"
        )

        response["Pragma"] = "no-cache"
        response["Expires"] = "0"

        patch_vary_headers(
            response,
            ["Cookie"],
        )

    else:
        response["Cache-Control"] = (
            "public, max-age=31536000, immutable"
        )

    return response


@require_safe
def serve_public_media(request, path):
    """
    Secure Arolana media gateway.

    PUBLIC ACCESS
    -------------
    Anonymous users may retrieve only explicitly approved public media:
    - products;
    - categories;
    - vendors;
    - manufacturers;
    - provider profile photos, logos and banners;
    - project images, thumbnails and videos;
    - homepage media;
    - advertisements;
    - promotional media;
    - blog media;
    - landing-page media;
    - newsletter public images;
    - validated optimized derivatives of public source media.

    PRIVATE ACCESS
    --------------
    Sensitive namespaces are never publicly available.

    Staff users may retrieve private media through the same endpoint for
    legitimate moderation/admin review. Private responses are never publicly
    cacheable.

    Unknown media namespaces are denied by default.
    """
    normalized_path = _clean_media_path(path)

    if not normalized_path:
        raise Http404(
            "Media file not found"
        )

    # ------------------------------------------------------------------------
    # PRIVATE MEDIA
    #
    # Anonymous/non-staff callers receive a 404 rather than 403 so that the
    # endpoint does not confirm whether a sensitive object path exists.
    # ------------------------------------------------------------------------
    if _is_private_media_path(normalized_path):
        user = getattr(
            request,
            "user",
            None,
        )

        if not (
            user
            and user.is_authenticated
            and user.is_staff
        ):
            logger.warning(
                "Blocked unauthorised request to private media namespace."
            )

            raise Http404(
                "Media file not found"
            )

        return _open_media_response(
            normalized_path,
            private=True,
        )

    # ------------------------------------------------------------------------
    # PUBLIC MEDIA
    #
    # Unknown namespaces are denied by default.
    # ------------------------------------------------------------------------
    if not _is_public_media_path(normalized_path):
        logger.warning(
            "Blocked request to non-public media namespace."
        )

        raise Http404(
            "Media file not found"
        )

    return _open_media_response(
        normalized_path,
        private=False,
    )


# ============================================================================
# HEALTH
# ============================================================================


def health_check(request):
    return JsonResponse(
        {
            "status": "ok",
        }
    )


# ============================================================================
# SITEMAP PAGE
# ============================================================================


def sitemap_page(request):
    categories = Category.objects.filter(
        is_active=True,
        parent=None,
    )[:20]

    products = Product.objects.filter(
        is_active=True,
        approval_status="approved",
    )[:50]

    vendors = VendorProfile.objects.filter(
        is_verified=True,
        is_active=True,
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


# ============================================================================
# HOMEPAGE
# ============================================================================


def home_view(request):
    """Custom home view with video section and proper context."""
    from core.local_cache import local_get_or_set
    from homepage.models import HomepageVideoSection

    video_section = local_get_or_set(
        "homepage:video_section",
        lambda: HomepageVideoSection.objects.filter(
            is_active=True,
        )
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


# ============================================================================
# REGISTRATION / ONBOARDING REDIRECTS
# ============================================================================


def vendor_register_redirect(request):
    """
    Public vendor registration entry point.

    Prevents /vendors/register/ from returning 404 when shared with vendors.
    """
    return redirect(
        "/accounts/register/?account_type=vendor"
    )


def manufacturer_register_redirect(request):
    """
    Public manufacturer registration entry point.

    Supports:
    - /manufacturer/register/
    - /manufacturers/register/
    """
    return redirect(
        "/accounts/register/?account_type=manufacturer"
    )


def sell_redirect(request):
    """
    Public sell shortcut for onboarding vendors.
    """
    return redirect(
        "/vendors/register/"
    )


def returns_redirect(request, path=None):
    return redirect(
        "returns"
    )


# ============================================================================
# ERROR HANDLERS
# ============================================================================


def custom_404(request, exception):
    return render(
        request,
        "404.html",
        status=404,
    )


# ============================================================================
# CKEDITOR 5
# ============================================================================


try:
    from django_ckeditor_5.views import upload_file, browse_files

    CKEDITOR_URLS = [
        re_path(
            r"^ckeditor5/upload/",
            upload_file,
            name="ck_editor_5_upload_file",
        ),
        re_path(
            r"^ckeditor5/browse/",
            browse_files,
            name="ck_editor_5_browse_files",
        ),
    ]

    print(
        "✅ Using django_ckeditor_5 built-in views"
    )

except ImportError:
    from ckeditor_views.views import upload_file, browse_files

    CKEDITOR_URLS = [
        re_path(
            r"^ckeditor5/upload/",
            upload_file,
            name="ck_editor_5_upload_file",
        ),
        re_path(
            r"^ckeditor5/browse/",
            browse_files,
            name="ck_editor_5_browse_files",
        ),
    ]

    print(
        "⚠️ Using custom CKEditor views"
    )


# ============================================================================
# URL PATTERNS
# ============================================================================


urlpatterns = [
    # ------------------------------------------------------------------------
    # Secure media gateway
    #
    # IMPORTANT:
    # Keep before catch-all routes and root includes.
    # ------------------------------------------------------------------------
    re_path(
        r"^media/(?P<path>.*)$",
        serve_public_media,
        name="serve_public_media",
    ),

    # ------------------------------------------------------------------------
    # Admin & Core
    # ------------------------------------------------------------------------
    path(
        "admin/live-stats/",
        core_views.live_stats,
        name="live_stats",
    ),
    path(
        "admin/logo-check/",
        TemplateView.as_view(
            template_name="admin/logo_check.html"
        ),
        name="logo_check",
    ),
    path(
        "admin/upload-logo/",
        core_admin_views.upload_logo,
        name="upload_logo",
    ),
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
    path(
        "admin/",
        admin.site.urls,
    ),
    path(
        "visitor-analytics/",
        include("visitor_analytics.urls"),
    ),

    # ------------------------------------------------------------------------
    # Public onboarding redirects
    #
    # Keep before vendors/manufacturers includes.
    # ------------------------------------------------------------------------
    path(
        "sell/",
        sell_redirect,
        name="sell_redirect",
    ),
    path(
        "vendors/register/",
        vendor_register_redirect,
        name="vendor_register_redirect",
    ),
    path(
        "vendor/register/",
        vendor_register_redirect,
        name="vendor_register_redirect_singular",
    ),
    path(
        "manufacturer/register/",
        manufacturer_register_redirect,
        name="manufacturer_register_redirect",
    ),
    path(
        "manufacturers/register/",
        manufacturer_register_redirect,
        name="manufacturers_register_redirect",
    ),

    # ------------------------------------------------------------------------
    # Dedicated APIs
    #
    # Keep before broad products include.
    # ------------------------------------------------------------------------
    path(
        "api/installers/",
        include(
            (
                "installers.api_urls",
                "installers_api",
            ),
            namespace="installers_api",
        ),
    ),
    path(
        "api/provider/",
        include(
            (
                provider_urlpatterns,
                "provider_api",
            ),
            namespace="provider_api",
        ),
    ),
    path(
        "api/projects/",
        include(
            (
                "installers.project_api_urls",
                "projects_api",
            ),
            namespace="projects_api",
        ),
    ),
    path(
        "api/smartchat/",
        include(
            (
                "smartchat.api_urls",
                "smartchat_api",
            ),
            namespace="smartchat_api",
        ),
    ),
    path(
        "api/quotes/",
        include(
            (
                "core.api_urls",
                "quotes_api",
            ),
            namespace="quotes_api",
        ),
    ),
    path(
        "dashboard/provider/",
        include(
            (
                "installers.workspace_urls",
                "provider_workspace",
            ),
            namespace="provider_workspace",
        ),
    ),
    path(
        "api/",
        include(
            "products.urls",
            namespace="products_api",
        ),
    ),
    path(
        "",
        include("core.urls"),
    ),

    # ------------------------------------------------------------------------
    # Railway health check
    # ------------------------------------------------------------------------
    path(
        "health/",
        health_check,
        name="health",
    ),

    # ------------------------------------------------------------------------
    # PWA
    # ------------------------------------------------------------------------
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

    # ------------------------------------------------------------------------
    # SEO routes
    # ------------------------------------------------------------------------
    path(
        "",
        include("arolana_seo.urls"),
    ),

    # ------------------------------------------------------------------------
    # Homepage
    # ------------------------------------------------------------------------
    path(
        "",
        home_view,
        name="home",
    ),
    path(
        "sitemap/",
        sitemap_page,
        name="sitemap",
    ),

    # ------------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------------
    path(
        "accounts/",
        include("accounts.urls"),
    ),
    path(
        "accounts/",
        include("allauth.urls"),
    ),

    # ------------------------------------------------------------------------
    # Application URLs
    # ------------------------------------------------------------------------
    path(
        "newsletter/",
        include("newsletter.urls"),
    ),
    path(
        "vendors/",
        include("vendors.urls"),
    ),
    path(
        "installers/",
        include(
            (
                "installers.urls",
                "installers",
            ),
            namespace="installers",
        ),
    ),
    path(
        "projects/",
        include(
            (
                "installers.project_web_urls",
                "projects",
            ),
            namespace="projects",
        ),
    ),
    path(
        "products/",
        include("products.urls"),
    ),
    path(
        "orders/",
        include("orders.urls"),
    ),
    path(
        "deliveries/",
        include("deliveries.urls"),
    ),
    path(
        "order-robot/",
        include("order_robot.urls"),
    ),
    path(
        "dashboard/",
        include("dashboard.urls"),
    ),
    path(
        "hero-banners/",
        include("hero_banners.urls"),
    ),
    path(
        "ads/",
        include("ads.urls"),
    ),
    path(
        "pages/",
        include("pages.urls"),
    ),
    path(
        "manufacturers/",
        include("manufacturers.urls"),
    ),
    path(
        "kyc/",
        include("kyc.urls"),
    ),
    path(
        "chat/",
        include("chat.urls"),
    ),
    path(
        "blog/",
        include("blog.urls"),
    ),
    path(
        "currency/",
        include("currency.urls"),
    ),
    path(
        "api/currency/rates/",
        currency_views.api_currency_rates,
        name="api_currency_rates",
    ),
    path(
        "api/currency/convert/",
        currency_views.api_convert_amount,
        name="api_currency_convert",
    ),
    path(
        "subscriptions/",
        include("subscriptions.urls"),
    ),
    path(
        "videos/",
        include("videos.urls"),
    ),
    path(
        "reports/",
        include("reports.urls"),
    ),
    path(
        "notifications/",
        include("notifications.urls"),
    ),
    path(
        "payments/",
        include("arolana_payments.urls"),
    ),
    path(
        "landing/",
        include("landing_pages.urls"),
    ),
    path(
        "landing-preview/<slug:slug>/",
        landing_page_views.landing_page_preview,
        name="landing_page_preview",
    ),

    # ------------------------------------------------------------------------
    # Smart AI Chat
    # ------------------------------------------------------------------------
    path(
        "smartchat/",
        include(
            (
                "smartchat.urls",
                "smartchat",
            ),
            namespace="smartchat",
        ),
    ),
    path(
        "support/ai/",
        include("smartchat.compat_urls"),
    ),

    # ------------------------------------------------------------------------
    # Social Apps Status
    # ------------------------------------------------------------------------
    path(
        "social-apps-status/",
        accounts_views.social_apps_status,
        name="social_apps_status",
    ),

    # ------------------------------------------------------------------------
    # CKEditor
    # ------------------------------------------------------------------------
    *CKEDITOR_URLS,

    # ------------------------------------------------------------------------
    # Support Pages
    # ------------------------------------------------------------------------
    path(
        "shipping/",
        TemplateView.as_view(
            template_name="support/shipping.html"
        ),
        name="shipping",
    ),
    path(
        "youtube-embed-test/",
        TemplateView.as_view(
            template_name="youtube_embed_test.html"
        ),
        name="youtube_embed_test",
    ),
    path(
        "support/",
        contact_page,
        name="support",
    ),
    path(
        "contact/",
        contact_page,
        name="contact",
    ),
    path(
        "about/",
        page_by_slug,
        {
            "slug": "about",
        },
        name="about",
    ),
    path(
        "privacy/",
        page_by_slug,
        {
            "slug": "privacy",
        },
        name="privacy",
    ),
    path(
        "terms/",
        page_by_slug,
        {
            "slug": "terms",
        },
        name="terms",
    ),
    path(
        "returns/",
        page_by_slug,
        {
            "slug": "returns",
        },
        name="returns",
    ),
    path(
        "faq/",
        faq_page,
        name="faq",
    ),
    re_path(
        r"^returns/.*$",
        returns_redirect,
        name="returns_catchall",
    ),

    # ------------------------------------------------------------------------
    # Order tracking
    # ------------------------------------------------------------------------
    path(
        "orders/track/",
        orders_views.track_order,
        name="track_order",
    ),

    # ------------------------------------------------------------------------
    # Mobile Orders API
    #
    # Keep before search_ai root include.
    # ------------------------------------------------------------------------
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
        "api/mobile/orders/<int:order_id>/",
        orders_views.mobile_authenticated_order_detail_api,
        name="mobile_authenticated_order_detail_api",
    ),
    path(
        "api/mobile/orders/<int:order_id>/tracking/",
        orders_views.mobile_authenticated_order_tracking_api,
        name="mobile_authenticated_order_tracking_api",
    ),
    path(
        "api/mobile/tracking/<str:tracking_code>/",
        orders_views.mobile_authenticated_tracking_code_api,
        name="mobile_authenticated_tracking_code_api",
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

    # ------------------------------------------------------------------------
    # Mobile Notifications API
    # ------------------------------------------------------------------------
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

    # ------------------------------------------------------------------------
    # Mobile Customers / Ops / Staff APIs
    # ------------------------------------------------------------------------
    path(
        "",
        include("mobile_customers.urls"),
    ),
    path(
        "",
        include("arolana_ops.urls"),
    ),
    path(
        "",
        include("staff_mobile.urls"),
    ),

    # ------------------------------------------------------------------------
    # Search
    #
    # Keep after mobile API routes.
    # ------------------------------------------------------------------------
    path(
        "search/",
        include("search_ai.urls"),
    ),
    path(
        "",
        include(
            "search_ai.urls",
            namespace="search_ai_legacy",
        ),
    ),

    # ------------------------------------------------------------------------
    # Help & Debug
    # ------------------------------------------------------------------------
    path(
        "color-test/",
        TemplateView.as_view(
            template_name="products/color_test.html"
        ),
        name="color_test",
    ),
    path(
        "debug-colors/<int:product_id>/",
        products_views.debug_colors,
        name="debug_colors",
    ),
    path(
        "careers/",
        careers_page,
        name="careers",
    ),
    path(
        "help/",
        help_center,
        name="help_center",
    ),
    path(
        "faq/",
        faq_page,
        name="faq_page",
    ),
    path(
        "article/<slug:slug>/",
        article_detail,
        name="article_detail",
    ),
    path(
        "currency/diagnose/",
        currency_views.diagnose_currency,
        name="diagnose_currency",
    ),

    # ------------------------------------------------------------------------
    # Test Pages
    # ------------------------------------------------------------------------
    path(
        "ads-test/",
        TemplateView.as_view(
            template_name="ads/test.html"
        ),
        name="ads_test",
    ),
    path(
        "image-test/",
        TemplateView.as_view(
            template_name="ads/direct_test.html"
        ),
        name="image_test",
    ),
    path(
        "social-test/",
        TemplateView.as_view(
            template_name="socialaccount/test.html"
        ),
        name="social_test",
    ),

    # ------------------------------------------------------------------------
    # Landing clean detail
    #
    # Keep near bottom because it catches slugs.
    # ------------------------------------------------------------------------
    path(
        "<slug:slug>/",
        landing_page_views.landing_page_detail,
        name="landing_page_clean_detail",
    ),
]


# ============================================================================
# DEVELOPMENT STATIC / MEDIA
# ============================================================================


if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )

    urlpatterns += static(
        settings.STATIC_URL,
        document_root=settings.STATIC_ROOT,
    )


# ============================================================================
# CUSTOM ERROR HANDLER
# ============================================================================


handler404 = "arolana_config.urls.custom_404"