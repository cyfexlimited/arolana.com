from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models import Sum
from datetime import timedelta
from django.utils.timezone import now
from django.conf import settings
from .models import SiteSettings, PromoBanner
from products.models import Product
from orders.models import Order
from vendors.models import VendorProfile


# =========================
# 🔥 GLOBAL STATS FUNCTION
# =========================
def get_admin_stats():
    User = get_user_model()

    return {
        'total_users': User.objects.count(),
        'total_vendors': VendorProfile.objects.count(),
        'total_products': Product.objects.count(),
        'total_orders': Order.objects.count(),
        'pending_orders': Order.objects.filter(status='pending').count(),
        'pending_vendors': VendorProfile.objects.filter(is_verified=False).count(),
    }


# =========================
# 🔥 SITE SETTINGS ADMIN
# =========================
@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ('site_name', 'site_tagline', 'is_active', 'logo_preview')
    list_editable = ('is_active',)
    list_filter = ('is_active',)
    search_fields = ('site_name',)

    fieldsets = (
        ('Basic Information', {
            'fields': ('site_name', 'site_tagline', 'site_description', 'site_keywords', 'is_active'),
        }),
        ('Branding', {
            'fields': ('site_logo', 'site_favicon', 'footer_logo'),
            'description': 'Upload branding assets',
        }),
        ('Contact Information', {
            'fields': ('contact_email', 'contact_phone', 'address'),
        }),
        ('Social Media', {
            'fields': ('facebook_url', 'twitter_url', 'instagram_url', 'linkedin_url', 'youtube_url'),
            'classes': ('collapse',),
        }),
        ('Colors', {
            'fields': ('primary_color', 'secondary_color'),
        }),
        ('Footer', {
            'fields': ('footer_copyright', 'shipping_note', 'return_policy', 'warranty_note'),
            'classes': ('collapse',),
        }),
        ('SEO', {
            'fields': ('meta_author', 'meta_robots'),
            'classes': ('collapse',),
        }),
    )

    def logo_preview(self, obj):
        if obj.site_logo:
            return format_html(
                '<img src="{}" style="width:50px;height:50px;border-radius:8px;object-fit:cover;" />',
                obj.site_logo.url
            )
        return mark_safe('<span style="color:#999;">No Logo</span>')

    logo_preview.short_description = "Logo"

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()


# =========================
# 🔥 PROMO BANNER ADMIN
# =========================
@admin.register(PromoBanner)
class PromoBannerAdmin(admin.ModelAdmin):
    list_display = ('title', 'order', 'is_active', 'preview', 'created_at')
    list_editable = ('order', 'is_active')
    list_filter = ('is_active', 'created_at')
    search_fields = ('title', 'subtitle')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Content', {
            'fields': ('title', 'subtitle', 'button_text', 'button_url'),
        }),
        ('Design', {
            'fields': ('background_color_start', 'background_color_end', 'image'),
        }),
        ('Settings', {
            'fields': ('order', 'is_active', 'created_at', 'updated_at'),
        }),
    )

    def preview(self, obj):
        subtitle = obj.subtitle or "No subtitle"
        if len(subtitle) > 40:
            subtitle = subtitle[:40] + "..."

        return format_html(
            '''
            <div style="
                background: linear-gradient(135deg, {} , {});
                padding: 10px;
                border-radius: 8px;
                color: #fff;
                min-width:180px;
                text-align:center;
                font-size:12px;
            ">
                <strong>{}</strong><br>
                <small>{}</small><br>
                <span style="
                    display:inline-block;
                    margin-top:6px;
                    padding:3px 6px;
                    background:rgba(255,255,255,0.2);
                    border-radius:4px;
                ">
                    {}
                </span>
            </div>
            ''',
            obj.background_color_start,
            obj.background_color_end,
            obj.title,
            subtitle,
            obj.button_text or "CTA"
        )

    preview.short_description = "Preview"

    def get_queryset(self, request):
        return super().get_queryset(request).order_by('order', '-created_at')


# =========================
# 🔥 CUSTOM ADMIN SITE
# =========================
class CustomAdminSite(admin.AdminSite):
    site_header = "Arolana Admin"
    site_title = "Arolana Control Panel"
    index_title = "Dashboard"

    def each_context(self, request):
        context = super().each_context(request)
        context.update({
            'admin_stats': get_admin_stats(),
            'debug': settings.DEBUG,
        })
        return context


# Create custom admin site instance
custom_admin_site = CustomAdminSite(name="custom_admin")

# Register core models with custom admin site
custom_admin_site.register(Group)

# Update the default admin settings
admin.site.site_header = 'Arolana Administration'
admin.site.site_title = 'Arolana Admin'
admin.site.index_title = 'Dashboard'
admin.site.site_url = '/'

# =========================
# 🔥 DASHBOARD CONTEXT
# =========================
def admin_dashboard_context(request):
    """Context processor for admin dashboard"""
    today = now().date()

    latest_orders = Order.objects.select_related('user').order_by('-created_at')[:5]
    latest_products = Product.objects.select_related('category', 'vendor').order_by('-created_at')[:5]
    latest_users = get_user_model().objects.order_by('-date_joined')[:5]

    chart_labels = []
    chart_data = []

    for i in range(6, -1, -1):
        day = today - timedelta(days=i)

        revenue = Order.objects.filter(
            created_at__date=day,
            status='delivered'
        ).aggregate(total=Sum('total'))['total'] or 0

        chart_labels.append(day.strftime('%b %d'))
        chart_data.append(float(revenue))

    return {
        'latest_orders': latest_orders,
        'latest_products': latest_products,
        'latest_users': latest_users,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'admin_stats': get_admin_stats(),
        'debug': settings.DEBUG,
    }
