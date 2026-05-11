from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.views.static import serve
from django.shortcuts import render
<<<<<<< HEAD
from django.views.decorators.csrf import csrf_exempt
from core.views import debug_home, live_stats
=======

>>>>>>> 02fdd334c4e232c6c016f4ea5d841012f0c6332b
# Import views
from pages.views import page_detail, help_center, faq_page, article_detail, careers_page
from products import views as products_views
import currency.views as currency_views
import core.views as core_views
from core import admin_views as core_admin_views
from accounts import views as accounts_views
from django.contrib.sitemaps.views import sitemap
from .sitemaps import StaticViewSitemap, ProductSitemap, CategorySitemap, VendorSitemap, BlogSitemap
from django.shortcuts import render
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


# =========================================================
# CORE VIEWS
# =========================================================
def home_view(request):
<<<<<<< HEAD
    """Custom home view with video section and proper context"""
    from homepage.models import HomepageVideoSection
    
    # Get active video section from database
    video_section = HomepageVideoSection.objects.filter(is_active=True).order_by('display_order').first()
    
    context = {
        'video_section': video_section,
    }
    return render(request, 'base/home.html', context)
    
=======
    return render(request, 'base/home.html', {})


>>>>>>> 02fdd334c4e232c6c016f4ea5d841012f0c6332b
def returns_redirect(request, path=None):
    from django.shortcuts import redirect
    return redirect('returns')


def custom_404(request, exception):
    return render(request, '404.html', status=404)


# =========================================================
# CKEDITOR CONFIG
# =========================================================
try:
    from django_ckeditor_5.views import upload_file, browse_files
    CKEDITOR_URLS = [
        re_path(r'^ckeditor5/upload/', upload_file, name='ck_editor_5_upload_file'),
        re_path(r'^ckeditor5/browse/', browse_files, name='ck_editor_5_browse_files'),
    ]
except ImportError:
    from ckeditor_views.views import upload_file, browse_files
    CKEDITOR_URLS = [
        re_path(r'^ckeditor5/upload/', upload_file, name='ck_editor_5_upload_file'),
        re_path(r'^ckeditor5/browse/', browse_files, name='ck_editor_5_browse_files'),
    ]


# =========================================================
# URL PATTERNS
# =========================================================
urlpatterns = [
    # ---------------- ADMIN ----------------
    path('admin/', admin.site.urls),
    path('admin/logo-check/', TemplateView.as_view(template_name='admin/logo_check.html')),
    path('admin/live-stats/', core_views.live_stats),
    path('admin/upload-logo/', core_admin_views.upload_logo),
    path('admin/avatar-upload/<int:user_id>/', core_admin_views.upload_user_avatar),
    path('admin/avatar-delete/<int:user_id>/', core_admin_views.delete_user_avatar),

    # ---------------- HOME ----------------
    path('', home_view, name='home'),
<<<<<<< HEAD
    
    # Sitemap
    path('sitemap/', sitemap_page, name='sitemap'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    
    # Authentication - Allauth handles core auth (login, logout, signup, password reset, social)
    path('accounts/', include('allauth.urls')),
    
    # Custom account URLs
=======

    # ---------------- AUTH ----------------
    # FIXED: avoid conflict between accounts apps
>>>>>>> 02fdd334c4e232c6c016f4ea5d841012f0c6332b
    path('accounts/', include('accounts.urls')),
    path('auth/', include('allauth.urls')),

    # ---------------- APPS ----------------
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

    # ---------------- SOCIAL ----------------
    path('social-apps-status/', accounts_views.social_apps_status),

    # ---------------- CKEDITOR ----------------
    *CKEDITOR_URLS,

    # ---------------- SUPPORT PAGES ----------------
    path('shipping/', TemplateView.as_view(template_name='support/shipping.html')),
    path('support/', TemplateView.as_view(template_name='support/contact.html')),
    path('contact/', TemplateView.as_view(template_name='support/contact.html')),
    path('about/', TemplateView.as_view(template_name='support/about.html')),
    path('privacy/', TemplateView.as_view(template_name='support/privacy.html')),
    path('terms/', TemplateView.as_view(template_name='support/terms.html')),
    path('returns/', TemplateView.as_view(template_name='support/returns.html')),
    re_path(r'^returns/.+$', returns_redirect),

    # ---------------- HELP ----------------
    path('careers/', careers_page),
    path('help/', help_center),
    path('faq/', faq_page),
    path('article/<slug:slug>/', article_detail),
    path('currency/diagnose/', currency_views.diagnose_currency),

    # ---------------- TEST ----------------
    path('ads-test/', TemplateView.as_view(template_name='ads/test.html')),
    path('image-test/', TemplateView.as_view(template_name='ads/direct_test.html')),
    path('social-test/', TemplateView.as_view(template_name='socialaccount/test.html')),
]


# =========================================================
# STATIC / MEDIA
# =========================================================
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]


# =========================================================
# ERROR HANDLER
# =========================================================
handler404 = 'arolana_config.urls.custom_404'