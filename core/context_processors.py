from core.models import SiteSettings
from products.models import Category, Product
from vendors.models import VendorProfile
from manufacturers.models import Manufacturer, ManufacturerCategory
from django.db.models import Q
import random
from django.conf import settings

def global_context(request):
    """Global context for all templates"""
    # Get or create site settings
    site_settings = SiteSettings.objects.first()
    if not site_settings:
        site_settings = SiteSettings.objects.create()
    
    # Get featured products (limit to 8)
    featured_products = Product.objects.filter(is_featured=True, is_active=True)[:8]
    
    # Get verified vendors and SHUFFLE them for variety
    vendors = list(VendorProfile.objects.filter(is_verified=True, is_active=True))
    random.shuffle(vendors)
    vendors = vendors[:4]
    
    # Get ALL top-level categories for mega menu
    main_categories = Category.objects.filter(parent=None, is_active=True).order_by('order', 'name')
    
    # Top rated vendors for mega menu dropdown
    top_vendors = VendorProfile.objects.filter(is_verified=True, is_active=True).order_by('-rating_avg')[:5]
    
    # Trending vendors for mega menu dropdown
    trending_vendors = VendorProfile.objects.filter(is_verified=True, is_active=True).order_by('-total_sales')[:5]
    
    # Get manufacturer categories for mega menu and homepage
    manufacturer_categories = ManufacturerCategory.objects.filter(is_active=True).order_by('display_order', 'name')
    
    # Get featured manufacturers
    featured_manufacturers = Manufacturer.objects.filter(is_featured=True, is_active=True)[:4]
    
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