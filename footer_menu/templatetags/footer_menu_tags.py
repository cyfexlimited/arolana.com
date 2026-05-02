from django import template
from footer_menu.models import FooterMenuCategory

register = template.Library()

@register.simple_tag
def get_footer_menus():
    """Get all active footer menu categories with their items"""
    try:
        categories = FooterMenuCategory.objects.filter(is_active=True).order_by('display_order')
        menus = []
        
        for category in categories:
            items = category.items.filter(is_active=True).order_by('display_order')
            if items.exists():
                menus.append({
                    'id': category.id,
                    'name': category.name,
                    'slug': category.slug,
                    'icon': category.icon,
                    'items': items
                })
        
        return menus
    except Exception as e:
        # Return empty list if there's an error
        return []
