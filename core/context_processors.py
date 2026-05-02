from core.models import SiteSettings
from products.models import Category, Product
from vendors.models import VendorProfile
from manufacturers.models import Manufacturer, ManufacturerCategory
import random
from notifications.models import Notification

def global_context(request):
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
    }

def admin_notifications(request):
    """Context processor for admin notifications"""
    if request.user.is_authenticated and request.user.is_staff:
        notifications = Notification.objects.filter(user=request.user)[:10]
        return {
            'recent_notifications': notifications,
            'admin_notification_count': Notification.objects.filter(user=request.user, is_read=False).count(),
        }
    return {}