from django import template
from django.db.models import Prefetch
from core.local_cache import local_get_or_set

from footer_menu.models import FooterMenuCategory, FooterMenuItem

register = template.Library()

@register.simple_tag
def get_footer_menus():
    """Get all active footer menu categories with their items"""
    def build_menus():
        categories = FooterMenuCategory.objects.filter(is_active=True).order_by('display_order').prefetch_related(
            Prefetch(
                'items',
                queryset=FooterMenuItem.objects.filter(is_active=True).order_by('display_order', 'title'),
                to_attr='active_items',
            )
        )
        menus = []

        for category in categories:
            if category.active_items:
                menus.append({
                    'id': category.id,
                    'name': category.name,
                    'slug': category.slug,
                    'icon': category.icon,
                    'items': category.active_items,
                })

        return menus

    return local_get_or_set('footer_menu:menus', build_menus, 300)
