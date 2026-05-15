from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django import forms
from django_ckeditor_5.widgets import CKEditor5Widget
from django.db.models import Q
from .models import (
    Category, Brand, Product, ProductImage, ProductVariant, 
    ProductVariantImage, ProductReview, RecentlyViewed, 
    Wishlist, ProductVideo, ReviewVideo, ProductQnA,
    Accessory, AccessoryProduct, ManufacturerWarranty, ShippingInfo
)

from django.utils.timezone import now


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


# =================================
# 🔥 INLINE ADMINS
# =================================

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
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
    fields = ['variant_type', 'name', 'value', 'price_adjustment', 'stock_quantity', 'image', 'color_code', 'is_active']
    readonly_fields = ['sku']


class ProductVariantImageInline(admin.TabularInline):
    model = ProductVariantImage
    extra = 1
    fields = ['image', 'alt_text', 'is_main', 'order', 'image_preview']
    readonly_fields = ['image_preview']

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="64" height="64" style="object-fit: cover; border-radius: 4px;" />',
                obj.image.url
            )
        return mark_safe('<span style="color: #9ca3af;">No Image</span>')
    image_preview.short_description = 'Preview'


class ProductVideoInline(admin.TabularInline):
    model = ProductVideo
    extra = 1
    fields = ['title', 'description', 'source', 'youtube_url', 'vimeo_url', 'local_video', 'thumbnail', 'is_main', 'display_order']


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
    list_display = ['sku', 'name', 'price', 'stock_quantity', 'approval_status_badge', 'is_featured', 'is_active', 'image_preview']
    list_filter = ['is_active', 'is_featured', 'is_new', 'is_bestseller', 'category', 'brand', 'approval_status', 'created_at']
    search_fields = ['sku', 'name', 'description']
    prepopulated_fields = {'slug': ['name']}
    readonly_fields = ['views_count', 'sales_count', 'rating_avg', 'rating_count', 'created_at', 'updated_at', 'sku', 'submitted_for_review_at', 'approved_at']
    inlines = [ProductImageInline, ProductVariantInline, ProductVideoInline, AccessoryInline, ManufacturerWarrantyInline, ShippingInfoInline]
    autocomplete_fields = ['vendor', 'category', 'brand']
    list_select_related = ['category', 'brand', 'vendor']
    list_per_page = 25
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('sku', 'name', 'slug', 'category', 'brand', 'vendor')
        }),
        ('Description & Specifications', {
            'fields': ('description', 'specifications'),
            'description': 'Use the rich text editor to add formatted content'
        }),
        ('Pricing', {
            'fields': ('price', 'compare_price', 'cost_per_item')
        }),
        ('Inventory', {
            'fields': ('stock_quantity', 'reserved_quantity', 'low_stock_threshold', 'is_in_stock', 'allow_backorder')
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
            'fields': ('main_image', 'video_type', 'video_url', 'local_video', 'video_thumbnail', 'video_title'),
            'description': 'Add product images and videos (YouTube, Vimeo, or local MP4)'
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
    
    actions = ['mark_as_featured', 'mark_as_unfeatured', 'activate_products', 'deactivate_products', 'approve_products', 'reject_products']
    
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


# =================================
# 🔥 CATEGORY ADMIN
# =================================

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'parent', 'order', 'is_active', 'image_preview', 'has_background_status', 'product_count_display']
    list_filter = ['is_active', 'parent']
    search_fields = ['name', 'slug', 'description']
    prepopulated_fields = {'slug': ['name']}
    list_editable = ['order', 'is_active']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'parent', 'order', 'is_active')
        }),
        ('Category Images', {
            'fields': ('image', 'background_image'),
            'description': 'Image for category card (thumbnail) and hero background image for landing page'
        }),
        ('Hero Section', {
            'fields': ('hero_title', 'hero_subtitle'),
            'description': 'Customize the hero section on the category landing page',
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


# =================================
# 🔥 PRODUCT VARIANT ADMIN
# =================================

@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ['product_name', 'variant_type', 'value', 'sku', 'price_adjustment', 'stock_quantity', 'color_swatch', 'is_active']
    list_filter = ['variant_type', 'is_active', 'created_at']
    search_fields = ['sku', 'value', 'product__name']
    list_editable = ['price_adjustment', 'stock_quantity', 'is_active']
    readonly_fields = ['sku', 'created_at', 'updated_at']
    list_select_related = ['product']
    inlines = [ProductVariantImageInline]
    
    def product_name(self, obj):
        return obj.product.name
    product_name.short_description = 'Product'
    
    fieldsets = (
        ('Product & Type', {
            'fields': ('product', 'variant_type')
        }),
        ('Variant Details', {
            'fields': ('name', 'value', 'sku')
        }),
        ('Pricing & Stock', {
            'fields': ('price_adjustment', 'stock_quantity', 'is_active')
        }),
        ('Media', {
            'fields': ('image', 'color_code'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def color_swatch(self, obj):
        if obj.color_code:
            return format_html(
                '<span style="display:inline-block;width:22px;height:22px;border-radius:999px;border:1px solid #d1d5db;background:{};"></span>',
                obj.color_code
            )
        return "-"
    color_swatch.short_description = 'Color'


# =================================
# 🔥 PRODUCT VARIANT IMAGE ADMIN
# =================================

@admin.register(ProductVariantImage)
class ProductVariantImageAdmin(admin.ModelAdmin):
    list_display = ['variant_display', 'is_main', 'order', 'image_preview']
    list_filter = ['is_main', 'created_at']
    list_editable = ['order', 'is_main']
    list_select_related = ['variant', 'variant__product']
    
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


# =================================
# 🔥 ADMIN SITE CONFIGURATION
# =================================

admin.site.site_header = "🛍️ Arolana Product Management"
admin.site.site_title = "Arolana Products"
admin.site.index_title = "Welcome to Arolana Product Dashboard"
