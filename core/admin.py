from django.contrib import admin
from django import forms
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models import Sum
from datetime import timedelta
from django.utils.timezone import now
from django.conf import settings

from .models import (
    AdminAppearance,
    ContentTranslation,
    HomePageAppearance,
    PromoBanner,
    ProtectedImageAsset,
    SiteSettings,
)
from products.models import Product
from orders.models import Order
from vendors.models import VendorProfile


@admin.register(ContentTranslation)
class ContentTranslationAdmin(admin.ModelAdmin):
    list_display = (
        "target",
        "language_code",
        "field_name",
        "translated_preview",
        "is_active",
        "updated_at",
    )
    list_filter = ("language_code", "is_active", "content_type", "field_name")
    search_fields = (
        "translation_key",
        "field_name",
        "translated_text",
        "object_id",
    )
    list_editable = ("is_active",)
    ordering = ("content_type", "object_id", "field_name", "language_code")
    raw_id_fields = ("content_type",)

    fieldsets = (
        ("Translation Target", {
            "fields": (
                "content_type",
                "object_id",
                "field_name",
                "translation_key",
            ),
            "description": (
                "For database content, select the model type, object ID, and field. "
                "For a shared label such as a product condition, use Translation key only."
            ),
        }),
        ("Localized Content", {
            "fields": ("language_code", "translated_text", "is_active"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Target")
    def target(self, obj):
        if obj.translation_key:
            return obj.translation_key
        return f"{obj.content_type} #{obj.object_id}"

    @admin.display(description="Translation")
    def translated_preview(self, obj):
        value = str(obj.translated_text or "").replace("\n", " ")
        return value if len(value) <= 100 else f"{value[:97]}..."


# =========================
# PROTECTED IMAGE ASSET ADMIN
# =========================
@admin.register(ProtectedImageAsset)
class ProtectedImageAssetAdmin(admin.ModelAdmin):
    list_display = (
        "file_name_short",
        "original_filename_short",
        "vendor",
        "uploader",
        "source_product_id",
        "content_type",
        "object_id",
        "field_name",
        "image_size",
        "sha256_short",
        "perceptual_hash_short",
        "duplicate_badge",
        "duplicate_of",
        "used_by_count",
        "allow_duplicate",
        "updated_at",
    )

    list_editable = ("allow_duplicate",)
    list_select_related = (
        "content_type",
        "duplicate_of",
        "vendor",
        "uploader",
    )
    list_per_page = 50

    actions = (
        "allow_selected_duplicates",
        "block_selected_duplicates",
    )

    def get_model_field_names(self):
        return {field.name for field in self.model._meta.fields}

    def get_list_filter(self, request):
        fields = self.get_model_field_names()
        filters = []

        for field in (
            "duplicate_status",
            "duplicate_type",
            "is_duplicate",
            "allow_duplicate",
            "vendor",
            "uploader",
            "content_type",
            "field_name",
            "updated_at",
        ):
            if field in fields:
                filters.append(field)

        return tuple(filters)

    def get_search_fields(self, request):
        fields = self.get_model_field_names()
        search_fields = []

        for field in (
            "file_name",
            "original_filename",
            "sha256",
            "perceptual_hash",
            "duplicate_reason",
            "field_name",
            "vendor__email",
            "vendor__username",
            "uploader__email",
        ):
            if field in fields:
                search_fields.append(field)

        return tuple(search_fields)

    def get_readonly_fields(self, request, obj=None):
        fields = self.get_model_field_names()
        readonly = []

        for field in (
            "content_type",
            "object_id",
            "field_name",
            "file_name",
            "original_filename",
            "sha256",
            "perceptual_hash",
            "width",
            "height",
            "size_bytes",
            "is_duplicate",
            "duplicate_type",
            "duplicate_status",
            "perceptual_distance",
            "duplicate_of",
            "vendor",
            "uploader",
            "source_product_id",
            "created_at",
            "updated_at",
        ):
            if field in fields:
                readonly.append(field)

        return tuple(readonly)

    def file_name_short(self, obj):
        name = str(getattr(obj, "file_name", "") or "")
        if not name:
            return "-"
        return name if len(name) <= 75 else f"...{name[-75:]}"
    file_name_short.short_description = "File"

    def original_filename_short(self, obj):
        name = str(getattr(obj, "original_filename", "") or "")
        return name if len(name) <= 45 else f"{name[:42]}..."
    original_filename_short.short_description = "Original name"

    def sha256_short(self, obj):
        value = getattr(obj, "sha256", "") or ""
        return value[:16] if value else "-"
    sha256_short.short_description = "SHA-256"

    def perceptual_hash_short(self, obj):
        value = getattr(obj, "perceptual_hash", "") or ""
        return value[:16] if value else "-"
    perceptual_hash_short.short_description = "pHash"

    def image_size(self, obj):
        width = getattr(obj, "width", None)
        height = getattr(obj, "height", None)
        if width and height:
            return f"{width} × {height}"
        return "-"
    image_size.short_description = "Size"

    def duplicate_badge(self, obj):
        if getattr(obj, "allow_duplicate", False) or getattr(obj, "duplicate_status", "") == "admin_override":
            return format_html(
                '<span style="background:#2563eb;color:#fff;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:700;">Approved Shared</span>'
            )

        if getattr(obj, "duplicate_status", "") == "same_vendor_reuse":
            return format_html(
                '<span style="background:#0f766e;color:#fff;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:700;">Same Vendor Reuse</span>'
            )

        if getattr(obj, "duplicate_status", "") == "rejected":
            return format_html(
                '<span style="background:#991b1b;color:#fff;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:700;">Rejected</span>'
            )

        if getattr(obj, "is_duplicate", False):
            label = "Exact Duplicate" if getattr(obj, "duplicate_type", "") == "exact" else "Likely Duplicate"
            return format_html(
                '<span style="background:#dc2626;color:#fff;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:700;">{} / Review</span>',
                label,
            )

        return format_html(
            '<span style="background:#059669;color:#fff;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:700;">Original</span>'
        )
    duplicate_badge.short_description = "Status"

    def used_by_count(self, obj):
        return obj.duplicate_assets.count() + 1
    used_by_count.short_description = "Used by"

    @admin.action(description="✅ Allow selected duplicate/shared images")
    def allow_selected_duplicates(self, request, queryset):
        update_data = {"allow_duplicate": True}
        fields = self.get_model_field_names()

        if "reviewed_by" in fields:
            update_data["reviewed_by"] = request.user
        if "reviewed_at" in fields:
            update_data["reviewed_at"] = now()
        if "duplicate_status" in fields:
            update_data["duplicate_status"] = "admin_override"

        updated = queryset.update(**update_data)
        self.message_user(request, f"✅ {updated} image asset(s) approved for duplicate/shared use.")

    @admin.action(description="❌ Block selected duplicate/shared images")
    def block_selected_duplicates(self, request, queryset):
        update_data = {"allow_duplicate": False}
        fields = self.get_model_field_names()

        if "reviewed_by" in fields:
            update_data["reviewed_by"] = request.user
        if "reviewed_at" in fields:
            update_data["reviewed_at"] = now()
        if "duplicate_status" in fields:
            update_data["duplicate_status"] = "rejected"

        updated = queryset.update(**update_data)
        self.message_user(request, f"❌ {updated} image asset duplicate approval(s) removed.")


# =========================
# ADMIN APPEARANCE FORM
# =========================
class AdminAppearanceForm(forms.ModelForm):
    color_fields = (
        'page_background_color',
        'content_background_color',
        'card_background_color',
        'text_color',
        'muted_text_color',
        'primary_color',
        'accent_color',
        'hero_start_color',
        'hero_end_color',
        'navbar_background_color',
        'navbar_text_color',
        'sidebar_background_color',
        'sidebar_text_color',
    )

    class Meta:
        model = AdminAppearance
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name in self.color_fields:
            if field_name in self.fields:
                self.fields[field_name].widget = forms.TextInput(attrs={'type': 'color'})


@admin.register(AdminAppearance)
class AdminAppearanceAdmin(admin.ModelAdmin):
    form = AdminAppearanceForm
    list_display = ('name', 'is_active', 'page_background_color', 'primary_color', 'accent_color', 'updated_at')
    list_editable = ('is_active',)
    readonly_fields = ('preview', 'created_at', 'updated_at')

    fieldsets = (
        ('Status', {
            'fields': ('name', 'is_active', 'preview'),
            'description': 'Only one admin appearance can be active at a time.',
        }),
        ('Main Colors', {
            'fields': (
                'page_background_color',
                'content_background_color',
                'card_background_color',
                'text_color',
                'muted_text_color',
            ),
        }),
        ('Brand Colors', {
            'fields': ('primary_color', 'accent_color', 'hero_start_color', 'hero_end_color'),
        }),
        ('Navigation Colors', {
            'fields': (
                'navbar_background_color',
                'navbar_text_color',
                'sidebar_background_color',
                'sidebar_text_color',
            ),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def preview(self, obj):
        return format_html(
            '''
            <div style="background:{};border:1px solid #e5e7eb;border-radius:12px;max-width:520px;padding:14px;">
                <div style="background:linear-gradient(135deg, {}, {});border-radius:10px;color:#fff;padding:14px;margin-bottom:12px;">
                    <strong>Operations dashboard</strong><br>
                    <small>Hero and accent preview</small>
                </div>
                <div style="background:{};border-radius:10px;color:{};padding:12px;">
                    <strong>Readable content card</strong><br>
                    <small style="color:{};">Cards, forms, tables, and dashboard panels use these colors.</small>
                </div>
            </div>
            ''',
            obj.page_background_color,
            obj.hero_start_color,
            obj.hero_end_color,
            obj.card_background_color,
            obj.text_color,
            obj.muted_text_color,
        )
    preview.short_description = 'Preview'


# =========================
# GLOBAL STATS FUNCTION
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
# SITE SETTINGS ADMIN
# =========================
@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ('site_name', 'site_tagline', 'is_active', 'logo_preview')
    list_editable = ('is_active',)
    list_filter = ('is_active',)
    search_fields = ('site_name',)
    readonly_fields = ('admin_logo_preview', 'smart_chat_bot_preview')

    fieldsets = (
        ('Basic Information', {
            'fields': ('site_name', 'site_tagline', 'site_description', 'site_keywords', 'is_active'),
        }),
        ('Branding', {
            'fields': (
                'admin_logo_preview',
                'site_logo',
                'site_favicon',
                'footer_logo',
                'smart_chat_bot_preview',
                'smart_chat_bot_image',
                'logo_height_desktop',
                'logo_height_mobile',
                'footer_logo_height',
            ),
            'description': 'Upload the storefront/admin logo and a separate square avatar for Arolana Smart Chat.',
        }),
        ('Contact Information', {
            'fields': (
                'contact_email',
                'contact_phone',
                'support_whatsapp_number',
                'cart_whatsapp_message',
                'address',
            ),
            'description': 'Control Arolana support contact details, including the WhatsApp number and first cart support message customers send from the cart page.',
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

    def admin_logo_preview(self, obj):
        if obj and obj.site_logo:
            return format_html(
                '<div style="display:flex;align-items:center;gap:14px;">'
                '<img src="{}" style="max-width:220px;max-height:80px;border:1px solid #d0d7de;border-radius:10px;padding:10px;background:#fff;object-fit:contain;" />'
                '<span style="color:#475569;">This image is used for the admin sidebar logo after you save.</span>'
                '</div>',
                obj.site_logo.url
            )
        return mark_safe(
            '<span style="color:#64748b;">No uploaded logo yet. The admin will use the fallback static logo until you upload one here.</span>'
        )
    admin_logo_preview.short_description = "Current admin logo"

    def smart_chat_bot_preview(self, obj):
        if obj and obj.smart_chat_bot_image:
            return format_html(
                '<div style="display:flex;align-items:center;gap:14px;">'
                '<img src="{}" style="width:84px;height:84px;border:1px solid #d0d7de;border-radius:22px;padding:6px;background:#fff;object-fit:contain;" />'
                '<span style="color:#475569;">This avatar appears in the customer Smart Chat header.</span>'
                '</div>',
                obj.smart_chat_bot_image.url,
            )
        return mark_safe(
            '<span style="color:#64748b;">No Smart Chat image uploaded. The Arolana fallback logo will be used.</span>'
        )
    smart_chat_bot_preview.short_description = "Current Smart Chat bot image"

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()


# =========================
# HOMEPAGE APPEARANCE ADMIN
# =========================
@admin.register(HomePageAppearance)
class HomePageAppearanceAdmin(admin.ModelAdmin):
    list_display = ("title", "is_active", "desktop_preview", "mobile_preview", "updated_at")
    list_editable = ("is_active",)
    list_filter = ("is_active", "blur_background", "fixed_background", "make_sections_glass")
    search_fields = ("title",)
    readonly_fields = ("desktop_preview", "mobile_preview", "created_at", "updated_at")

    fieldsets = (
        ("Status", {
            "fields": ("title", "is_active"),
            "description": "Enable or disable the homepage background image from here.",
        }),
        ("Homepage Background Images", {
            "fields": (
                ("desktop_preview", "mobile_preview"),
                ("desktop_background_image", "mobile_background_image"),
            ),
            "description": (
                "Upload separate homepage background images for desktop and mobile. "
                "Recommended desktop: 1920×1080 WebP. Recommended mobile: 1080×1350 WebP or 1080×1920 WebP."
            ),
        }),
        ("Overlay and Position", {
            "fields": (
                ("desktop_overlay_opacity", "mobile_overlay_opacity"),
                ("desktop_position", "mobile_position"),
                ("blur_background", "fixed_background", "make_sections_glass"),
            ),
            "description": (
                "Overlay opacity controls image visibility. "
                "Lower value = image clearer. Higher value = image softer/more muted."
            ),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request):
        if HomePageAppearance.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def desktop_preview(self, obj):
        if not obj or not obj.desktop_background_image:
            return mark_safe('<span style="color:#64748b;">No desktop background uploaded.</span>')
        try:
            return format_html(
                '<div style="width:260px;height:105px;border-radius:14px;overflow:hidden;'
                'border:1px solid #e5e7eb;background:#f8fafc;">'
                '<img src="{}" style="width:100%;height:100%;object-fit:cover;" alt="Desktop homepage background">'
                '</div>'
                '<div style="font-size:11px;color:#6b7280;margin-top:4px;">Recommended: 1920×1080 WebP</div>',
                obj.desktop_background_image.url,
            )
        except Exception:
            return "Desktop image exists but preview failed."
    desktop_preview.short_description = "Desktop Preview"

    def mobile_preview(self, obj):
        if not obj or not obj.mobile_background_image:
            return mark_safe('<span style="color:#64748b;">No mobile background uploaded.</span>')
        try:
            return format_html(
                '<div style="width:100px;height:130px;border-radius:14px;overflow:hidden;'
                'border:1px solid #e5e7eb;background:#f8fafc;">'
                '<img src="{}" style="width:100%;height:100%;object-fit:cover;" alt="Mobile homepage background">'
                '</div>'
                '<div style="font-size:11px;color:#6b7280;margin-top:4px;">Recommended: 1080×1350 WebP</div>',
                obj.mobile_background_image.url,
            )
        except Exception:
            return "Mobile image exists but preview failed."
    mobile_preview.short_description = "Mobile Preview"


# =========================
# PROMO BANNER ADMIN
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
# CUSTOM ADMIN SITE
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


custom_admin_site = CustomAdminSite(name="custom_admin")
custom_admin_site.register(Group)


admin.site.site_header = 'Arolana Administration'
admin.site.site_title = 'Arolana Admin'
admin.site.index_title = 'Dashboard'
admin.site.site_url = '/'


# =========================
# DASHBOARD CONTEXT
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
