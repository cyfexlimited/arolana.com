from django.db.models import Prefetch
from core.local_cache import local_get_or_set

from .models import FooterMenuCategory, FooterMenuItem

def footer_menus(request):
    """Provide footer menu categories and items to all templates"""
    def build_menus():
        categories = FooterMenuCategory.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                'items',
                queryset=FooterMenuItem.objects.filter(is_active=True).order_by('display_order', 'title'),
                to_attr='active_items',
            )
        )

        menus = {}
        for category in categories:
            if category.active_items:
                menus[category.slug] = {
                    'name': category.name,
                    'icon': category.icon,
                    'items': category.active_items,
                }
        return menus

    menus = local_get_or_set('footer_menu:menus_by_slug', build_menus, 300)
    
    return {
        'footer_menus': menus,
    }
