import json
from datetime import timedelta
from django.db.models import F, Q, Sum
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
from core.local_cache import local_get_or_set


def _build_admin_sidebar_badges(user, stats, notification_count):
    """Small cached counts for Jazzmin sidebar badges."""

    def build():
        badges = {}

        def add(label, count, title="", href_contains=None):
            count = int(count or 0)
            if count <= 0:
                return
            badges[label.lower()] = {
                "label": label,
                "count": count,
                "title": title or f"{count} item(s) need attention",
                "href_contains": href_contains or [],
            }

        category_alerts = 0
        vendor_alerts = stats.get("pending_vendors", 0)
        chat_alerts = 0
        smartchat_alerts = 0
        kyc_alerts = 0

        try:
            from products.models import Category
            category_alerts = Category.objects.filter(
                is_active=True,
            ).filter(
                Q(image="") | Q(image__isnull=True) | Q(background_image="") | Q(background_image__isnull=True)
            ).count()
        except Exception:
            category_alerts = 0

        try:
            from chat.models import ChatNotification, VendorChatRoom
            chat_alerts = (
                ChatNotification.objects.filter(user=user, is_read=False).count()
                + VendorChatRoom.objects.filter(is_active=True, vendor_unread__gt=0).count()
            )
        except Exception:
            chat_alerts = 0

        try:
            from smartchat.models import AIMessage, HumanTakeoverRequest
            smartchat_alerts = (
                AIMessage.objects.filter(is_read_by_admin=False).exclude(sender_type="admin").count()
                + HumanTakeoverRequest.objects.exclude(status__in=["resolved", "cancelled"]).count()
            )
        except Exception:
            smartchat_alerts = 0

        try:
            from kyc.models import KYCSubmission
            kyc_alerts = KYCSubmission.objects.filter(status="pending").count()
        except Exception:
            kyc_alerts = 0

        add("Products", stats.get("pending_products", 0) + stats.get("low_stock_products", 0) + stats.get("out_of_stock_products", 0), "Products waiting, low stock, or out of stock", ["/products/product/"])
        add("Categories", category_alerts, "Categories/subcategories missing thumbnail or hero image", ["/products/category/"])
        add("Orders", stats.get("pending_orders", 0), "Pending orders", ["/orders/order/"])
        add("Vendors", vendor_alerts, "Vendors waiting for verification", ["/vendors/vendorprofile/"])
        add("Notifications", notification_count, "Unread admin notifications", ["/notifications/notification/"])
        add("Chat", chat_alerts, "Unread chat messages", ["/chat/"])
        add("KYC", kyc_alerts, "KYC submissions waiting for review", ["/kyc/"])
        add("Arolana Smart Chat", smartchat_alerts, "Smart Chat messages or human takeover requests need attention", ["/smartchat/"])

        return badges

    return local_get_or_set(f"admin-sidebar-badges:{user.id}", build, 60)

def admin_context(request):
    """Comprehensive context processor for admin panel"""
    if not getattr(request, 'path', '').startswith('/admin'):
        return {}

    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated or not user.is_staff:
        return {}

    is_dashboard_view = request.path.rstrip('/') in {'/admin', ''}

    User = get_user_model()
    admin_appearance = None
    site_settings = None
    try:
        from core.models import AdminAppearance, SiteSettings
        admin_appearance = AdminAppearance.objects.filter(is_active=True).first()
        site_settings = SiteSettings.objects.first()
    except Exception:
        admin_appearance = None
        site_settings = None
    
    # Import models inside function to avoid circular imports at startup
    from products.models import Product, ProductVariant
    from orders.models import Order
    from vendors.models import VendorProfile

    try:
        from manufacturers.models import Manufacturer
    except Exception:
        Manufacturer = None

    try:
        from ads.models import AdCampaign
    except Exception:
        AdCampaign = None
    
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
    
    active_products = Product.objects.filter(is_active=True)
    approved_products = active_products.filter(approval_status='approved')
    low_stock_qs = active_products.filter(
        stock_quantity__gt=0,
        stock_quantity__lte=F('low_stock_threshold'),
    )
    out_of_stock_qs = active_products.filter(stock_quantity__lte=0)
    pending_products_qs = Product.objects.filter(approval_status='pending')
    vendor_pending_qs = VendorProfile.objects.filter(is_verified=False)

    inventory_totals = Product.objects.aggregate(
        total_units=Sum('stock_quantity'),
        reserved_units=Sum('reserved_quantity'),
    )
    total_units = inventory_totals['total_units'] or 0
    reserved_units = inventory_totals['reserved_units'] or 0
    available_units = max(0, total_units - reserved_units)
    total_active_products = active_products.count()
    healthy_products = max(0, total_active_products - low_stock_qs.count() - out_of_stock_qs.count())
    inventory_health_percent = round((healthy_products / total_active_products) * 100) if total_active_products else 100

    active_ads_count = 0
    if AdCampaign:
        active_ads_count = AdCampaign.objects.filter(status='active', approved=True).count()

    manufacturer_count = Manufacturer.objects.filter(is_active=True).count() if Manufacturer else 0

    # Statistics
    stats = {
        'total_users': User.objects.count(),
        'total_vendors': VendorProfile.objects.filter(is_verified=True).count(),
        'pending_vendors': vendor_pending_qs.count(),
        'total_manufacturers': manufacturer_count,
        'total_products': approved_products.count(),
        'pending_products': pending_products_qs.count(),
        'total_orders': Order.objects.count(),
        'pending_orders': Order.objects.filter(status='pending').count(),
        'completed_orders': Order.objects.filter(status='delivered').count(),
        'total_revenue': float(Order.objects.filter(status='delivered').aggregate(total=Sum('total'))['total'] or 0),
        'revenue_this_month': float(Order.objects.filter(
            status='delivered',
            created_at__date__gte=month_ago
        ).aggregate(total=Sum('total'))['total'] or 0),
        'low_stock_products': low_stock_qs.count(),
        'out_of_stock_products': out_of_stock_qs.count(),
        'total_variants': ProductVariant.objects.count(),
        'low_stock_variants': ProductVariant.objects.filter(is_active=True, stock_quantity__lte=5, stock_quantity__gt=0).count(),
        'active_ads': active_ads_count,
        'inventory_units': total_units,
        'available_units': available_units,
        'reserved_units': reserved_units,
        'inventory_health_percent': inventory_health_percent,
    }
    
    chart_labels = []
    chart_data = []
    latest_orders = []
    latest_users = []
    top_products = []
    low_stock_items = []
    out_of_stock_items = []
    pending_product_list = []
    pending_vendor_profiles = []

    if is_dashboard_view:
        for i in range(29, -1, -1):
            day = today - timedelta(days=i)
            chart_labels.append(day.strftime('%b %d'))
            revenue = Order.objects.filter(
                created_at__date=day,
                status='delivered'
            ).aggregate(total=Sum('total'))['total'] or Decimal('0')
            chart_data.append(float(revenue))

        latest_orders = Order.objects.select_related('user').order_by('-created_at')[:10]
        latest_users = User.objects.order_by('-date_joined')[:8]
        top_products = approved_products.order_by('-sales_count')[:6]
        low_stock_items = low_stock_qs.select_related('category', 'brand', 'vendor').order_by('stock_quantity', 'name')[:8]
        out_of_stock_items = out_of_stock_qs.select_related('category', 'brand', 'vendor').order_by('name')[:6]
        pending_product_list = pending_products_qs.select_related('category', 'brand', 'vendor').order_by('-submitted_for_review_at')[:8]
        pending_vendor_profiles = vendor_pending_qs.select_related('user').order_by('-created_at')[:6]
    
    # Recent activities (if UserActivityLog exists)
    recent_activities = []
    if is_dashboard_view:
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
            recent_notifications = list(notifications_qs[:8])
            has_unread = any(not notif.is_read for notif in recent_notifications)
        except Exception as e:
            print(f"Error loading notifications: {e}")
            notification_count = 0
            recent_notifications = []
            has_unread = False
    
    admin_alerts = []
    if stats['pending_products']:
        admin_alerts.append({
            'level': 'warning',
            'icon': 'fas fa-clock',
            'title': 'Products waiting for approval',
            'message': f"{stats['pending_products']} product(s) need review before they go live.",
            'url': '/admin/products/product/?approval_status__exact=pending',
            'label': 'Review products',
        })
    if stats['pending_vendors']:
        admin_alerts.append({
            'level': 'info',
            'icon': 'fas fa-id-card',
            'title': 'Vendor verification pending',
            'message': f"{stats['pending_vendors']} vendor profile(s) are waiting for verification.",
            'url': '/admin/vendors/vendorprofile/?is_verified__exact=0',
            'label': 'Verify vendors',
        })
    if stats['low_stock_products'] or stats['out_of_stock_products']:
        admin_alerts.append({
            'level': 'danger',
            'icon': 'fas fa-box-open',
            'title': 'Inventory needs attention',
            'message': f"{stats['low_stock_products']} low-stock and {stats['out_of_stock_products']} out-of-stock product(s).",
            'url': '/admin/products/product/',
            'label': 'Open inventory',
        })
    if notification_count:
        admin_alerts.append({
            'level': 'primary',
            'icon': 'fas fa-bell',
            'title': 'Unread admin notifications',
            'message': f"{notification_count} unread notification(s) in your message center.",
            'url': '/admin/notifications/notification/?is_read__exact=0',
            'label': 'Read notifications',
        })

    admin_sidebar_badges = _build_admin_sidebar_badges(request.user, stats, notification_count)

    return {
        # Admin specific context
        'site_url': getattr(settings, 'SITE_URL', 'http://localhost:8000'),
        'admin_theme': 'darkly' if getattr(settings, 'DEBUG', True) else 'lightly',
        'debug_mode': settings.DEBUG,
        
        # Admin stats
        'admin_stats': stats,
        'latest_orders': latest_orders,
        'latest_users': latest_users,
        'top_products': top_products,
        'low_stock_items': low_stock_items,
        'out_of_stock_items': out_of_stock_items,
        'pending_product_list': pending_product_list,
        'pending_vendor_profiles': pending_vendor_profiles,
        'admin_alerts': admin_alerts,
        'recent_activities': recent_activities,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'chart_labels_json': json.dumps(chart_labels),
        'chart_data_json': json.dumps(chart_data),
        
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
        'site_name': site_settings.site_name if site_settings else 'Arolana',
        'site_settings': site_settings,
        'admin_appearance': admin_appearance,
        'admin_pending_count': stats['pending_vendors'] + stats['pending_orders'] + stats['pending_products'] + stats['low_stock_products'],
        'admin_sidebar_badges': admin_sidebar_badges,
        'admin_sidebar_badges_json': json.dumps(admin_sidebar_badges),
    }

def admin_notifications(request):
    """Admin notifications context (legacy compatibility)"""
    return admin_context(request)
