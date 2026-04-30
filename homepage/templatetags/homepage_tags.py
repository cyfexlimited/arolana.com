from django import template
from django.core.serializers.json import DjangoJSONEncoder
from homepage.models import (
    HomepageCategory, HomepageBanner, HomepageSection, 
    HomepageVendorSettings, HomepageNewsletterSettings, 
    HomepageManufacturerSettings, HomepageManufacturerCategory,
    HomepageVideoSection
)
from vendors.models import VendorProfile
from products.models import Product
from manufacturers.models import Manufacturer
import random
import json

register = template.Library()

@register.inclusion_tag('homepage/categories.html', takes_context=True)
def homepage_categories(context):
    request = context.get('request')
    categories = HomepageCategory.objects.filter(is_active=True).select_related('category').order_by('display_order')
    return {'categories': categories, 'request': request}

@register.inclusion_tag('homepage/banner.html', takes_context=True)
def homepage_banner(context):
    request = context.get('request')
    banners = HomepageBanner.objects.filter(is_active=True).order_by('display_order')
    banners_json = []
    for banner in banners:
        banners_json.append({
            'id': banner.id,
            'title': banner.title,
            'subtitle': banner.subtitle,
            'button_text': banner.button_text,
            'button_url': banner.button_url,
            'background_color_start': banner.background_color_start,
            'background_color_end': banner.background_color_end,
            'left_image': banner.left_image.url if banner.left_image else None,
            'right_image': banner.right_image.url if banner.right_image else None,
            'center_image': banner.center_image.url if banner.center_image else None,
            'left_animation': banner.left_animation,
            'right_animation': banner.right_animation,
            'center_animation': banner.center_animation,
        })
    return {
        'banners': banners,
        'banners_json': json.dumps(banners_json, cls=DjangoJSONEncoder),
        'request': request
    }

@register.inclusion_tag('homepage/sections.html', takes_context=True)
def homepage_sections(context):
    request = context.get('request')
    sections = HomepageSection.objects.filter(is_active=True).order_by('display_order')
    return {'sections': sections, 'request': request}

@register.inclusion_tag('homepage/vendor_carousel.html', takes_context=True)
def vendor_carousel(context):
    request = context.get('request')
    settings = HomepageVendorSettings.objects.first()
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
    settings = HomepageNewsletterSettings.objects.first()
    return {'settings': settings, 'request': request}

@register.inclusion_tag('homepage/manufacturers_section.html', takes_context=True)
def manufacturers_section(context):
    """Display manufacturers section on homepage"""
    request = context.get('request')
    settings = HomepageManufacturerSettings.objects.first()
    if not settings or not settings.is_active:
        return {'show_section': False, 'request': request}
    
    # Get manufacturers
    if settings.show_featured_only:
        manufacturers = Manufacturer.objects.filter(is_featured=True, is_active=True)[:settings.display_count]
    else:
        manufacturers = Manufacturer.objects.filter(is_active=True).order_by('-total_sales', '-rating_avg')[:settings.display_count]
    
    # Get categories for display
    homepage_categories = HomepageManufacturerCategory.objects.filter(is_active=True).order_by('display_order')
    categories = [hc.category for hc in homepage_categories if hc.category.is_active]
    
    return {
        'show_section': True,
        'settings': settings,
        'manufacturers': manufacturers,
        'categories': categories,
        'request': request
    }

@register.inclusion_tag('homepage/video_section.html', takes_context=True)
def video_section(context):
    """Display video section on homepage with smooth animations"""
    request = context.get('request')
    try:
        video_section = HomepageVideoSection.objects.filter(is_active=True).order_by('display_order').first()
        if video_section and video_section.youtube_id:
            return {'video_section': video_section, 'request': request}
    except Exception as e:
        print(f"Video section error: {e}")
    return {'video_section': None, 'request': request}