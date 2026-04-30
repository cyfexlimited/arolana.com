from .models import FooterMenuCategory

def footer_menus(request):
    """Provide footer menu categories and items to all templates"""
    categories = FooterMenuCategory.objects.filter(is_active=True).prefetch_related('items')
    
    # Build menu structure
    menus = {}
    for category in categories:
        items = category.items.filter(is_active=True).order_by('display_order')
        if items.exists():
            menus[category.slug] = {
                'name': category.name,
                'icon': category.icon,
                'items': items
            }
    
    return {
        'footer_menus': menus,
    }
