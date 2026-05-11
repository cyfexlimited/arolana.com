from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.views.static import serve
from django.shortcuts import render
from django.http import HttpResponse
from core.views import debug_home, live_stats

# Import views
from pages.views import page_detail, help_center, faq_page, article_detail, careers_page
from products import views as products_views
import currency.views as currency_views
import core.views as core_views
from core import admin_views as core_admin_views
from accounts import views as accounts_views
from django.contrib.sitemaps.views import sitemap
from .sitemaps import StaticViewSitemap, ProductSitemap, CategorySitemap, VendorSitemap, BlogSitemap
from products.models import Product, Category
from vendors.models import VendorProfile

def sitemap_page(request):
    categories = Category.objects.filter(is_active=True, parent=None)[:20]
    products = Product.objects.filter(is_active=True)[:50]
    vendors = VendorProfile.objects.filter(is_verified=True, is_active=True)[:20]
    
    return render(request, 'pages/sitemap.html', {
        'categories': categories,
        'products': products,
        'vendors': vendors,
    })
    
sitemaps = {
    'static': StaticViewSitemap,
    'products': ProductSitemap,
    'categories': CategorySitemap,
    'vendors': VendorSitemap,
    'blog': BlogSitemap,
}

def home_view(request):
    """Custom home view with video section and proper context"""
    from homepage.models import HomepageVideoSection
    
    # Get active video section from database
    video_section = HomepageVideoSection.objects.filter(is_active=True).order_by('display_order').first()
    
    context = {
        'video_section': video_section,
    }
    return render(request, 'base/home.html', context)

def returns_redirect(request, path=None):
    """Redirect any /returns/* to the main returns page"""
    from django.shortcuts import redirect
    return redirect('returns')

def custom_404(request, exception):
    return render(request, '404.html', status=404)

def health_check(request):
    """Health check endpoint for Railway"""
    return HttpResponse("OK")

# CKEditor 5 URLs configuration
try:
    from django_ckeditor_5.views import upload_file, browse_files
    CKEDITOR_URLS = [
        re_path(r'^ckeditor5/upload/', upload_file, name='ck_editor_5_upload_file'),
        re_path(r'^ckeditor5/browse/', browse_files, name='ck_editor_5_browse_files'),
    ]
    print("✅ Using django_ckeditor_5 built-in views")
except ImportError:
    from ckeditor_views.views import upload_file, browse_files
    CKEDITOR_URLS = [
        re_path(r'^ckeditor5/upload/', upload_file, name='ck_editor_5_upload_file'),
        re_path(r'^ckeditor5/browse/', browse_files, name='ck_editor_5_browse_files'),
    ]
    print("⚠️ Using custom CKEditor views")

urlpatterns = [
    # Admin & Core
    path('admin/', admin.site.urls),
    path('admin/logo-check/', TemplateView.as_view(template_name='admin/logo_check.html'), name='logo_check'),
    path('admin/live-stats/', core_views.live_stats, name='live_stats'),
    path('admin/upload-logo/', core_admin_views.upload_logo, name='upload_logo'),
    path('admin/avatar-upload/<int:user_id>/', core_admin_views.upload_user_avatar, name='avatar_upload'),
    path('admin/avatar-delete/<int:user_id>/', core_admin_views.delete_user_avatar, name='avatar_delete'),
    
    # Homepage
    path('', home_view, name='home'),
    path('health/', health_check, name='health'),
    
    # Sitemap
    path('sitemap/', sitemap_page, name='sitemap'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    
    # Authentication
    path('accounts/', include('allauth.urls')),
    path('accounts/', include('accounts.urls')),
    
    # App URLs
    path('newsletter/', include('newsletter.urls')),
    path('vendors/', include('vendors.urls')),
    path('products/', include('products.urls')),
    path('orders/', include('orders.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('search/', include('search_ai.urls')),
    path('hero-banners/', include('hero_banners.urls')),
    path('ads/', include('ads.urls')),
    path('pages/', include('pages.urls')),
    path('manufacturers/', include('manufacturers.urls')),
    path('kyc/', include('kyc.urls')),
    path('chat/', include('chat.urls')),
    path('blog/', include('blog.urls')),
    path('currency/', include('currency.urls')),
    path('subscriptions/', include('subscriptions.urls')),
    path('videos/', include('videos.urls')),
    path('reports/', include('reports.urls')),
    path('notifications/', include('notifications.urls')),
    
    # Social Apps Status
    path('social-apps-status/', accounts_views.social_apps_status, name='social_apps_status'),
    
    # CKEditor 5
    *CKEDITOR_URLS,
    
    # Support Pages
    path('shipping/', TemplateView.as_view(template_name='support/shipping.html'), name='shipping'),
    path('youtube-embed-test/', TemplateView.as_view(template_name='youtube_embed_test.html'), name='youtube_embed_test'),
    path('support/', TemplateView.as_view(template_name='support/contact.html'), name='support'),
    path('contact/', TemplateView.as_view(template_name='support/contact.html'), name='contact'),
    path('about/', TemplateView.as_view(template_name='support/about.html'), name='about'),
    path('privacy/', TemplateView.as_view(template_name='support/privacy.html'), name='privacy'),
    path('terms/', TemplateView.as_view(template_name='support/terms.html'), name='terms'),
    path('returns/', TemplateView.as_view(template_name='support/returns.html'), name='returns'),
    re_path(r'^returns/.*$', returns_redirect, name='returns_catchall'),
    path('orders/track/', TemplateView.as_view(template_name='support/track_order.html'), name='track_order'),
    
    # Help & Debug
    path('color-test/', TemplateView.as_view(template_name='products/color_test.html'), name='color_test'),
    path('debug-colors/<int:product_id>/', products_views.debug_colors, name='debug_colors'),
    path('debug/', include('core.urls')),
    path('careers/', careers_page, name='careers'),
    path('help/', help_center, name='help_center'),
    path('faq/', faq_page, name='faq_page'),
    path('article/<slug:slug>/', article_detail, name='article_detail'),
    path('currency/diagnose/', currency_views.diagnose_currency, name='diagnose_currency'),
    
    # Test Pages
    path('ads-test/', TemplateView.as_view(template_name='ads/test.html'), name='ads_test'),
    path('image-test/', TemplateView.as_view(template_name='ads/direct_test.html'), name='image_test'),
    path('social-test/', TemplateView.as_view(template_name='socialaccount/test.html'), name='social_test'),
]

# Static and Media files serving (development only)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Custom 404 handler
handler404 = 'arolana_config.urls.custom_404'