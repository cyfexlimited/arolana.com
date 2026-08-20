import logging
import mimetypes
import posixpath
import re

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.core.files.storage import default_storage
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import redirect, render
from django.urls import include, path, re_path
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_safe
from django.views.generic import TemplateView

from accounts import views as accounts_views
from core import admin_views as core_admin_views
from core.deployment_health import readiness_status
from core import views as core_views
from core.private_media import authorize_private_media_request
from core.private_media_audit import record_private_media_access
from installers.api_urls import provider_urlpatterns
from landing_pages import views as landing_page_views
from orders import views as orders_views
from pages.views import (
    article_detail,
    careers_page,
    contact_page,
    faq_page,
    help_center,
    page_by_slug,
)
from products import views as products_views

import currency.views as currency_views


logger = logging.getLogger(__name__)


# ============================================================================
# MEDIA SECURITY POLICY
# ============================================================================

PUBLIC_MEDIA_PREFIXES = (
    "settings",
    "categories",
    "hero_banners",
    "homepage",
    "brands",
    "avatars",
    "products",
    "accessories",
    "vendors",
    "manufacturers",
    "ads",
    "advertisements",
    "promo",
    "blog",
    "landing_pages",
    "uploads",
    "newsletter",
    "videos",
    "support",
    "reviews/videos",
    "reviews/thumbs",
    "installers/providers",
    "installers/categories",
    "installers/portfolio",
    "installers/projects/gallery",
    "installers/projects/thumbnails",
    "installers/projects/videos",
    "installers/projects/documents",
    "installers/homepage",
    "crypto_wallet_qr",
)


PRIVATE_MEDIA_PREFIXES = (
    "installers/kyc",
    "installers/verification",
    "installers/profile-change-requests",
    "installers/completions",
    "installers/providers/kyc",
    "installers/providers/private",
    "installers/providers/documents",
    "kyc",
    "delivery/riders/id_documents",
    "delivery/riders/licenses",
    "delivery/riders/vehicle_documents",
    "delivery/riders/photos",
    "delivery/riders/banners",
    "delivery/proofs",
    "chat/attachments",
    "chat/vendor_attachments",
    "smartchat/images",
    "payment_proofs",
    "job_applications/resumes",
    "mobile_customers/profile_pictures",
    "private",
    "protected",
    "verification",
    "identity",
    "documents/private",
    "vendors/kyc",
    "vendors/private",
    "vendors/documents",
    "manufacturers/kyc",
    "manufacturers/private",
    "manufacturers/documents",
    "accounts/kyc",
    "accounts/private",
    "accounts/documents",
)


# ============================================================================
# MEDIA PATH HELPERS
# ============================================================================


def _clean_media_path(path):
    raw_path = str(path or "").strip()

    if not raw_path or "\x00" in raw_path:
        return ""

    raw_path = raw_path.replace("\\", "/")

    if any(segment == ".." for segment in raw_path.split("/")):
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
            or comparison_path.startswith(f"{comparison_prefix}/")
        ):
            return True

    return False


def _optimized_source_path(path):
    cleaned_path = _clean_media_path(path)

    if not cleaned_path or not cleaned_path.lower().startswith("optimized/"):
        return ""

    parts = cleaned_path.split("/", 2)

    if len(parts) != 3:
        return ""

    return _clean_media_path(parts[2])


def _is_private_media_path(path):
    cleaned_path = _clean_media_path(path)

    if not cleaned_path:
        return True

    if _path_matches_prefix(cleaned_path, PRIVATE_MEDIA_PREFIXES):
        return True

    source_path = _optimized_source_path(cleaned_path)

    return bool(
        source_path
        and _path_matches_prefix(source_path, PRIVATE_MEDIA_PREFIXES)
    )


def _is_public_media_path(path):
    cleaned_path = _clean_media_path(path)

    if not cleaned_path or _is_private_media_path(cleaned_path):
        return False

    if cleaned_path.lower().startswith("optimized/"):
        source_path = _optimized_source_path(cleaned_path)

        if not source_path or _is_private_media_path(source_path):
            return False

        return _path_matches_prefix(source_path, PUBLIC_MEDIA_PREFIXES)

    return _path_matches_prefix(cleaned_path, PUBLIC_MEDIA_PREFIXES)


# ============================================================================
# HTTP BYTE-RANGE SUPPORT
# ============================================================================

_RANGE_HEADER_PATTERN = re.compile(
    r"^bytes=(\d*)-(\d*)$",
    re.IGNORECASE,
)


def _media_file_size(file_obj, normalized_path):
    try:
        return int(default_storage.size(normalized_path))
    except Exception:
        pass

    try:
        original_position = int(file_obj.tell())
    except Exception:
        original_position = 0

    try:
        file_obj.seek(0, 2)
        return int(file_obj.tell())
    finally:
        try:
            file_obj.seek(original_position)
        except Exception:
            pass


def _parse_media_range(range_header, file_size):
    header = str(range_header or "").strip()

    if not header:
        return None

    match = _RANGE_HEADER_PATTERN.fullmatch(header)

    if not match:
        raise ValueError("Invalid Range header.")

    first_value = match.group(1)
    last_value = match.group(2)

    if not first_value and not last_value:
        raise ValueError("Empty Range header.")

    if first_value:
        start = int(first_value)
        end = int(last_value) if last_value else file_size - 1
    else:
        suffix_length = int(last_value)

        if suffix_length <= 0:
            raise ValueError("Invalid suffix range.")

        suffix_length = min(suffix_length, file_size)
        start = file_size - suffix_length
        end = file_size - 1

    if start < 0 or start >= file_size or end < start:
        raise ValueError("Requested range is not satisfiable.")

    return start, min(end, file_size - 1)


def _iter_media_range(
    file_obj,
    *,
    start,
    length,
    chunk_size=64 * 1024,
):
    try:
        file_obj.seek(start)
        remaining = int(length)

        while remaining > 0:
            chunk = file_obj.read(min(chunk_size, remaining))

            if not chunk:
                break

            remaining -= len(chunk)
            yield chunk
    finally:
        try:
            file_obj.close()
        except Exception:
            pass


def _safe_inline_filename(normalized_path):
    filename = str(normalized_path.rsplit("/", 1)[-1] or "media")
    filename = filename.replace("\r", "").replace("\n", "").replace('"', "")
    return filename or "media"


def _apply_media_security_headers(response, *, private):
    response["X-Content-Type-Options"] = "nosniff"
    response["Accept-Ranges"] = "bytes"

    if private:
        response["Cache-Control"] = (
            "private, no-store, no-cache, must-revalidate"
        )
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        patch_vary_headers(response, ["Cookie"])
    else:
        response["Cache-Control"] = "public, max-age=31536000, immutable"

    return response


def _range_not_satisfiable_response(
    *,
    file_size,
    content_type,
    filename,
    private,
):
    response = HttpResponse(status=416, content_type=content_type)
    response["Content-Range"] = f"bytes */{file_size}"
    response["Content-Length"] = "0"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return _apply_media_security_headers(response, private=private)


def _open_media_response(
    request,
    normalized_path,
    *,
    private=False,
):
    try:
        file_obj = default_storage.open(normalized_path, "rb")
    except Exception as exc:
        logger.warning(
            "Could not open media object path=%s error=%s",
            normalized_path,
            exc,
        )
        raise Http404("Media file not found") from exc

    try:
        file_size = _media_file_size(file_obj, normalized_path)
    except Exception as exc:
        try:
            file_obj.close()
        except Exception:
            pass

        logger.warning(
            "Could not determine media size path=%s error=%s",
            normalized_path,
            exc,
        )
        raise Http404("Media file not found") from exc

    if file_size <= 0:
        try:
            file_obj.close()
        except Exception:
            pass
        raise Http404("Media file not found")

    content_type = (
        mimetypes.guess_type(normalized_path)[0]
        or "application/octet-stream"
    )
    filename = _safe_inline_filename(normalized_path)

    try:
        requested_range = _parse_media_range(
            request.headers.get("Range", ""),
            file_size,
        )
    except (TypeError, ValueError):
        try:
            file_obj.close()
        except Exception:
            pass

        return _range_not_satisfiable_response(
            file_size=file_size,
            content_type=content_type,
            filename=filename,
            private=private,
        )

    if requested_range is not None:
        start, end = requested_range
        content_length = end - start + 1

        if request.method == "HEAD":
            try:
                file_obj.close()
            except Exception:
                pass
            response = HttpResponse(status=206, content_type=content_type)
        else:
            response = StreamingHttpResponse(
                _iter_media_range(
                    file_obj,
                    start=start,
                    length=content_length,
                ),
                status=206,
                content_type=content_type,
            )

        response["Content-Length"] = str(content_length)
        response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return _apply_media_security_headers(response, private=private)

    if request.method == "HEAD":
        try:
            file_obj.close()
        except Exception:
            pass

        response = HttpResponse(status=200, content_type=content_type)
        response["Content-Length"] = str(file_size)
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return _apply_media_security_headers(response, private=private)

    response = FileResponse(file_obj, content_type=content_type)
    response["Content-Length"] = str(file_size)
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return _apply_media_security_headers(response, private=private)


@require_safe
def serve_public_media(request, path):
    normalized_path = _clean_media_path(path)

    if not normalized_path:
        raise Http404("Media file not found")

    if _is_private_media_path(normalized_path):
        decision = authorize_private_media_request(request, normalized_path)

        if not decision.allowed:
            record_private_media_access(
                request=request,
                path=normalized_path,
                decision=decision,
            )

            logger.warning(
                (
                    "Blocked unauthorized private media request. "
                    "reason=%s rule=%s model=%s object_id=%s user_id=%s"
                ),
                decision.reason,
                decision.rule_key,
                decision.model_label,
                decision.object_id,
                decision.principal_user_id,
            )
            raise Http404("Media file not found")

        response = _open_media_response(
            request,
            normalized_path,
            private=True,
        )

        record_private_media_access(
            request=request,
            path=normalized_path,
            decision=decision,
        )
        return response

    if not _is_public_media_path(normalized_path):
        logger.warning(
            "Blocked request to non-public media namespace path=%s",
            normalized_path,
        )
        raise Http404("Media file not found")

    return _open_media_response(
        request,
        normalized_path,
        private=False,
    )


@require_safe
def stream_public_media(request, path):
    """
    Send public video playback to object storage.

    Cloudflare can cache the first full proxy response for a large MP4 and then
    answer later Range requests with that same 200 response. A short-lived,
    uncached redirect lets the browser negotiate byte ranges with Tigris
    directly while keeping the bucket private.
    """
    normalized_path = _clean_media_path(path)
    video_suffix = posixpath.splitext(normalized_path)[1].lower()

    if (
        not normalized_path
        or video_suffix not in {".mp4", ".webm", ".mov", ".m4v"}
        or not _is_public_media_path(normalized_path)
    ):
        raise Http404("Media file not found")

    try:
        direct_url = default_storage.url(
            normalized_path,
            expire=15 * 60,
            http_method=request.method,
        )
    except (AttributeError, NotImplementedError, TypeError, ValueError):
        direct_url = ""

    if str(direct_url).startswith(("http://", "https://")):
        response = redirect(direct_url)
        response["Cache-Control"] = "private, no-store, max-age=0"
        response["Pragma"] = "no-cache"
        response["Referrer-Policy"] = "no-referrer"
        return response

    return _open_media_response(
        request,
        normalized_path,
        private=False,
    )


# ============================================================================
# HEALTH / SIMPLE PAGES
# ============================================================================


def health_check(request):
    return JsonResponse({"status": "ok"})


@require_safe
def health_live(request):
    return JsonResponse({"status": "ok", "check": "live"})


@require_safe
def health_ready(request):
    ready, payload = readiness_status()
    return JsonResponse(payload, status=200 if ready else 503)


def sitemap_page(request):
    # Local imports avoid circular imports while Django loads the root URLconf.
    from products.models import Category, Product
    from vendors.models import VendorProfile

    categories = Category.objects.filter(is_active=True, parent=None)[:20]
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


def home_view(request):
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
        {"video_section": video_section},
    )


def vendor_register_redirect(request):
    return redirect("/accounts/register/?account_type=vendor")


def manufacturer_register_redirect(request):
    return redirect("/accounts/register/?account_type=manufacturer")


def sell_redirect(request):
    return redirect("/vendors/register/")


def returns_redirect(request, path=None):
    return redirect("returns")


def custom_404(request, exception):
    return render(request, "404.html", status=404)


# ============================================================================
# CKEDITOR 5
# ============================================================================

try:
    from django_ckeditor_5.views import browse_files, upload_file

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

    print("✅ Using django_ckeditor_5 built-in views")
except ImportError:
    from ckeditor_views.views import browse_files, upload_file

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

    print("⚠️ Using custom CKEditor views")


# ============================================================================
# URL PATTERNS
# ============================================================================

urlpatterns = [
    re_path(
        r"^stream-media/(?P<path>.*)$",
        stream_public_media,
        name="stream_public_media",
    ),
    re_path(
        r"^media/(?P<path>.*)$",
        serve_public_media,
        name="serve_public_media",
    ),

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

    path("sell/", sell_redirect, name="sell_redirect"),
    path("vendors/register/", vendor_register_redirect, name="vendor_register_redirect"),
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

    path(
        "api/installers/",
        include(("installers.api_urls", "installers_api"), namespace="installers_api"),
    ),
    path(
        "api/provider/",
        include((provider_urlpatterns, "provider_api"), namespace="provider_api"),
    ),
    path(
        "api/ads/v2/",
        include(("ads.api_urls", "ads_api"), namespace="ads_api"),
    ),
    path(
        "api/projects/",
        include(("installers.project_api_urls", "projects_api"), namespace="projects_api"),
    ),
    path(
        "api/smartchat/",
        include(("smartchat.api_urls", "smartchat_api"), namespace="smartchat_api"),
    ),
    path(
        "api/quotes/",
        include(("core.api_urls", "quotes_api"), namespace="quotes_api"),
    ),
    path(
        "dashboard/provider/",
        include(
            ("installers.workspace_urls", "provider_workspace"),
            namespace="provider_workspace",
        ),
    ),
    path("api/", include("products.urls", namespace="products_api")),
    path("", include("core.urls")),

    path("health/", health_check, name="health"),
    path("health/live/", health_live, name="health_live"),
    path("health/ready/", health_ready, name="health_ready"),

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
    path("", home_view, name="home"),
    path("sitemap/", sitemap_page, name="sitemap"),

    path("accounts/", include("accounts.urls")),
    path("accounts/", include("allauth.urls")),

    path("newsletter/", include("newsletter.urls")),
    path("vendors/", include("vendors.urls")),
    path(
        "installers/",
        include(("installers.urls", "installers"), namespace="installers"),
    ),
    path(
        "projects/",
        include(("installers.project_web_urls", "projects"), namespace="projects"),
    ),
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
    path("subscriptions/", include("subscriptions.urls")),
    path("social-publishing/", include("social_publishing.web_urls")),
    path("api/social-publishing/", include("social_publishing.urls")),
    path("videos/", include("videos.urls")),
    path("reports/", include("reports.urls")),
    path("notifications/", include("notifications.urls")),
    path("payments/", include("arolana_payments.urls")),
    path("", include("ai_core.urls")),
    path("landing/", include("landing_pages.urls")),
    path(
        "landing-preview/<slug:slug>/",
        landing_page_views.landing_page_preview,
        name="landing_page_preview",
    ),

    path(
        "smartchat/",
        include(("smartchat.urls", "smartchat"), namespace="smartchat"),
    ),
    path("support/ai/", include("smartchat.compat_urls")),

    path(
        "social-apps-status/",
        accounts_views.social_apps_status,
        name="social_apps_status",
    ),

    *CKEDITOR_URLS,

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

    path("orders/track/", orders_views.track_order, name="track_order"),

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

    path("", include("mobile_customers.urls")),
    path("", include("arolana_ops.urls")),
    path("", include("staff_mobile.urls")),

    path("search/", include("search_ai.urls")),
    path(
        "",
        include("search_ai.urls", namespace="search_ai_legacy"),
    ),

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
    path("careers/", careers_page, name="careers"),
    path("help/", help_center, name="help_center"),
    path("faq/", faq_page, name="faq_page"),
    path("article/<slug:slug>/", article_detail, name="article_detail"),
    path(
        "currency/diagnose/",
        currency_views.diagnose_currency,
        name="diagnose_currency",
    ),

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

    path(
        "<slug:slug>/",
        landing_page_views.landing_page_detail,
        name="landing_page_clean_detail",
    ),
]


if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
    urlpatterns += static(
        settings.STATIC_URL,
        document_root=settings.STATIC_ROOT,
    )


handler404 = "arolana_config.urls.custom_404"
