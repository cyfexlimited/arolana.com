from core.models import SiteSettings
from django.db.models import Count, Prefetch, Q, Sum
from products.models import Category, Product
from vendors.models import VendorProfile
from manufacturers.models import Manufacturer, ManufacturerCategory
from currency.models import Currency
import random
from django.conf import settings
from core.local_cache import local_get_or_set


GLOBAL_CONTEXT_CACHE_TIMEOUT = 300


def _cached(key, builder, timeout=GLOBAL_CONTEXT_CACHE_TIMEOUT):
    return local_get_or_set(key, builder, timeout)


def _main_categories():
    grandchild_queryset = Category.objects.filter(is_active=True).order_by('order', 'name')
    child_queryset = (
        Category.objects
        .filter(is_active=True)
        .annotate(active_child_count=Count('children', filter=Q(children__is_active=True)))
        .prefetch_related(Prefetch('children', queryset=grandchild_queryset))
        .order_by('order', 'name')
    )
    return list(
        Category.objects
        .filter(parent=None, is_active=True)
        .annotate(active_child_count=Count('children', filter=Q(children__is_active=True)))
        .prefetch_related(Prefetch('children', queryset=child_queryset))
        .order_by('order', 'name')
    )

def global_context(request):
    """Global context for all templates"""
    def build_site_settings():
        site_settings = SiteSettings.objects.first()
        if not site_settings:
            site_settings = SiteSettings.objects.create()
        return site_settings

    site_settings = _cached('global_context:site_settings', build_site_settings)
    
    # Get featured products (limit to 8)
    featured_products = _cached(
        'global_context:featured_products',
        lambda: list(
            Product.objects
            .filter(is_featured=True, is_active=True, approval_status='approved')
            .select_related('category', 'brand')
            .order_by('-created_at')[:8]
        ),
    )
    
    # Get verified vendors and SHUFFLE them for variety
    vendors = _cached(
        'global_context:verified_vendors',
        lambda: list(VendorProfile.objects.filter(is_verified=True, is_active=True)),
    )
    vendors = list(vendors)
    random.shuffle(vendors)
    vendors = vendors[:4]
    
    # Get ALL top-level categories for mega menu
    main_categories = _cached('global_context:main_categories', _main_categories)
    
    # Top rated vendors for mega menu dropdown
    top_vendors = _cached(
        'global_context:top_vendors',
        lambda: list(VendorProfile.objects.filter(is_verified=True, is_active=True).order_by('-rating_avg')[:5]),
    )
    
    # Trending vendors for mega menu dropdown
    trending_vendors = _cached(
        'global_context:trending_vendors',
        lambda: list(VendorProfile.objects.filter(is_verified=True, is_active=True).order_by('-total_sales')[:5]),
    )
    
    # Get manufacturer categories for mega menu and homepage
    manufacturer_categories = _cached(
        'global_context:manufacturer_categories',
        lambda: list(ManufacturerCategory.objects.filter(is_active=True).order_by('display_order', 'name')),
    )
    
    # Get featured manufacturers
    featured_manufacturers = _cached(
        'global_context:featured_manufacturers',
        lambda: list(Manufacturer.objects.filter(is_featured=True, is_active=True)[:4]),
    )

    active_currencies = _cached(
        'global_context:active_currencies',
        lambda: list(Currency.objects.filter(is_active=True).order_by('code')),
        3600,
    )
    
    notification_unread_count = 0
    recent_user_notifications = []
    chat_unread_count = 0
    if request.user.is_authenticated:
        try:
            from notifications.models import Notification
            user_notifications = Notification.objects.filter(user=request.user, is_archived=False)
            notification_unread_count = user_notifications.filter(is_read=False).count()
            recent_user_notifications = list(user_notifications.order_by('-created_at')[:5])
        except Exception:
            notification_unread_count = 0
            recent_user_notifications = []
        try:
            from chat.models import ChatRoom, VendorChatRoom
            direct_unread = 0
            for room in ChatRoom.objects.filter(participants=request.user, is_active=True):
                direct_unread += room.get_unread_count(request.user)
            vendor_unread = VendorChatRoom.objects.filter(customer=request.user, is_active=True).aggregate(total=Sum('customer_unread'))['total'] or 0
            seller_unread = VendorChatRoom.objects.filter(vendor=request.user, is_active=True).aggregate(total=Sum('vendor_unread'))['total'] or 0
            chat_unread_count = direct_unread + vendor_unread + seller_unread
        except Exception:
            chat_unread_count = 0

    return {
        'site_settings': site_settings,
        'featured_products': featured_products,
        'vendors': vendors,
        'main_categories': main_categories,
        'top_vendors': top_vendors,
        'trending_vendors': trending_vendors,
        'manufacturer_categories': manufacturer_categories,
        'featured_manufacturers': featured_manufacturers,
        'DEBUG': settings.DEBUG,
        'SITE_URL': getattr(settings, 'SITE_URL', 'http://localhost:8000'),
        'notification_unread_count': notification_unread_count,
        'recent_user_notifications': recent_user_notifications,
        'chat_unread_count': chat_unread_count,
        'all_currencies': active_currencies,
        'current_currency_code': request.session.get('user_currency') or request.COOKIES.get('user_currency') or 'USD',
        'currency_source': request.session.get('user_currency_source', 'auto'),
    }

def admin_notifications(request):
    """Admin notifications context processor - single definition"""
    from orders.models import Order
    from vendors.models import VendorProfile
    from notifications.models import Notification
    
    if request.user.is_authenticated and request.user.is_staff:
        # Pending counts
        pending_orders = Order.objects.filter(status='pending').count()
        pending_vendors = VendorProfile.objects.filter(is_verified=False).count()
        
        # Notifications
        notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:10]
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
        
        return {
            'admin_notifications': {
                'pending_orders': pending_orders,
                'pending_vendors': pending_vendors,
                'total_pending': pending_orders + pending_vendors,
            },
            'recent_notifications': notifications,
            'admin_notification_count': unread_count,
            'has_unread_notifications': unread_count > 0,
        }
    return {
        'admin_notifications': {
            'pending_orders': 0,
            'pending_vendors': 0,
            'total_pending': 0,
        },
        'recent_notifications': [],
        'admin_notification_count': 0,
        'has_unread_notifications': False,
    }
