from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.shortcuts import render
from pages.views import page_detail, help_center, faq_page, article_detail, careers_page
from products import views as products_views
import currency.views as currency_views
import core.views as core_views
from core import admin_views as core_admin_views  # This is the correct import

def home_view(request):
    """Custom home view that ensures request is in template context"""
    return render(request, 'base/home.html', {})

def returns_redirect(request, path=None):
    """Redirect any /returns/* to the main returns page"""
    from django.shortcuts import redirect
    return redirect('returns')

urlpatterns = [
    path('admin/logo-check/', TemplateView.as_view(template_name='admin/logo_check.html'), name='logo_check'),
    path('', home_view, name='home'),
    path('admin/', admin.site.urls),
    path('newsletter/', include('newsletter.urls')),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('allauth.urls')),
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
    path('shipping/', TemplateView.as_view(template_name='support/shipping.html'), name='shipping'),
    path('currency/', include('currency.urls')),
    path('youtube-embed-test/', TemplateView.as_view(template_name='youtube_embed_test.html'), name='youtube_embed_test'),
    path('currency/diagnose/', currency_views.diagnose_currency, name='diagnose_currency'),
    path('reports/', include('reports.urls')),
    path('notifications/', include('notifications.urls')),

    # Support Pages
    path('support/', TemplateView.as_view(template_name='support/contact.html'), name='support'),
    path('contact/', TemplateView.as_view(template_name='support/contact.html'), name='contact'),
    path('about/', TemplateView.as_view(template_name='support/about.html'), name='about'),
    path('privacy/', TemplateView.as_view(template_name='support/privacy.html'), name='privacy'),
    path('terms/', TemplateView.as_view(template_name='support/terms.html'), name='terms'),
    path('returns/', TemplateView.as_view(template_name='support/returns.html'), name='returns'),
    re_path(r'^returns/.*$', returns_redirect, name='returns_catchall'),
    path('orders/track/', TemplateView.as_view(template_name='support/track_order.html'), name='track_order'),
    path('subscriptions/', include('subscriptions.urls')),
    path('videos/', include('videos.urls')),
    path('color-test/', TemplateView.as_view(template_name='products/color_test.html'), name='color_test'),
    path('debug-colors/<int:product_id>/', products_views.debug_colors, name='debug_colors'),
    path('debug/', include('core.urls')),
    path('careers/', careers_page, name='careers'),
    path('help/', help_center, name='help_center'),
    path('faq/', faq_page, name='faq_page'),
    path('article/<slug:slug>/', article_detail, name='article_detail'),
    path('admin/live-stats/', core_views.live_stats, name='live_stats'),
    path('admin/upload-logo/', core_admin_views.upload_logo, name='upload_logo'),
    path('admin/avatar-upload/<int:user_id>/', core_admin_views.upload_user_avatar, name='avatar_upload'),
    path('admin/avatar-delete/<int:user_id>/', core_admin_views.delete_user_avatar, name='avatar_delete'),
]

# CKEditor 5 URLs
try:
    from django_ckeditor_5.views import upload_file, browse_files
    urlpatterns += [
        re_path(r'^ckeditor5/upload/', upload_file, name='ck_editor_5_upload_file'),
        re_path(r'^ckeditor5/browse/', browse_files, name='ck_editor_5_browse_files'),
    ]
    print("✅ CKEditor 5 URLs added")
except ImportError:
    from ckeditor_views.views import upload_file, browse_files
    urlpatterns += [
        re_path(r'^ckeditor5/upload/', upload_file, name='ck_editor_5_upload_file'),
        re_path(r'^ckeditor5/browse/', browse_files, name='ck_editor_5_browse_files'),
    ]
    print("⚠️ Using custom CKEditor views")

def custom_404(request, exception):
    return render(request, '404.html', status=404)

handler404 = 'arolana_config.urls.custom_404'

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)