from django import template
from django.db.models import Sum, Count
from datetime import datetime, timedelta
from django.contrib.auth import get_user_model
from products.models import Product
from orders.models import Order
from vendors.models import VendorProfile

register = template.Library()

@register.simple_tag
def get_admin_stats():
    """Get statistics for admin dashboard"""
    User = get_user_model()
    
    return {
        'total_users': User.objects.count(),
        'total_vendors': VendorProfile.objects.filter(is_verified=True).count(),
        'pending_vendors': VendorProfile.objects.filter(is_verified=False).count(),
        'total_products': Product.objects.filter(is_active=True, approval_status="approved").count(),
        'pending_products': Product.objects.filter(approval_status="pending").count(),
        'total_orders': Order.objects.count(),
        'pending_orders': Order.objects.filter(status='pending').count(),
        'completed_orders': Order.objects.filter(status='delivered').count(),
        'total_revenue': float(Order.objects.filter(status='delivered').aggregate(total=Sum('total'))['total'] or 0),
    }

@register.simple_tag
def get_chart_data():
    """Get chart data for last 7 days"""
    today = datetime.now().date()
    chart_labels = []
    chart_data = []
    
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        chart_labels.append(day.strftime('%b %d'))
        revenue = Order.objects.filter(
            created_at__date=day,
            status='delivered'
        ).aggregate(total=Sum('total'))['total'] or 0
        chart_data.append(float(revenue))
    
    return {
        'labels': chart_labels,
        'data': chart_data,
    }

@register.simple_tag
def get_latest_orders(limit=5):
    """Get latest orders"""
    return Order.objects.select_related('user').order_by('-created_at')[:limit]

@register.simple_tag
def get_latest_products(limit=5):
    """Get latest products"""
    return Product.objects.filter(approval_status="approved").select_related('category', 'vendor').order_by('-created_at')[:limit]

@register.simple_tag
def get_latest_users(limit=5):
    """Get latest users"""
    User = get_user_model()
    return User.objects.order_by('-date_joined')[:limit]
