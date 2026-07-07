from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django import forms
from django_ckeditor_5.widgets import CKEditor5Widget
from django.db.models import Count, F, Q

from .models import (
    Category, Brand, Product, ProductImage, ProductVariant, 
    ProductVariantImage, ProductVariantSpecification, VendorProductOffer, ProductCatalogRequest,
    ProductReview, RecentlyViewed, 
    Wishlist, ProductVideo, ReviewVideo, ProductQnA,
    Accessory, AccessoryProduct, ManufacturerWarranty, ShippingInfo, ProductListingBanner,
    ProductArticleLink, CategoryArticleLink, ProductWholesaleTier, ProductDetailSection,
    ProductDetailFieldConfig, ProductVariantTypeConfig
)

from django.utils.timezone import now
from core.image_protection import duplicate_warning_payload, set_protected_image_uploader

# NOTE FOR VARIANT IMAGES:
# Add variant rows from the Product admin, save, then click the change/open link
# on each variant to upload multiple ProductVariantImage records.
# Django admin does not support Product > Variant > Variant Images nested inline directly.



# =================================
# 🔥 FORMS
# =================================

class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'
        widgets = {
            'description': CKEditor5Widget(config_name='default'),
            'specifications': CKEditor5Widget(config_name='default'),
        }

    class Media:
        css = {
            'all': ('css/ckeditor-custom.css',)
        }

    def clean_description(self):
        description = self.cleaned_data.get('description') or ''
        if 'UPLOAD_PRODUCT_IMAGE_URL_HERE' in str(description).upper():
            raise forms.ValidationError(
                'Upload the real product image and insert its media URL before publishing. '
                'Placeholder image URLs are not allowed.'
            )
        return description

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get("name")
        vendor = cleaned_data.get("vendor")
        requested_slug = cleaned_data.get("slug") or name
        if name:
            unique_slug = Product.build_unique_slug(
                name=name,
                vendor=vendor,
                requested_slug=requested_slug,
                current_pk=self.instance.pk,
            )
            cleaned_data["slug"] = unique_slug
            self._slug_adjusted_by_form = bool(requested_slug and unique_slug != requested_slug)
        return cleaned_data


def _message_image_duplicate_review(model_admin, request, instance, field_name):
    warning = duplicate_warning_payload(instance, field_name)
    if not warning:
        return None
    if warning.get("needs_review"):
        first_vendor = warning.get("first_vendor_name") or "another vendor"
        first_product = warning.get("first_product_name") or "an existing product"
        match_label = (
            "exact duplicate"
            if warning.get("match_type") == "exact"
            else "near-duplicate"
        )
        model_admin.message_user(
            request,
            (
                f"This image is an {match_label} already used by {first_vendor} "
                f"on {first_product}. Allow it only when it is official manufacturer "
                "media or the vendor has usage rights. Use the Protected Image Assets "
                "review action to approve or reject it."
            ),
            level="WARNING",
        )
    elif warning.get("same_vendor_reuse"):
        model_admin.message_user(
            request,
            warning.get("message") or "This image was reused from the same vendor catalogue.",
        )
    return warning


class AccessoryAdminForm(forms.ModelForm):
    class Meta:
        model = Accessory
        fields = '__all__'
        widgets = {
            'description': CKEditor5Widget(config_name='default'),
        }

    class Media:
        css = {
            'all': ('css/ckeditor-custom.css',)
        }


class InventoryStatusFilter(admin.SimpleListFilter):
    title = 'inventory status'
    parameter_name = 'inventory_status'

    def lookups(self, request, model_admin):
        return (
            ('in_stock', 'In stock'),
            ('low_stock', 'Low stock'),
            ('out_of_stock', 'Out of stock'),
            ('reserved', 'Has reserved stock'),
            ('backorder', 'Backorder enabled'),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'in_stock':
            return queryset.filter(stock_quantity__gt=F('reserved_quantity'))
        if value == 'low_stock':
            return queryset.filter(stock_quantity__gt=0, stock_quantity__lte=F('low_stock_threshold'))
        if value == 'out_of_stock':
            return queryset.filter(stock_quantity__lte=0)
        if value == 'reserved':
            return queryset.filter(reserved_quantity__gt=0)
        if value == 'backorder':
            return queryset.filter(allow_backorder=True)
        return queryset


class OptionalColorFieldAdminMixin:
    optional_color_fields = set()

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name in self.optional_color_fields and formfield:
            formfield.widget.attrs.update({
                'placeholder': '#2563eb',
                'style': 'max-width: 9rem;',
            })
        return formfield


class VariantStockStatusFilter(admin.SimpleListFilter):
    title = 'variant stock'
    parameter_name = 'variant_stock_status'

    def lookups(self, request, model_admin):
        return (
            ('available', 'Available'),
            ('out', 'Out of stock'),
            ('inactive', 'Inactive'),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'available':
            return queryset.filter(is_active=True, stock_quantity__gt=0)
        if value == 'out':
            return queryset.filter(stock_quantity__lte=0)
        if value == 'inactive':
            return queryset.filter(is_active=False)
        return queryset


# =================================
# 🔥 INLINE ADMINS
# =================================

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 5
    fields = ['image', 'alt_text', 'is_main', 'order', 'image_preview']
    readonly_fields = ['image_preview']
    
    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="80" height="80" style="object-fit: cover; border-radius: 4px;" />', 
                obj.image.url
            )
        return mark_safe('<span style="color: #9ca3af;">No Image</span>')
    image_preview.short_description = 'Preview'


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    fields = [
        'variant_mode',
        'variant_type',
        'name',
        'value',
        'model_number',
        'price_adjustment',
        'stock_quantity',
        'image',
        'selector_type',
        'display_order',
        'is_default',
        'color_code',
        'is_active',
    ]
    readonly_fields = ['sku']

    # Important:
    # Django admin does not support nested inlines like Product > Variant > Variant Images.
    # This adds an "open/change" link beside each variant row, so you can open the variant
    # and add multiple ProductVariantImage records under it.
    show_change_link = True


class ProductVariantImageInline(admin.TabularInline):
    model = ProductVariantImage
    extra = 5
    fields = ['image', 'image_type', 'title', 'alt_text', 'is_primary', 'sort_order', 'is_active', 'image_preview']
    readonly_fields = ['image_preview']

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="64" height="64" style="object-fit: cover; border-radius: 4px;" />',
                obj.image.url
            )
        return mark_safe('<span style="color: #9ca3af;">No Image</span>')
    image_preview.short_description = 'Preview'


class ProductVariantSpecificationInline(admin.TabularInline):
    model = ProductVariantSpecification
    extra = 1
    fields = ['group', 'name', 'value', 'unit', 'display_order', 'is_highlight', 'is_active']


class VendorProductOfferInline(admin.TabularInline):
    model = VendorProductOffer
    extra = 0
    fields = [
        'vendor',
        'variant',
        'seller_sku',
        'price',
        'sale_price',
        'stock_quantity',
        'condition',
        'approval_status',
        'is_featured',
        'is_preferred',
        'is_active',
    ]
    autocomplete_fields = ['vendor', 'variant']
    show_change_link = True


@admin.register(ProductDetailSection)
class ProductDetailSectionAdmin(admin.ModelAdmin):
    list_display = ['title', 'key', 'display_order', 'is_enabled', 'web_enabled', 'mobile_enabled']
    list_editable = ['display_order', 'is_enabled', 'web_enabled', 'mobile_enabled']
    list_filter = ['is_enabled', 'web_enabled', 'mobile_enabled']
    search_fields = ['title', 'key']


@admin.register(ProductDetailFieldConfig)
class ProductDetailFieldConfigAdmin(admin.ModelAdmin):
    list_display = ['label', 'key', 'display_order', 'is_enabled', 'is_required']
    list_editable = ['display_order', 'is_enabled', 'is_required']
    list_filter = ['is_enabled', 'is_required']
    search_fields = ['label', 'key', 'help_text']


@admin.register(ProductVariantTypeConfig)
class ProductVariantTypeConfigAdmin(admin.ModelAdmin):
    list_display = ['label', 'key', 'display_order', 'is_active']
    list_editable = ['display_order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['label', 'key']


class ProductVideoInline(admin.TabularInline):
    model = ProductVideo
    extra = 1
    fields = ['title', 'description', 'source', 'youtube_url', 'vimeo_url', 'local_video', 'thumbnail', 'is_main', 'display_order']


class ProductArticleLinkInline(admin.StackedInline):
    model = ProductArticleLink
    extra = 1
    fields = [
        'article',
        'label',
        'teaser',
        'placement',
        'open_behavior',
        'reader_content_mode',
        ('reader_show_ads', 'reader_show_newsletter', 'reader_show_comments'),
        ('reader_show_cookie_banner', 'reader_show_chat_widgets', 'reader_show_site_header_footer'),
        'sort_order',
        'is_active',
    ]
    autocomplete_fields = ['article']
    show_change_link = True


class CategoryArticleLinkInline(admin.TabularInline):
    model = CategoryArticleLink
    extra = 1
    fields = ['article', 'label', 'teaser', 'placement', 'open_behavior', 'sort_order', 'is_active']
    autocomplete_fields = ['article']


class ProductWholesaleTierInline(admin.TabularInline):
    model = ProductWholesaleTier
    extra = 1
    fields = ['min_quantity', 'max_quantity', 'price_per_unit', 'sort_order', 'is_active']


class AccessoryInline(admin.TabularInline):
    model = AccessoryProduct
    extra = 1
    fields = ['accessory', 'required', 'discount_when_bought_together', 'display_order']
    autocomplete_fields = ['accessory']


class ManufacturerWarrantyInline(admin.StackedInline):
    model = ManufacturerWarranty
    extra = 0
    max_num = 1
    fields = ['provider', 'duration_years', 'duration_months', 'coverage_details', 'exclusions', 'registration_required', 'registration_url', 'terms_url', 'customer_support_phone', 'customer_support_email']


class ShippingInfoInline(admin.StackedInline):
    model = ShippingInfo
    extra = 0
    max_num = 1
    fields = ['weight_shipping', 'dimensions_package', 'free_shipping', 'estimated_delivery_days_min', 'estimated_delivery_days_max', 'shipping_restrictions', 'hazmat']


class ReviewVideoInline(admin.TabularInline):
    model = ReviewVideo
    extra = 1
    fields = ['title', 'video_file', 'thumbnail', 'is_main']


# =================================
# 🔥 PRODUCT ADMIN WITH APPROVAL SYSTEM
# =================================

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = ['sku', 'manufacturer_sku', 'name', 'condition', 'price', 'stock_quantity', 'available_stock_display', 'stock_status_badge', 'approval_status_badge', 'is_featured', 'is_active', 'image_preview']
    list_editable = ['price', 'stock_quantity', 'is_featured', 'is_active']
    list_filter = [InventoryStatusFilter, 'condition', 'is_active', 'is_featured', 'is_new', 'is_bestseller', 'category', 'brand', 'approval_status', 'allow_backorder', 'created_at']
    search_fields = ['sku', 'manufacturer_sku', 'name', 'description']
    prepopulated_fields = {'slug': ['name']}
    readonly_fields = ['views_count', 'sales_count', 'rating_avg', 'rating_count', 'created_at', 'updated_at', 'sku', 'submitted_for_review_at', 'approved_at']
    inlines = [ProductImageInline, ProductVariantInline, VendorProductOfferInline, ProductWholesaleTierInline, ProductVideoInline, ProductArticleLinkInline, AccessoryInline, ManufacturerWarrantyInline, ShippingInfoInline]
    autocomplete_fields = ['vendor', 'category', 'brand']
    list_select_related = ['category', 'brand', 'vendor']
    list_per_page = 30

    def save_model(self, request, obj, form, change):
        submitted_slug = obj.slug
        super().save_model(request, obj, form, change)
        if getattr(obj, "_slug_was_adjusted", False) or getattr(form, "_slug_adjusted_by_form", False) or obj.slug != submitted_slug:
            self.message_user(
                request,
                f'Slug adjusted automatically to "{obj.slug}" because another listing uses the requested URL.',
            )
        for field_name in ("main_image", "video_thumbnail"):
            if getattr(obj, field_name, None):
                set_protected_image_uploader(obj, field_name, request.user)
                _message_image_duplicate_review(self, request, obj, field_name)

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        for inline_form in getattr(formset, "forms", []):
            instance = getattr(inline_form, "instance", None)
            if not instance or not getattr(instance, "pk", None):
                continue
            for field_name in ("image", "thumbnail"):
                if getattr(instance, field_name, None):
                    set_protected_image_uploader(instance, field_name, request.user)
                    _message_image_duplicate_review(self, request, instance, field_name)
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('sku', 'manufacturer_sku', 'name', 'slug', 'condition', 'category', 'brand', 'vendor')
        }),
        ('Description & Specifications', {
            'fields': ('description', 'specifications'),
            'description': 'Use the rich text editor to add formatted content'
        }),
        ('Pricing', {
            'fields': ('price', 'compare_price', 'cost_per_item', 'wholesale_price', 'bulk_price')
        }),
        ('Inventory', {
            'fields': ('stock_quantity', 'reserved_quantity', 'low_stock_threshold', 'is_in_stock', 'allow_backorder', 'minimum_order_quantity', 'moq_unit', 'sample_available', 'sample_price'),
            'description': 'Manage product stock, reserved quantities, low-stock alerts, and backorder behavior from one place.'
        }),
        ('Manufacturer & Bulk Trade', {
            'fields': ('lead_time_days', 'country_of_origin', 'manufacturer_address', 'certifications'),
            'classes': ('collapse',)
        }),
        ('Physical Attributes', {
            'fields': ('weight', 'weight_unit', 'dimensions_length', 'dimensions_width', 'dimensions_height', 'dimension_unit'),
            'classes': ('collapse',)
        }),
        ('Warranty', {
            'fields': ('warranty_years', 'warranty_description', 'extended_warranty_available', 'extended_warranty_price'),
            'classes': ('collapse',)
        }),
        ('Media', {
            'fields': ('main_image', 'manual_pdf', 'video_type', 'video_url', 'local_video', 'video_thumbnail', 'video_title'),
            'description': 'Add product images, optional PDF manual/brochure, and videos (YouTube, Vimeo, or local MP4).'
        }),
        ('Product Detail Display Controls', {
            'fields': (
                'show_top_gallery',
                'show_auto_overview_gallery',
                'auto_fill_description_images',
            ),
            'description': (
                'Control how this product appears on the frontend. '
                'Show top gallery controls the main gallery beside checkout. '
                'Show auto overview gallery controls the automatic gallery inside the Overview tab. '
                'Auto fill description images fills styled description placeholders from uploaded product images.'
            ),
        }),
        ('SEO', {
            'fields': ('meta_title', 'meta_description', 'meta_keywords'),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('views_count', 'sales_count', 'rating_avg', 'rating_count'),
            'classes': ('collapse',)
        }),
        # ========== APPROVAL SYSTEM SECTION ==========
        ('Approval System', {
            'fields': ('approval_status', 'approval_notes', 'approved_by', 'approved_at', 'submitted_for_review_at'),
            'description': 'Manage product approval status. Products must be approved before appearing on the frontend.',
        }),
        ('Features', {
            'fields': ('is_featured', 'is_new', 'is_bestseller', 'is_active', 'tags')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("category", "brand", "vendor")
            .annotate(
                active_article_link_count=Count(
                    "article_links",
                    filter=Q(article_links__is_active=True),
                    distinct=True,
                ),
            )
        )
    
    def image_preview(self, obj):
        if obj.main_image:
            return format_html(
                '<img src="{}" width="80" height="80" style="object-fit: cover; border-radius: 4px;" />', 
                obj.main_image.url
            )
        return mark_safe('<span style="color: #9ca3af;">No Image</span>')
    image_preview.short_description = 'Preview'
    
    def approval_status_badge(self, obj):
        """Display approval status with colored badge"""
        status_colors = {
            'pending': ('#f59e0b', 'Pending'),
            'approved': ('#10b981', 'Approved'),
            'rejected': ('#ef4444', 'Rejected'),
            'requires_changes': ('#f97316', 'Changes Required'),
        }
        color, text = status_colors.get(obj.approval_status, ('#6b7280', obj.approval_status))
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color, text
        )
    approval_status_badge.short_description = 'Approval Status'

    def available_stock_display(self, obj):
        available = obj.available_stock
        color = '#dc2626' if available <= 0 else '#d97706' if obj.is_low_stock else '#059669'
        return format_html('<strong style="color: {};">{}</strong>', color, available)
    available_stock_display.short_description = 'Available'
    available_stock_display.admin_order_field = 'stock_quantity'

    def stock_status_badge(self, obj):
        if obj.stock_quantity <= 0:
            label, color = 'Out of stock', '#dc2626'
        elif obj.is_low_stock:
            label, color = 'Low stock', '#d97706'
        elif obj.reserved_quantity:
            label, color = 'Reserved', '#2563eb'
        else:
            label, color = 'Healthy', '#059669'
        return format_html(
            '<span style="background: {}; color: #fff; padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 700;">{}</span>',
            color,
            label
        )
    stock_status_badge.short_description = 'Stock'
    
    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        
        if search_term:
            try:
                from vendors.models import Vendor
                vendor_ids = Vendor.objects.filter(name__icontains=search_term).values_list('id', flat=True)
                queryset = queryset | Product.objects.filter(vendor_id__in=vendor_ids)
                use_distinct = True
            except Exception:
                pass
        
        return queryset, use_distinct
    
    actions = [
        'mark_as_featured',
        'mark_as_unfeatured',
        'activate_products',
        'deactivate_products',
        'approve_products',
        'reject_products',
        'mark_out_of_stock',
        'reset_reserved_quantity',
        'enable_backorders',
        'disable_backorders',
    ]
    
    def mark_as_featured(self, request, queryset):
        queryset.update(is_featured=True)
        self.message_user(request, f"⭐ {queryset.count()} products marked as featured.")
    mark_as_featured.short_description = "⭐ Mark as featured"
    
    def mark_as_unfeatured(self, request, queryset):
        queryset.update(is_featured=False)
        self.message_user(request, f"☆ {queryset.count()} products unmarked as featured.")
    mark_as_unfeatured.short_description = "☆ Unmark as featured"
    
    def activate_products(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f"✅ {queryset.count()} products activated.")
    activate_products.short_description = "✅ Activate selected products"
    
    def deactivate_products(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f"❌ {queryset.count()} products deactivated.")
    deactivate_products.short_description = "❌ Deactivate selected products"
    
    # ========== APPROVAL ACTIONS ==========
    def approve_products(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(approval_status='approved', approved_by=request.user, approved_at=timezone.now(), is_active=True)
        self.message_user(request, f"✅ {updated} product(s) approved and are now live on the site.")
    approve_products.short_description = "✅ Approve selected products"
    
    def reject_products(self, request, queryset):
        updated = queryset.update(approval_status='rejected', is_active=False)
        self.message_user(request, f"❌ {updated} product(s) rejected.")
    reject_products.short_description = "❌ Reject selected products"

    def mark_out_of_stock(self, request, queryset):
        updated = queryset.update(stock_quantity=0, is_in_stock=False)
        self.message_user(request, f"{updated} product(s) marked out of stock.")
    mark_out_of_stock.short_description = "Mark selected products out of stock"

    def reset_reserved_quantity(self, request, queryset):
        updated = queryset.update(reserved_quantity=0)
        self.message_user(request, f"Reserved quantity reset for {updated} product(s).")
    reset_reserved_quantity.short_description = "Reset reserved stock for selected products"

    def enable_backorders(self, request, queryset):
        updated = queryset.update(allow_backorder=True)
        self.message_user(request, f"Backorders enabled for {updated} product(s).")
    enable_backorders.short_description = "Enable backorders"

    def disable_backorders(self, request, queryset):
        updated = queryset.update(allow_backorder=False)
        self.message_user(request, f"Backorders disabled for {updated} product(s).")
    disable_backorders.short_description = "Disable backorders"


# =================================
# 🔥 CATEGORY ADMIN
# =================================

@admin.register(Category)
class CategoryAdmin(OptionalColorFieldAdminMixin, admin.ModelAdmin):
    optional_color_fields = {
        'hero_background_color',
        'hero_text_color',
        'hero_accent_color',
        'hero_button_background_color',
        'hero_button_text_color',
    }
    list_display = ['name', 'parent', 'order', 'is_active', 'image_preview', 'has_background_status', 'article_links_display', 'product_count_display']
    list_filter = ['is_active', 'parent']
    search_fields = ['name', 'slug', 'description']
    prepopulated_fields = {'slug': ['name']}
    list_editable = ['order', 'is_active']
    inlines = [CategoryArticleLinkInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'parent', 'order', 'is_active')
        }),
        ('Category Images', {
            'fields': ('image', 'background_image'),
            'description': 'Image for category card (thumbnail) and hero background image for landing page'
        }),
        ('Hero Section', {
            'fields': (
                'hero_title',
                'hero_subtitle',
                ('show_hero_eyebrow', 'show_hero_title', 'show_hero_subtitle'),
                ('show_hero_stats', 'show_hero_cta', 'show_hero_side_image'),
                ('hero_background_color', 'hero_text_color', 'hero_accent_color'),
                ('hero_button_background_color', 'hero_button_text_color'),
                ('hero_image_brightness', 'hero_height_desktop', 'hero_height_tablet', 'hero_height_mobile'),
            ),
            'description': 'Customize the hero section on the category landing page. Turn off text/metrics when your uploaded design already includes them.',
            'classes': ('wide',)
        }),
        ('SEO & Description', {
            'fields': ('description', 'meta_title', 'meta_description', 'meta_keywords'),
            'classes': ('collapse',)
        }),
        ('Icon', {
            'fields': ('icon',),
            'classes': ('collapse',)
        }),
    )
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="50" height="50" style="object-fit: cover; border-radius: 4px;" />', obj.image.url)
        return mark_safe('<span style="color: #9ca3af;">No Image</span>')
    image_preview.short_description = 'Thumbnail'
    
    def has_background_status(self, obj):
        if obj.background_image:
            return mark_safe('<span style="color: #10b981; font-weight: bold;">✓ Has Background</span>')
        return mark_safe('<span style="color: #9ca3af;">— No Background —</span>')
    has_background_status.short_description = 'Hero Background'
    
    def product_count_display(self, obj):
        count = obj.product_count if hasattr(obj, 'product_count') else 0
        if count > 0:
            return mark_safe(f'<span style="color: #3b82f6; font-weight: bold;">{count} products</span>')
        return mark_safe('<span style="color: #9ca3af;">0 products</span>')
    product_count_display.short_description = 'Products'

    def article_links_display(self, obj):
        count = getattr(obj, 'active_article_link_count', 0)
        if count:
            return mark_safe(f'<span style="color: #f97316; font-weight: bold;">{count} article link(s)</span>')
        return mark_safe('<span style="color: #9ca3af;">No articles</span>')
    article_links_display.short_description = 'Articles'


@admin.register(CategoryArticleLink)
class CategoryArticleLinkAdmin(admin.ModelAdmin):
    list_display = ['category', 'article', 'placement', 'open_behavior', 'sort_order', 'is_active']
    list_filter = ['is_active', 'placement', 'open_behavior', 'category']
    search_fields = ['category__name', 'article__title', 'label', 'teaser']
    autocomplete_fields = ['category', 'article']
    list_editable = ['sort_order', 'is_active']


# =================================
# 🔥 BRAND ADMIN
# =================================

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'logo_preview', 'is_active', 'featured']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ['name']}
    list_filter = ['is_active', 'featured', 'created_at']
    list_editable = ['is_active', 'featured']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'description', 'is_active', 'featured')
        }),
        ('Media & Links', {
            'fields': ('logo', 'website'),
            'classes': ('collapse',)
        }),
    )
    
    def logo_preview(self, obj):
        if obj.logo:
            return format_html(
                '<img src="{}" width="50" height="50" style="border-radius: 50%; object-fit: cover;" />', 
                obj.logo.url
            )
        return mark_safe('<span style="color: #9ca3af;">No Logo</span>')
    logo_preview.short_description = 'Logo'


# =================================
# 🔥 ACCESSORY ADMIN
# =================================

@admin.register(Accessory)
class AccessoryAdmin(admin.ModelAdmin):
    form = AccessoryAdminForm
    list_display = ['name', 'price', 'compare_price', 'stock_quantity', 'is_active', 'image_preview', 'discount_display']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    list_editable = ['price', 'compare_price', 'stock_quantity', 'is_active']
    list_per_page = 20
    prepopulated_fields = {'slug': ['name']}
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'description', 'is_active')
        }),
        ('Pricing', {
            'fields': ('price', 'compare_price')
        }),
        ('Inventory', {
            'fields': ('stock_quantity',)
        }),
        ('Media', {
            'fields': ('image',),
            'classes': ('collapse',)
        }),
        ('Display', {
            'fields': ('display_order',),
            'classes': ('collapse',)
        }),
    )
    
    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="50" height="50" style="object-fit: cover; border-radius: 4px;" />', 
                obj.image.url
            )
        return mark_safe('<span style="color: #9ca3af;">No Image</span>')
    image_preview.short_description = 'Preview'
    
    def discount_display(self, obj):
        if obj.compare_price and obj.compare_price > obj.price:
            return format_html('<span style="color: #10b981; font-weight: bold;">Save {}%</span>', obj.discount_percent)
        return "-"
    discount_display.short_description = 'Discount'
    
    actions = ['activate_accessories', 'deactivate_accessories']
    
    def activate_accessories(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f"✅ {queryset.count()} accessories activated.")
    activate_accessories.short_description = "✅ Activate selected"


# =================================
# 🔥 ACCESSORY PRODUCT ADMIN
# =================================

@admin.register(AccessoryProduct)
class AccessoryProductAdmin(admin.ModelAdmin):
    list_display = ['product_name', 'accessory_name', 'required', 'discount_when_bought_together', 'display_order']
    list_filter = ['required', 'created_at']
    search_fields = ['product__name', 'accessory__name']
    autocomplete_fields = ['product', 'accessory']
    list_editable = ['required', 'discount_when_bought_together', 'display_order']
    list_select_related = ['product', 'accessory']
    
    def product_name(self, obj):
        return obj.product.name
    product_name.short_description = 'Product'
    
    def accessory_name(self, obj):
        return obj.accessory.name
    accessory_name.short_description = 'Accessory'


# =================================
# 🔥 PRODUCT IMAGE ADMIN
# =================================

@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ['product_name', 'is_main', 'order', 'image_preview', 'created_at']
    list_filter = ['is_main', 'created_at']
    list_editable = ['order', 'is_main']
    search_fields = ['product__name', 'alt_text']
    list_select_related = ['product']
    
    def product_name(self, obj):
        return obj.product.name
    product_name.short_description = 'Product'
    
    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="50" height="50" style="object-fit: cover; border-radius: 4px;" />', 
                obj.image.url
            )
        return mark_safe('<span style="color: #9ca3af;">No Image</span>')
    image_preview.short_description = 'Preview'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        set_protected_image_uploader(obj, "image", request.user)
        _message_image_duplicate_review(self, request, obj, "image")


# =================================
# 🔥 PRODUCT VARIANT ADMIN
# =================================

@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = [
        'product_name',
        'variant_mode',
        'variant_type',
        'value',
        'sku',
        'model_number',
        'final_price_display',
        'price_adjustment',
        'stock_quantity',
        'variant_stock_badge',
        'color_swatch',
        'variant_images_count',
        'is_active',
    ]
    list_filter = [VariantStockStatusFilter, 'variant_mode', 'variant_type', 'selector_type', 'is_default', 'is_active', 'created_at']
    search_fields = ['sku', 'value', 'name', 'model_number', 'manufacturer_sku', 'gtin', 'upc', 'ean', 'barcode', 'product__name']
    list_editable = ['price_adjustment', 'stock_quantity', 'is_active']
    readonly_fields = ['sku', 'created_at', 'updated_at']
    list_select_related = ['product']
    autocomplete_fields = ['product']
    inlines = [ProductVariantSpecificationInline, ProductVariantImageInline, VendorProductOfferInline]
    actions = ['activate_variants', 'deactivate_variants', 'mark_variants_out_of_stock']
    list_per_page = 30
    save_on_top = True

    fieldsets = (
        ('Product & Type', {
            'fields': ('product', 'variant_mode', 'variant_type', 'selector_type', 'display_order', 'is_default')
        }),
        ('Variant Details', {
            'fields': ('name', 'value', 'sku', 'slug', 'model_number', 'manufacturer_sku', 'gtin', 'upc', 'ean', 'barcode')
        }),
        ('Full Variant Content Overrides', {
            'fields': ('short_description', 'description', 'specifications', 'key_features', 'compatibility_notes', 'included_accessories', 'recommended_use'),
            'classes': ('collapse',),
        }),
        ('Pricing & Stock', {
            'fields': ('price_adjustment', 'stock_quantity', 'is_active')
        }),
        ('Main Variant Image / Color', {
            'fields': ('image', 'hover_image', 'color_code', 'manual_pdf', 'video_type', 'video_url', 'local_video', 'video_thumbnail', 'video_title'),
            'description': 'This is only the main variant image. Add the full variant gallery below under Variant Images.',
        }),
        ('Physical & Warranty Overrides', {
            'fields': ('weight', 'weight_unit', 'dimensions_length', 'dimensions_width', 'dimensions_height', 'dimension_unit', 'warranty_years', 'warranty_description', 'extended_warranty_available'),
            'classes': ('collapse',),
        }),
        ('SEO Overrides', {
            'fields': ('meta_title', 'meta_description', 'meta_keywords', 'canonical_override', 'is_indexable'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def product_name(self, obj):
        return obj.product.name
    product_name.short_description = 'Product'
    product_name.admin_order_field = 'product__name'

    def color_swatch(self, obj):
        if obj.color_code:
            return format_html(
                '<span title="{}" style="display:inline-block;width:22px;height:22px;border-radius:999px;border:1px solid #d1d5db;background:{};"></span>',
                obj.color_code,
                obj.color_code
            )
        return '-'
    color_swatch.short_description = 'Color'

    def final_price_display(self, obj):
        return format_html('<strong>{}</strong>', obj.final_price)
    final_price_display.short_description = 'Final Price'

    def variant_stock_badge(self, obj):
        if not obj.is_active:
            label, color = 'Inactive', '#6b7280'
        elif obj.stock_quantity <= 0:
            label, color = 'Out', '#dc2626'
        else:
            label, color = 'Available', '#059669'
        return format_html(
            '<span style="background: {}; color: #fff; padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 700;">{}</span>',
            color,
            label
        )
    variant_stock_badge.short_description = 'Stock Status'

    def variant_images_count(self, obj):
        count = obj.images.count()
        if count:
            return format_html(
                '<span style="color:#059669;font-weight:700;">{} image{}</span>',
                count,
                '' if count == 1 else 's'
            )
        return format_html('<span style="color:#dc2626;font-weight:700;">0 images</span>')
    variant_images_count.short_description = 'Gallery Images'

    def activate_variants(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} variant(s) activated.")
    activate_variants.short_description = 'Activate variants'

    def deactivate_variants(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} variant(s) deactivated.")
    deactivate_variants.short_description = 'Deactivate variants'

    def mark_variants_out_of_stock(self, request, queryset):
        updated = queryset.update(stock_quantity=0)
        self.message_user(request, f"{updated} variant(s) marked out of stock.")
    mark_variants_out_of_stock.short_description = 'Mark variants out of stock'


# =================================
# 🔥 PRODUCT VARIANT IMAGE ADMIN
# =================================

@admin.register(ProductVariantImage)
class ProductVariantImageAdmin(admin.ModelAdmin):
    list_display = ['variant_display', 'image_type', 'title', 'is_primary', 'sort_order', 'is_active', 'image_preview']
    list_filter = ['image_type', 'is_primary', 'is_active', 'created_at']
    list_editable = ['sort_order', 'is_primary', 'is_active']
    search_fields = ['variant__product__name', 'variant__value', 'title', 'alt_text']
    autocomplete_fields = ['variant']
    list_select_related = ['variant', 'variant__product']
    list_per_page = 50
    
    def variant_display(self, obj):
        return f"{obj.variant.product.name} - {obj.variant.value}"
    variant_display.short_description = 'Variant'
    
    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="50" height="50" style="object-fit: cover; border-radius: 4px;" />', 
                obj.image.url
            )
        return mark_safe('<span style="color: #9ca3af;">No Image</span>')
    image_preview.short_description = 'Preview'


@admin.register(ProductVariantSpecification)
class ProductVariantSpecificationAdmin(admin.ModelAdmin):
    list_display = ['variant_display', 'group', 'name', 'value_preview', 'unit', 'display_order', 'is_highlight', 'is_active']
    list_filter = ['group', 'is_highlight', 'is_active']
    list_editable = ['display_order', 'is_highlight', 'is_active']
    search_fields = ['variant__product__name', 'variant__value', 'group', 'name', 'value']
    autocomplete_fields = ['variant']
    list_select_related = ['variant', 'variant__product']

    def variant_display(self, obj):
        return f"{obj.variant.product.name} - {obj.variant.value}"
    variant_display.short_description = 'Variant'

    def value_preview(self, obj):
        value = str(obj.value or '')
        return value[:80] + ('...' if len(value) > 80 else '')
    value_preview.short_description = 'Value'


@admin.register(VendorProductOffer)
class VendorProductOfferAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'vendor', 'price', 'sale_price', 'stock_quantity', 'available_stock', 'condition', 'approval_status', 'is_featured', 'is_preferred', 'is_active']
    list_filter = ['approval_status', 'condition', 'fulfilment_method', 'is_featured', 'is_preferred', 'is_active', 'created_at']
    list_editable = ['price', 'sale_price', 'stock_quantity', 'approval_status', 'is_featured', 'is_preferred', 'is_active']
    search_fields = ['product__name', 'variant__value', 'variant__sku', 'seller_sku', 'vendor__store_name', 'vendor__company_name']
    autocomplete_fields = ['vendor', 'product', 'variant']
    list_select_related = ['vendor', 'product', 'variant']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Catalog Item', {
            'fields': ('vendor', 'product', 'variant', 'seller_sku')
        }),
        ('Offer Commercials', {
            'fields': ('price', 'sale_price', 'currency', 'stock_quantity', 'reserved_quantity', 'condition', 'fulfilment_method')
        }),
        ('Seller Terms', {
            'fields': ('seller_warranty', 'return_policy', 'delivery_note', 'lead_time_days')
        }),
        ('Status & Visibility', {
            'fields': ('approval_status', 'approval_notes', 'is_featured', 'is_preferred', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ProductCatalogRequest)
class ProductCatalogRequestAdmin(admin.ModelAdmin):
    list_display = ['title', 'request_type', 'vendor', 'product', 'status', 'brand_name', 'model_number', 'created_at']
    list_filter = ['request_type', 'status', 'created_at']
    search_fields = [
        'title',
        'brand_name',
        'model_number',
        'manufacturer_sku',
        'gtin',
        'upc',
        'ean',
        'barcode',
        'vendor__business_name',
        'vendor__store_name',
        'product__name',
    ]
    autocomplete_fields = ['vendor', 'requested_by', 'product', 'resulting_product', 'resulting_variant', 'reviewed_by']
    readonly_fields = ['created_at', 'updated_at', 'reviewed_at']
    fieldsets = (
        ('Request', {
            'fields': ('vendor', 'requested_by', 'request_type', 'status', 'product')
        }),
        ('Requested Catalog Data', {
            'fields': (
                'title',
                'brand_name',
                'model_number',
                'manufacturer_sku',
                'gtin',
                'upc',
                'ean',
                'barcode',
                'requested_attributes',
                'description',
                'vendor_note',
            )
        }),
        ('Review Outcome', {
            'fields': ('resulting_product', 'resulting_variant', 'admin_notes', 'reviewed_by', 'reviewed_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# =================================
# 🔥 PRODUCT VIDEO ADMIN
# =================================

@admin.register(ProductVideo)
class ProductVideoAdmin(admin.ModelAdmin):
    list_display = ['product_name', 'title', 'source', 'is_main', 'display_order']
    list_filter = ['source', 'is_main', 'created_at']
    list_editable = ['display_order', 'is_main']
    search_fields = ['product__name', 'title']
    list_select_related = ['product']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('product', 'title', 'description', 'source')
        }),
        ('Video Source', {
            'fields': ('youtube_url', 'vimeo_url', 'local_video')
        }),
        ('Media', {
            'fields': ('thumbnail', 'is_main'),
            'classes': ('collapse',)
        }),
        ('Display', {
            'fields': ('display_order',),
            'classes': ('collapse',)
        }),
    )
    
    def product_name(self, obj):
        return obj.product.name
    product_name.short_description = 'Product'


# =================================
# 🔥 PRODUCT REVIEW ADMIN
# =================================

@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ['product_name', 'user_name', 'rating_display', 'title', 'verified_purchase', 'helpful_count', 'created_at']
    list_filter = ['rating', 'verified_purchase', 'created_at']
    search_fields = ['product__name', 'user__username', 'title', 'review']
    readonly_fields = ['helpful_count', 'unhelpful_count', 'created_at', 'updated_at']
    list_select_related = ['product', 'user']
    inlines = [ReviewVideoInline]
    list_per_page = 25
    
    fieldsets = (
        ('Review Information', {
            'fields': ('product', 'user', 'rating', 'title', 'review')
        }),
        ('Verification & Engagement', {
            'fields': ('verified_purchase', 'helpful_count', 'unhelpful_count')
        }),
        ('Media', {
            'fields': ('video_review',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def product_name(self, obj):
        return obj.product.name
    product_name.short_description = 'Product'
    
    def user_name(self, obj):
        return obj.user.username
    user_name.short_description = 'User'
    
    def rating_display(self, obj):
        return format_html(
            '<span style="color: #f59e0b; font-weight: bold;">{} ★</span>',
            obj.rating
        )
    rating_display.short_description = 'Rating'
    
    actions = ['mark_as_verified', 'mark_as_unverified']
    
    def mark_as_verified(self, request, queryset):
        queryset.update(verified_purchase=True)
        self.message_user(request, f"✓ {queryset.count()} reviews marked as verified.")
    mark_as_verified.short_description = "✓ Mark as verified purchase"
    
    def mark_as_unverified(self, request, queryset):
        queryset.update(verified_purchase=False)
        self.message_user(request, f"✗ {queryset.count()} reviews marked as unverified.")
    mark_as_unverified.short_description = "✗ Mark as unverified purchase"


# =================================
# 🔥 PRODUCT Q&A ADMIN
# =================================

@admin.register(ProductQnA)
class ProductQnAAdmin(admin.ModelAdmin):
    list_display = ['product_name', 'user_name', 'question_preview', 'has_answer', 'is_public', 'created_at']
    list_filter = ['is_public', 'created_at', 'answered_at']
    search_fields = ['product__name', 'user__username', 'question', 'answer']
    readonly_fields = ['answered_at', 'created_at', 'updated_at']
    list_select_related = ['product', 'user', 'answered_by']
    list_per_page = 25
    
    fieldsets = (
        ('Question', {
            'fields': ('product', 'user', 'question', 'is_public')
        }),
        ('Answer', {
            'fields': ('answer', 'answered_by', 'answered_at'),
        }),
        ('Engagement', {
            'fields': ('helpful_count',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def product_name(self, obj):
        return obj.product.name
    product_name.short_description = 'Product'
    
    def user_name(self, obj):
        return obj.user.username
    user_name.short_description = 'User'
    
    def question_preview(self, obj):
        return obj.question[:50] + "..." if len(obj.question) > 50 else obj.question
    question_preview.short_description = 'Question'
    
    def has_answer(self, obj):
        return bool(obj.answer and obj.answered_at)
    has_answer.boolean = True
    has_answer.short_description = 'Answered'


# =================================
# 🔥 REVIEW VIDEO ADMIN
# =================================

@admin.register(ReviewVideo)
class ReviewVideoAdmin(admin.ModelAdmin):
    list_display = ['review_display', 'title', 'is_main', 'created_at']
    list_filter = ['is_main', 'created_at']
    list_editable = ['is_main']
    list_select_related = ['review', 'review__product', 'review__user']
    
    def review_display(self, obj):
        return f"{obj.review.product.name} - {obj.review.user.username}"
    review_display.short_description = 'Review'


# =================================
# 🔥 MANUFACTURER WARRANTY ADMIN
# =================================

@admin.register(ManufacturerWarranty)
class ManufacturerWarrantyAdmin(admin.ModelAdmin):
    list_display = ['product_name', 'provider', 'duration_text', 'registration_required', 'customer_support_phone']
    list_filter = ['registration_required', 'duration_years', 'created_at']
    search_fields = ['product__name', 'provider', 'customer_support_email']
    raw_id_fields = ['product']
    list_select_related = ['product']
    
    fieldsets = (
        ('Warranty Information', {
            'fields': ('product', 'provider', 'duration_years', 'duration_months', 'coverage_details', 'exclusions')
        }),
        ('Registration', {
            'fields': ('registration_required', 'registration_url'),
        }),
        ('Support', {
            'fields': ('terms_url', 'customer_support_phone', 'customer_support_email'),
        }),
    )
    
    def product_name(self, obj):
        return obj.product.name
    product_name.short_description = 'Product'
    
    def duration_text(self, obj):
        years = obj.duration_years or 0
        months = obj.duration_months or 0
        if years > 0 and months > 0:
            return f"{years} year{'s' if years > 1 else ''} {months} month{'s' if months > 1 else ''}"
        elif years > 0:
            return f"{years} year{'s' if years > 1 else ''}"
        elif months > 0:
            return f"{months} month{'s' if months > 1 else ''}"
        return "Not specified"
    duration_text.short_description = 'Duration'


# =================================
# 🔥 SHIPPING INFO ADMIN
# =================================

@admin.register(ShippingInfo)
class ShippingInfoAdmin(admin.ModelAdmin):
    list_display = ['product_name', 'weight_shipping', 'free_shipping', 'estimated_delivery_range', 'hazmat']
    list_filter = ['free_shipping', 'hazmat', 'created_at']
    search_fields = ['product__name']
    raw_id_fields = ['product']
    list_select_related = ['product']
    
    fieldsets = (
        ('Product', {
            'fields': ('product',)
        }),
        ('Weight', {
            'fields': ('weight_shipping',)
        }),
        ('Package Information', {
            'fields': ('dimensions_package', 'hazmat'),
        }),
        ('Delivery', {
            'fields': ('free_shipping', 'estimated_delivery_days_min', 'estimated_delivery_days_max'),
        }),
        ('Restrictions', {
            'fields': ('shipping_restrictions',),
            'classes': ('collapse',)
        }),
    )
    
    def product_name(self, obj):
        return obj.product.name
    product_name.short_description = 'Product'
    
    def estimated_delivery_range(self, obj):
        if obj.estimated_delivery_days_min and obj.estimated_delivery_days_max:
            return f"{obj.estimated_delivery_days_min}-{obj.estimated_delivery_days_max} days"
        return "Not specified"
    estimated_delivery_range.short_description = 'Delivery Time'


# =================================
# 🔥 WISHLIST ADMIN
# =================================

@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ['user_name', 'product_name', 'added_at']
    list_filter = ['added_at']
    search_fields = ['user__username', 'product__name']
    readonly_fields = ['added_at', 'created_at', 'updated_at']
    list_select_related = ['user', 'product']
    list_per_page = 50
    
    def user_name(self, obj):
        return obj.user.username
    user_name.short_description = 'User'
    
    def product_name(self, obj):
        return obj.product.name
    product_name.short_description = 'Product'


# =================================
# 🔥 RECENTLY VIEWED ADMIN
# =================================

@admin.register(RecentlyViewed)
class RecentlyViewedAdmin(admin.ModelAdmin):
    list_display = ['user_name', 'product_name', 'viewed_at']
    list_filter = ['viewed_at']
    search_fields = ['user__username', 'product__name']
    readonly_fields = ['viewed_at', 'created_at', 'updated_at']
    list_select_related = ['user', 'product']
    list_per_page = 50
    
    def user_name(self, obj):
        return obj.user.username
    user_name.short_description = 'User'
    
    def product_name(self, obj):
        return obj.product.name
    product_name.short_description = 'Product'

@admin.register(ProductListingBanner)
class ProductListingBannerAdmin(OptionalColorFieldAdminMixin, admin.ModelAdmin):
    optional_color_fields = {
        "primary_color",
        "secondary_color",
        "cta_background_color",
        "cta_text_color",
    }
    list_display = [
        "title",
        "placement",
        "is_active",
        "display_order",
        "banner_preview",
        "created_at",
    ]
    list_editable = ["is_active", "display_order"]
    list_filter = ["placement", "is_active", "created_at"]
    search_fields = ["title", "subtitle", "eyebrow"]
    readonly_fields = ["banner_preview", "created_at", "updated_at"]

    fieldsets = (
        ("Banner Content", {
            "fields": (
                "placement",
                "eyebrow",
                "title",
                "subtitle",
                ("show_eyebrow", "show_title", "show_subtitle"),
                ("show_metrics", "show_cta", "show_side_image"),
            ),
            "description": "Turn off text/metrics/CTA when the uploaded banner artwork already contains them."
        }),
        ("Images", {
            "fields": ("background_image", "side_image", "banner_preview"),
            "description": "Recommended background image size: 1920x700."
        }),
        ("Call To Action", {
            "fields": ("cta_text", "cta_link", ("cta_background_color", "cta_text_color")),
            "description": "CTA colors are optional hex values like #2563eb and #ffffff."
        }),
        ("Metrics", {
            "fields": (
                ("metric_one_icon", "metric_one_text"),
                ("metric_two_icon", "metric_two_text"),
                ("metric_three_icon", "metric_three_text"),
            )
        }),
        ("Design Colors", {
            "fields": ("primary_color", "secondary_color")
        }),
        ("Publishing", {
            "fields": ("is_active", "display_order")
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )

    def banner_preview(self, obj):
        if obj.background_image:
            return format_html(
                '<img src="{}" style="width:320px;height:120px;object-fit:cover;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.15);" />',
                obj.background_image.url
            )
        return mark_safe('<span style="color:#9ca3af;">No banner image uploaded</span>')

    banner_preview.short_description = "Preview"


# =================================
# 🔥 ADMIN SITE CONFIGURATION
# =================================

admin.site.site_header = "🛍️ Arolana Product Management"
admin.site.site_title = "Arolana Products"
admin.site.index_title = "Welcome to Arolana Product Dashboard"
