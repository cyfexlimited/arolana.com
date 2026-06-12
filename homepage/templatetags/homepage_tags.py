from django import template
from django.db.models import Count, Q, Prefetch

from homepage.models import (
    HomepageCategory,
    HomepageBanner,
    HomepageBannerImage,
    HomepageSection,
    HomepageVendorSettings,
    HomepageNewsletterSettings,
    HomepageManufacturerSettings,
    HomepageManufacturerCategory,
    HomepageVideoSection,
    HomepageVendorSection,
)
from vendors.models import VendorProfile
from manufacturers.models import Manufacturer
from core.local_cache import local_get_or_set

import random


register = template.Library()
HOMEPAGE_CACHE_TIMEOUT = 300


# ============================================================
# HOMEPAGE CATEGORIES
# ============================================================

@register.inclusion_tag("homepage/categories.html", takes_context=True)
def homepage_categories(context):
    request = context.get("request")

    def build_categories():
        categories = list(
            HomepageCategory.objects
            .filter(
                is_active=True,
                category__isnull=False,
                category__is_active=True,
            )
            .select_related("category")
            .annotate(
                product_total=Count(
                    "category__products",
                    filter=Q(
                        category__products__is_active=True,
                        category__products__approval_status="approved",
                    ),
                )
            )
            .order_by("display_order", "id")
        )

        default_images = {
            "accessories": "/media/categories/defaults/accessories.jpg",
            "audio": "/media/categories/defaults/audio.jpg",
            "cameras": "/media/categories/defaults/cameras.jpg",
            "electronics": "/media/categories/defaults/electronics.jpg",
            "gaming": "/media/categories/defaults/gaming.jpg",
            "laptops": "/media/categories/defaults/laptops.jpg",
            "smart-home": "/media/categories/defaults/smart-home.jpg",
            "smartphones": "/media/categories/defaults/phones.jpg",
        }

        default_icons = {
            "accessories": "fas fa-keyboard",
            "audio": "fas fa-headphones",
            "cameras": "fas fa-camera",
            "electronics": "fas fa-microchip",
            "gaming": "fas fa-gamepad",
            "laptops": "fas fa-laptop",
            "smart-home": "fas fa-home",
            "smartphones": "fas fa-mobile-alt",
        }

        for hp_category in categories:
            hp_category.image_url = None
            hp_category.product_count = 0

            if not hp_category.category:
                continue

            hp_category.product_count = hp_category.product_total or 0

            if not hp_category.category.image:
                hp_category.image_url = default_images.get(hp_category.category.slug)

            if not hp_category.icon:
                hp_category.icon = default_icons.get(
                    hp_category.category.slug,
                    "fas fa-folder-open"
                )

            if hp_category.icon and not hp_category.icon.startswith("fa"):
                hp_category.icon = f"fas fa-{hp_category.icon}"

        return categories

    categories = local_get_or_set(
        "homepage:categories",
        build_categories,
        HOMEPAGE_CACHE_TIMEOUT
    )

    return {
        "categories": categories,
        "request": request,
    }


# ============================================================
# HOMEPAGE BANNERS WITH FLEXIBLE PLACEMENT
# ============================================================

def _audience_allowed(banner, request):
    user = getattr(request, "user", None)

    if banner.target_audience == "all":
        return True

    if banner.target_audience == "guests":
        return not getattr(user, "is_authenticated", False)

    if banner.target_audience == "authenticated":
        return getattr(user, "is_authenticated", False)

    if not getattr(user, "is_authenticated", False):
        return False

    if banner.target_audience == "staff":
        return getattr(user, "is_staff", False)

    user_type = getattr(user, "user_type", "") or ""

    if banner.target_audience == "customers":
        return user_type == "customer"

    if banner.target_audience == "vendors":
        return user_type == "vendor"

    if banner.target_audience == "manufacturers":
        return user_type == "manufacturer"

    return True


@register.inclusion_tag("homepage/banner.html", takes_context=True)
def homepage_banner(context, placement="top", style=""):
    """
    Usage in templates:

        {% homepage_banner %}
        {% homepage_banner "top" %}
        {% homepage_banner "after_categories" %}
        {% homepage_banner "after_products" %}
        {% homepage_banner "after_manufacturers" %}
        {% homepage_banner "after_vendors" %}
        {% homepage_banner "before_newsletter" %}

    Optional style filter:

        {% homepage_banner "after_categories" "wide_strip" %}
    """

    request = context.get("request")

    def build_banners():
        qs = (
            HomepageBanner.objects
            .filter(
                is_active=True,
                show_on_homepage=True,
                placement=placement,
            )
            .prefetch_related(
                Prefetch(
                    "uploaded_images",
                    queryset=HomepageBannerImage.objects
                    .filter(is_active=True)
                    .order_by("display_order", "id"),
                    to_attr="active_uploaded_images",
                )
            )
            .order_by("display_order", "id")
        )

        if style:
            qs = qs.filter(banner_style=style)

        return list(qs)

    cache_key = f"homepage:banners:v4:{placement}:{style or 'all'}"

    raw_banners = local_get_or_set(
        cache_key,
        build_banners,
        HOMEPAGE_CACHE_TIMEOUT
    )

    banners = []

    for banner in raw_banners:
        if request and not _audience_allowed(banner, request):
            continue

        images = list(getattr(banner, "active_uploaded_images", []))

        banner.background_image = next(
            (img for img in images if img.position == "background"),
            None
        )
        banner.left_images = [
            img for img in images if img.position == "left"
        ]
        banner.center_images = [
            img for img in images if img.position == "center"
        ]
        banner.right_images = [
            img for img in images if img.position == "right"
        ]

        banners.append(banner)

    return {
        "request": request,
        "banners": banners,
        "has_full_width_banner": any(banner.full_width for banner in banners),
        "placement": placement,
        "style": style,
        "site_settings": context.get("site_settings"),
    }


# ============================================================
# HOMEPAGE PRODUCT SECTIONS
# ============================================================

@register.inclusion_tag("homepage/sections.html", takes_context=True)
def homepage_sections(context):
    request = context.get("request")

    def build_sections():
        sections = list(
            HomepageSection.objects
            .filter(is_active=True)
            .order_by("display_order", "id")
        )

        for section in sections:
            section.products = list(section.get_products())

        return sections

    sections = local_get_or_set(
        "homepage:sections",
        build_sections,
        HOMEPAGE_CACHE_TIMEOUT
    )

    return {
        "sections": sections,
        "request": request,
    }


# ============================================================
# VENDOR CAROUSEL
# ============================================================

@register.inclusion_tag("homepage/vendor_carousel.html", takes_context=True)
def vendor_carousel(context):
    request = context.get("request")

    settings = local_get_or_set(
        "homepage:vendor_settings",
        lambda: HomepageVendorSettings.objects.first(),
        HOMEPAGE_CACHE_TIMEOUT
    )

    if not settings or not settings.is_active:
        return {
            "vendors": [],
            "settings": None,
            "request": request,
        }

    vendors = list(local_get_or_set(
        f"homepage:vendor_carousel:{settings.vendor_count}",
        lambda: list(
            VendorProfile.objects
            .filter(is_verified=True, is_active=True)
            .select_related("user")
            .order_by("-rating_avg", "-total_sales")[:settings.vendor_count]
        ),
        HOMEPAGE_CACHE_TIMEOUT,
    ))

    random.shuffle(vendors)

    return {
        "vendors": vendors,
        "settings": settings,
        "request": request,
    }


# ============================================================
# HOMEPAGE VENDOR SECTIONS
# ============================================================

@register.inclusion_tag("homepage/vendor_sections.html", takes_context=True)
def homepage_vendor_sections(context):
    request = context.get("request")

    def build_sections():
        sections = list(
            HomepageVendorSection.objects
            .filter(is_active=True)
            .order_by("sort_order", "title", "id")
        )

        if not sections and not HomepageVendorSection.objects.exists():
            sections = [
                HomepageVendorSection(
                    title="Verified Vendors",
                    description="Trusted Arolana sellers across all vendor types.",
                    section_type="verified_vendors",
                    verified_only=True,
                    max_items=12,
                    empty_state_text="No verified vendors yet.",
                    view_all_url="/vendors/?section=verified_vendors",
                ),
                HomepageVendorSection(
                    title="Factory Direct Manufacturers",
                    description="Verified factory-direct suppliers and manufacturers.",
                    section_type="factory_direct_manufacturers",
                    verified_only=True,
                    manufacturer_only=True,
                    max_items=12,
                    empty_state_text="No verified manufacturers yet.",
                    view_all_url="/vendors/?section=factory_direct_manufacturers",
                ),
                HomepageVendorSection(
                    title="Top Retailers",
                    description="Retail-ready sellers with verified Arolana stores.",
                    section_type="top_retailers",
                    vendor_type_filter="retailer",
                    verified_only=True,
                    max_items=12,
                    empty_state_text="No verified retailers yet.",
                    view_all_url="/vendors/?section=top_retailers",
                ),
                HomepageVendorSection(
                    title="Distributors & Wholesalers",
                    description="Bulk supply partners for trade buyers.",
                    section_type="distributors_wholesalers",
                    vendor_type_filter="distributor_wholesaler",
                    verified_only=True,
                    max_items=12,
                    empty_state_text="No distributors or wholesalers yet.",
                    view_all_url="/vendors/?section=distributors_wholesalers",
                ),
                HomepageVendorSection(
                    title="Service Providers",
                    description="Verified service providers for business support.",
                    section_type="service_providers",
                    vendor_type_filter="service_provider",
                    verified_only=True,
                    max_items=12,
                    empty_state_text="No service providers yet.",
                    view_all_url="/vendors/?section=service_providers",
                ),
            ]

        visible_sections = []

        for section in sections:
            section.vendors = list(section.get_vendor_queryset())

            if section.vendors or section.show_when_empty:
                visible_sections.append(section)

        return visible_sections

    sections = local_get_or_set(
        "homepage:vendor_sections:v3",
        build_sections,
        HOMEPAGE_CACHE_TIMEOUT
    )

    return {
        "sections": sections,
        "request": request,
    }


# ============================================================
# NEWSLETTER SECTION
# ============================================================

@register.inclusion_tag("homepage/newsletter.html", takes_context=True)
def newsletter_section(context):
    request = context.get("request")

    settings = local_get_or_set(
        "homepage:newsletter_settings",
        lambda: HomepageNewsletterSettings.objects.first(),
        HOMEPAGE_CACHE_TIMEOUT
    )

    return {
        "settings": settings,
        "request": request,
    }


# ============================================================
# MANUFACTURERS SECTION
# ============================================================

@register.inclusion_tag("homepage/manufacturers_section.html", takes_context=True)
def manufacturers_section(context):
    request = context.get("request")

    def build_manufacturers_section():
        settings = HomepageManufacturerSettings.objects.first()

        if not settings or not settings.is_active:
            return None, [], []

        if settings.show_featured_only:
            manufacturers = list(
                Manufacturer.objects
                .filter(is_featured=True, is_active=True)
                .order_by("-rating_avg", "-total_sales")[:settings.display_count]
            )
        else:
            manufacturers = list(
                Manufacturer.objects
                .filter(is_active=True)
                .order_by("-total_sales", "-rating_avg")[:settings.display_count]
            )

        homepage_categories = (
            HomepageManufacturerCategory.objects
            .filter(is_active=True)
            .select_related("category")
            .order_by("display_order", "id")
        )

        categories = [
            item.category
            for item in homepage_categories
            if item.category and item.category.is_active
        ]

        return settings, manufacturers, categories

    settings, manufacturers, categories = local_get_or_set(
        "homepage:manufacturers_section",
        build_manufacturers_section,
        HOMEPAGE_CACHE_TIMEOUT,
    )

    if not settings:
        return {
            "show_section": False,
            "request": request,
        }

    return {
        "show_section": True,
        "settings": settings,
        "manufacturers": manufacturers,
        "categories": categories,
        "request": request,
    }


# ============================================================
# VIDEO SECTION
# ============================================================

@register.inclusion_tag("homepage/video_section.html", takes_context=True)
def video_section(context):
    request = context.get("request")
    existing_video_section = context.get("video_section")

    if existing_video_section:
        return {
            "video_section": existing_video_section,
            "request": request,
        }

    try:
        homepage_video = local_get_or_set(
            "homepage:video_section",
            lambda: HomepageVideoSection.objects
            .filter(is_active=True)
            .order_by("display_order", "id")
            .first(),
            HOMEPAGE_CACHE_TIMEOUT,
        )

        if homepage_video:
            return {
                "video_section": homepage_video,
                "request": request,
            }

    except Exception as exc:
        print(f"Video section error: {exc}")

    return {
        "video_section": None,
        "request": request,
    }
