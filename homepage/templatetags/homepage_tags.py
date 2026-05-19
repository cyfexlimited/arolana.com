from django import template
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Count, Q
from homepage.models import (
    HomepageCategory, HomepageBanner, HomepageSection, 
    HomepageVendorSettings, HomepageNewsletterSettings, 
    HomepageManufacturerSettings, HomepageManufacturerCategory,
    HomepageVideoSection
)
from vendors.models import VendorProfile
from products.models import Product
from manufacturers.models import Manufacturer
from core.local_cache import local_get_or_set
import random
import json

register = template.Library()
HOMEPAGE_CACHE_TIMEOUT = 300

@register.inclusion_tag('homepage/categories.html', takes_context=True)
def homepage_categories(context):
    request = context.get('request')
    def build_categories():
        categories = list(
            HomepageCategory.objects
            .filter(is_active=True)
            .select_related('category')
            .annotate(
                product_total=Count(
                    'category__products',
                    filter=Q(
                        category__products__is_active=True,
                        category__products__approval_status='approved',
                    ),
                )
            )
            .order_by('display_order')
        )
        # Enhance each category with fallback image URL and product count.
        for hp_category in categories:
            hp_category.image_url = None
            if not hp_category.category.image:
                default_images = {
                    'accessories': '/media/categories/defaults/accessories.jpg',
                    'audio': '/media/categories/defaults/audio.jpg',
                    'cameras': '/media/categories/defaults/cameras.jpg',
                    'electronics': '/media/categories/defaults/electronics.jpg',
                    'gaming': '/media/categories/defaults/gaming.jpg',
                    'laptops': '/media/categories/defaults/laptops.jpg',
                    'smart-home': '/media/categories/defaults/smart-home.jpg',
                    'smartphones': '/media/categories/defaults/phones.jpg',
                }
                hp_category.image_url = default_images.get(hp_category.category.slug, None)

            hp_category.product_count = hp_category.product_total

            if not hp_category.icon:
                default_icons = {
                    'accessories': 'keyboard',
                    'audio': 'headphones',
                    'cameras': 'camera',
                    'electronics': 'microchip',
                    'gaming': 'gamepad',
                    'laptops': 'laptop',
                    'smart-home': 'home',
                    'smartphones': 'mobile-alt',
                }
                hp_category.icon = default_icons.get(hp_category.category.slug, 'folder-open')
        return categories

    categories = local_get_or_set('homepage:categories', build_categories, HOMEPAGE_CACHE_TIMEOUT)
    
    return {'categories': categories, 'request': request}

@register.inclusion_tag('homepage/banner.html', takes_context=True)
def homepage_banner(context):
    request = context.get('request')
    allowed_audiences = ['all']
    user = getattr(request, 'user', None)
    if user and user.is_authenticated:
        allowed_audiences.append('authenticated')
        if user.is_staff or user.is_superuser:
            allowed_audiences.append('staff')
        user_type = getattr(user, 'user_type', '')
        if user_type == 'customer':
            allowed_audiences.append('customers')
        elif user_type == 'vendor':
            allowed_audiences.append('vendors')
        elif user_type == 'manufacturer':
            allowed_audiences.append('manufacturers')
    else:
        allowed_audiences.append('guests')

    cache_key = f"homepage:banners:{','.join(sorted(allowed_audiences))}"

    def build_banners():
        banners = list(
            HomepageBanner.objects
            .filter(is_active=True, target_audience__in=allowed_audiences)
            .prefetch_related('uploaded_images')
            .order_by('display_order')
        )
        banners_json = []
        for banner in banners:
            active_images = [image for image in banner.uploaded_images.all() if image.is_active]
            banner.background_image = next((image for image in active_images if image.position == 'background'), None)
            banner.left_images = [image for image in active_images if image.position == 'left']
            banner.center_images = [image for image in active_images if image.position == 'center']
            banner.right_images = [image for image in active_images if image.position == 'right']
            banners_json.append({
                'id': banner.id,
                'title': banner.title,
                'subtitle': banner.subtitle,
                'button_text': banner.button_text,
                'button_url': banner.button_url,
                'target_audience': banner.target_audience,
                'background_color_start': banner.background_color_start,
                'background_color_end': banner.background_color_end,
                'left_image': banner.left_image or None,
                'right_image': banner.right_image or None,
                'center_image': banner.center_image or None,
                'left_animation': banner.left_animation,
                'right_animation': banner.right_animation,
                'center_animation': banner.center_animation,
            })
        return banners, json.dumps(banners_json, cls=DjangoJSONEncoder)

    banners, banners_json = local_get_or_set(cache_key, build_banners, HOMEPAGE_CACHE_TIMEOUT)
    return {
        'banners': banners,
        'banners_json': banners_json,
        'request': request
    }

@register.inclusion_tag('homepage/sections.html', takes_context=True)
def homepage_sections(context):
    request = context.get('request')
    def build_sections():
        sections = list(HomepageSection.objects.filter(is_active=True).order_by('display_order'))
        for section in sections:
            section.products = list(section.get_products())
        return sections

    sections = local_get_or_set('homepage:sections', build_sections, HOMEPAGE_CACHE_TIMEOUT)
    return {'sections': sections, 'request': request}

@register.inclusion_tag('homepage/vendor_carousel.html', takes_context=True)
def vendor_carousel(context):
    request = context.get('request')
    settings = local_get_or_set('homepage:vendor_settings', lambda: HomepageVendorSettings.objects.first(), HOMEPAGE_CACHE_TIMEOUT)
    if not settings or not settings.is_active:
        return {'vendors': [], 'settings': None, 'request': request}
    
    vendors = VendorProfile.objects.filter(is_verified=True, is_active=True)[:settings.vendor_count]
    vendors_list = list(vendors)
    random.shuffle(vendors_list)
    
    return {
        'vendors': vendors_list,
        'settings': settings,
        'request': request
    }

@register.inclusion_tag('homepage/newsletter.html', takes_context=True)
def newsletter_section(context):
    request = context.get('request')
    settings = local_get_or_set('homepage:newsletter_settings', lambda: HomepageNewsletterSettings.objects.first(), HOMEPAGE_CACHE_TIMEOUT)
    return {'settings': settings, 'request': request}

@register.inclusion_tag('homepage/manufacturers_section.html', takes_context=True)
def manufacturers_section(context):
    """Display manufacturers section on homepage"""
    request = context.get('request')
    def build_manufacturers_section():
        settings = HomepageManufacturerSettings.objects.first()
        if not settings or not settings.is_active:
            return None, [], []

        if settings.show_featured_only:
            manufacturers = list(Manufacturer.objects.filter(is_featured=True, is_active=True)[:settings.display_count])
        else:
            manufacturers = list(Manufacturer.objects.filter(is_active=True).order_by('-total_sales', '-rating_avg')[:settings.display_count])

        homepage_categories = (
            HomepageManufacturerCategory.objects
            .filter(is_active=True)
            .select_related('category')
            .order_by('display_order')
        )
        categories = [hc.category for hc in homepage_categories if hc.category and hc.category.is_active]
        return settings, manufacturers, categories

    settings, manufacturers, categories = local_get_or_set(
        'homepage:manufacturers_section',
        build_manufacturers_section,
        HOMEPAGE_CACHE_TIMEOUT,
    )
    if not settings:
        return {'show_section': False, 'request': request}
    
    return {
        'show_section': True,
        'settings': settings,
        'manufacturers': manufacturers,
        'categories': categories,
        'request': request
    }

@register.inclusion_tag('homepage/video_section.html', takes_context=True)
def video_section(context):
    """Display video section on homepage - FIXED for local videos"""
    request = context.get('request')
    existing_video_section = context.get('video_section')
    if existing_video_section:
        return {'video_section': existing_video_section, 'request': request}
    try:
        # Get active video section - NO YOUTUBE CONDITION
        video_section = local_get_or_set(
            'homepage:video_section',
            lambda: HomepageVideoSection.objects.filter(is_active=True).order_by('display_order').first(),
            HOMEPAGE_CACHE_TIMEOUT,
        )
        
        # Return video section regardless of source (local or YouTube)
        if video_section:
            return {'video_section': video_section, 'request': request}
    except Exception as e:
        print(f"Video section error: {e}")
    
    return {'video_section': None, 'request': request}
