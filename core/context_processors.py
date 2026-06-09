from core.models import SiteSettings, HomePageAppearance
from django.db.models import Count, Prefetch, Q, Sum
from types import SimpleNamespace
from products.models import Category, Product
from vendors.models import VendorProfile
from manufacturers.models import Manufacturer, ManufacturerCategory
from currency.models import Currency
import random
import logging
from django.conf import settings
from core.local_cache import local_get_or_set


GLOBAL_CONTEXT_CACHE_TIMEOUT = 300
logger = logging.getLogger(__name__)


def _cached(key, builder, timeout=GLOBAL_CONTEXT_CACHE_TIMEOUT):
    return local_get_or_set(key, builder, timeout)


def _safe_cached(key, builder, default, timeout=GLOBAL_CONTEXT_CACHE_TIMEOUT):
    try:
        return _cached(key, builder, timeout)
    except Exception as exc:
        logger.warning("Global context lookup failed for %s: %s", key, exc)
        return default


def _fallback_site_settings():
    return SimpleNamespace(
        site_name="Arolana",
        site_tagline="Smart Global Marketplace",
        site_description="Smart global marketplace for customers, vendors, and manufacturers.",
        site_keywords="Arolana, marketplace, ecommerce",
        meta_author="Arolana",
        meta_robots="index,follow",
        primary_color="#d4af37",
        secondary_color="#111827",
        site_logo=None,
        site_favicon=None,
        footer_logo=None,
        smart_chat_bot_image=None,
        facebook_url="",
        twitter_url="",
        instagram_url="",
        youtube_url="",
        contact_email="",
        contact_phone="",
        address="",
        shipping_note="",
        return_note="",
    )


def _fallback_homepage_appearance():
    return SimpleNamespace(
        is_active=False,
        desktop_background_image=None,
        mobile_background_image=None,
        desktop_overlay_opacity=0.35,
        mobile_overlay_opacity=0.50,
        desktop_position="center center",
        mobile_position="center center",
        blur_background=False,
        fixed_background=True,
        make_sections_glass=True,
    )


def _main_categories():
    grandchild_queryset = Category.objects.filter(is_active=True).order_by("order", "name")

    child_queryset = (
        Category.objects
        .filter(is_active=True)
        .annotate(active_child_count=Count("children", filter=Q(children__is_active=True)))
        .prefetch_related(Prefetch("children", queryset=grandchild_queryset))
        .order_by("order", "name")
    )

    return list(
        Category.objects
        .filter(parent=None, is_active=True)
        .annotate(active_child_count=Count("children", filter=Q(children__is_active=True)))
        .prefetch_related(Prefetch("children", queryset=child_queryset))
        .order_by("order", "name")
    )


def global_context(request):
    """Global context for all templates"""

    def build_site_settings():
        site_settings = SiteSettings.objects.first()
        if not site_settings:
            site_settings = SiteSettings.objects.create()
        return site_settings

    site_settings = _safe_cached(
        "global_context:site_settings",
        build_site_settings,
        _fallback_site_settings(),
    )

    homepage_appearance = _safe_cached(
        "global_context:homepage_appearance",
        lambda: HomePageAppearance.load(),
        _fallback_homepage_appearance(),
        3600,
    )

    featured_products = _safe_cached(
        "global_context:featured_products",
        lambda: list(
            Product.objects
            .filter(is_featured=True, is_active=True, approval_status="approved")
            .select_related("category", "brand")
            .order_by("-created_at")[:8]
        ),
        [],
    )

    vendors = _safe_cached(
        "global_context:verified_vendors",
        lambda: list(VendorProfile.objects.filter(is_verified=True, is_active=True)),
        [],
    )
    vendors = list(vendors)
    random.shuffle(vendors)
    vendors = vendors[:4]

    main_categories = _safe_cached(
        "global_context:main_categories",
        _main_categories,
        [],
    )

    top_vendors = _safe_cached(
        "global_context:top_vendors",
        lambda: list(
            VendorProfile.objects
            .filter(is_verified=True, is_active=True)
            .order_by("-rating_avg")[:5]
        ),
        [],
    )

    trending_vendors = _safe_cached(
        "global_context:trending_vendors",
        lambda: list(
            VendorProfile.objects
            .filter(is_verified=True, is_active=True)
            .order_by("-total_sales")[:5]
        ),
        [],
    )

    manufacturer_categories = _safe_cached(
        "global_context:manufacturer_categories",
        lambda: list(
            ManufacturerCategory.objects
            .filter(is_active=True)
            .order_by("display_order", "name")
        ),
        [],
    )

    featured_manufacturers = _safe_cached(
        "global_context:featured_manufacturers",
        lambda: list(
            Manufacturer.objects
            .filter(is_featured=True, is_active=True)[:4]
        ),
        [],
    )

    active_currencies = _safe_cached(
        "global_context:active_currencies",
        lambda: list(Currency.objects.filter(is_active=True).order_by("code")),
        [],
        3600,
    )

    notification_unread_count = 0
    recent_user_notifications = []
    chat_unread_count = 0

    if request.user.is_authenticated:
        try:
            from notifications.models import Notification

            user_notifications = Notification.objects.filter(
                user=request.user,
                is_archived=False,
            )
            notification_unread_count = user_notifications.filter(is_read=False).count()
            recent_user_notifications = list(user_notifications.order_by("-created_at")[:5])
        except Exception:
            notification_unread_count = 0
            recent_user_notifications = []

        try:
            from chat.models import ChatMessage, VendorChatRoom

            direct_unread = (
                ChatMessage.objects
                .filter(
                    room__participants=request.user,
                    room__is_active=True,
                    is_active=True,
                    is_read=False,
                )
                .exclude(sender=request.user)
                .count()
            )

            vendor_unread = (
                VendorChatRoom.objects
                .filter(customer=request.user, is_active=True)
                .aggregate(total=Sum("customer_unread"))["total"] or 0
            )

            seller_unread = (
                VendorChatRoom.objects
                .filter(vendor=request.user, is_active=True)
                .aggregate(total=Sum("vendor_unread"))["total"] or 0
            )

            chat_unread_count = direct_unread + vendor_unread + seller_unread
        except Exception:
            chat_unread_count = 0

    return {
        "site_settings": site_settings,
        "homepage_appearance": homepage_appearance,

        "featured_products": featured_products,
        "vendors": vendors,
        "main_categories": main_categories,
        "top_vendors": top_vendors,
        "trending_vendors": trending_vendors,
        "manufacturer_categories": manufacturer_categories,
        "featured_manufacturers": featured_manufacturers,

        "DEBUG": settings.DEBUG,
        "SITE_URL": getattr(settings, "SITE_URL", "http://localhost:8000"),
        "GOOGLE_MAPS_API_KEY": getattr(settings, "GOOGLE_MAPS_API_KEY", ""),

        "notification_unread_count": notification_unread_count,
        "recent_user_notifications": recent_user_notifications,
        "chat_unread_count": chat_unread_count,

        "all_currencies": active_currencies,
        "current_currency_code": (
            request.session.get("user_currency")
            or request.COOKIES.get("user_currency")
            or "USD"
        ),
        "currency_source": request.session.get("user_currency_source", "auto"),
    }


def admin_notifications(request):
    """Admin notifications context processor - single definition"""
    from orders.models import Order
    from vendors.models import VendorProfile
    from notifications.models import Notification

    if request.user.is_authenticated and request.user.is_staff:
        pending_orders = Order.objects.filter(status="pending").count()
        pending_vendors = VendorProfile.objects.filter(is_verified=False).count()

        notifications = Notification.objects.filter(user=request.user).order_by("-created_at")[:10]
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()

        return {
            "admin_notifications": {
                "pending_orders": pending_orders,
                "pending_vendors": pending_vendors,
                "total_pending": pending_orders + pending_vendors,
            },
            "recent_notifications": notifications,
            "admin_notification_count": unread_count,
            "has_unread_notifications": unread_count > 0,
        }

    return {
        "admin_notifications": {
            "pending_orders": 0,
            "pending_vendors": 0,
            "total_pending": 0,
        },
        "recent_notifications": [],
        "admin_notification_count": 0,
        "has_unread_notifications": False,
    }
