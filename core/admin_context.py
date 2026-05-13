from datetime import datetime, timedelta
from django.db.models import Sum, Count
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
from django.contrib.sites.models import Site

def admin_context(request):
    """Comprehensive context processor for admin panel"""
    User = get_user_model()
    
    # Import models inside function to avoid circular imports at startup
    from products.models import Product
    from orders.models import Order
    from vendors.models import VendorProfile
    from ads.models import AdCampaign
    
    # Try to import notification models
    try:
        from notifications.models import Notification
        NOTIFICATIONS_AVAILABLE = True
    except ImportError:
        NOTIFICATIONS_AVAILABLE = False
    
    # Get date ranges
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Statistics
    stats = {
        'total_users': User.objects.count(),
        'total_vendors': VendorProfile.objects.filter(is_verified=True).count(),
        'pending_vendors': VendorProfile.objects.filter(is_verified=False).count(),
        'total_products': Product.objects.filter(is_active=True, approval_status='approved').count(),
        'pending_products': Product.objects.filter(approval_status='pending').count(),
        'total_orders': Order.objects.count(),
        'pending_orders': Order.objects.filter(status='pending').count(),
        'completed_orders': Order.objects.filter(status='delivered').count(),
        'total_revenue': float(Order.objects.filter(status='delivered').aggregate(total=Sum('total'))['total'] or 0),
        'revenue_this_month': float(Order.objects.filter(
            status='delivered',
            created_at__date__gte=month_ago
        ).aggregate(total=Sum('total'))['total'] or 0),
        'low_stock_products': Product.objects.filter(stock_quantity__lte=5, stock_quantity__gt=0, is_active=True, approval_status='approved').count(),
        'active_ads': AdCampaign.objects.filter(status='active', approved=True).count(),
    }
    
    # Chart data for last 30 days
    chart_labels = []
    chart_data = []
    
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        chart_labels.append(day.strftime('%b %d'))
        revenue = Order.objects.filter(
            created_at__date=day,
            status='delivered'
        ).aggregate(total=Sum('total'))['total'] or Decimal('0')
        chart_data.append(float(revenue))
    
    # Recent orders
    latest_orders = Order.objects.select_related('user').order_by('-created_at')[:10]
    
    # Top products
    top_products = Product.objects.filter(is_active=True, approval_status='approved').order_by('-sales_count')[:5]
    
    # Recent activities (if UserActivityLog exists)
    recent_activities = []
    try:
        from accounts.models import UserActivityLog
        recent_activities = UserActivityLog.objects.select_related('user').order_by('-timestamp')[:10]
    except:
        pass
    
    # Today's stats for header
    today_orders = Order.objects.filter(created_at__date=today).count()
    total_revenue_value = Order.objects.filter(status='delivered').aggregate(total=Sum('total'))['total'] or Decimal('0')
    
    # Notifications for current admin
    notification_count = 0
    recent_notifications = []
    has_unread = False
    
    if request.user.is_authenticated and request.user.is_staff and NOTIFICATIONS_AVAILABLE:
        try:
            notifications_qs = Notification.objects.filter(user=request.user).order_by('-created_at')
            notification_count = notifications_qs.filter(is_read=False).count()
            recent_notifications = list(notifications_qs[:10])
            has_unread = any(not notif.is_read for notif in recent_notifications)
        except Exception as e:
            print(f"Error loading notifications: {e}")
            notification_count = 0
            recent_notifications = []
            has_unread = False
    
    return {
        # Admin specific context
        'site_url': getattr(settings, 'SITE_URL', 'http://localhost:8000'),
        'admin_theme': 'darkly' if getattr(settings, 'DEBUG', True) else 'lightly',
        'debug_mode': settings.DEBUG,
        
        # Admin stats
        'admin_stats': stats,
        'latest_orders': latest_orders,
        'top_products': top_products,
        'recent_activities': recent_activities,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        
        # Header stats
        'debug': settings.DEBUG,
        'today_orders': today_orders,
        'total_revenue': f"${total_revenue_value:,.2f}",
        
        # Notifications
        'recent_notifications': recent_notifications,
        'has_unread': has_unread,
        'notification_count': notification_count,
        
        # Additional context
        'current_date': today.strftime('%B %d, %Y'),
        'site_name': 'Arolana',
        'admin_pending_count': stats['pending_vendors'] + stats['pending_orders'] + stats['pending_products'],
    }

def admin_notifications(request):
    """Admin notifications context (legacy compatibility)"""
    return admin_context(request)