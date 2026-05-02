from django import template
from django.db.models import Sum, Count
from datetime import datetime, timedelta
from accounts.models import User
from products.models import Product
from orders.models import Order
from vendors.models import VendorProfile

register = template.Library()

@register.simple_tag
def get_admin_stats():
    """Get statistics for admin dashboard"""
    today = datetime.now().date()
    week_ago = today - timedelta(days=7)
    
    return {
        'total_users': User.objects.count(),
        'total_vendors': User.objects.filter(user_type='vendor').count(),
        'total_products': Product.objects.count(),
        'total_orders': Order.objects.count(),
        'pending_orders': Order.objects.filter(status='pending').count(),
        'pending_vendors': VendorProfile.objects.filter(is_verified=False).count(),
        'revenue_today': Order.objects.filter(
            created_at__date=today,
            status='delivered'
        ).aggregate(total=Sum('total'))['total'] or 0,
        'revenue_week': Order.objects.filter(
            created_at__date__gte=week_ago,
            status='delivered'
        ).aggregate(total=Sum('total'))['total'] or 0,
    }
