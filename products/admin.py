from django.contrib import admin
from django.utils.html import format_html
from django import forms
from django_ckeditor_5.widgets import CKEditor5Widget
from .models import (
    Category, Brand, Product, ProductImage, ProductVariant, 
    ProductVariantImage, ProductReview, RecentlyViewed, 
    Wishlist, ProductVideo, ReviewVideo, ProductQnA
)

class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'
        widgets = {
            'description': CKEditor5Widget(config_name='default'),
            'specifications': CKEditor5Widget(config_name='default'),
        }

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ['image', 'alt_text', 'is_main', 'order']
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="100" height="100" style="object-fit: cover;" />', obj.image.url)
        return "No Image"
    image_preview.short_description = 'Preview'

class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    fields = ['variant_type', 'name', 'value', 'price_adjustment', 'stock_quantity', 'is_active']
    readonly_fields = ['sku']

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'parent', 'order', 'is_active', 'image_preview']
    list_filter = ['is_active', 'parent']
    search_fields = ['name']
    prepopulated_fields = {'slug': ['name']}
    list_editable = ['order', 'is_active']
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="50" height="50" style="object-fit: cover; border-radius: 4px;" />', obj.image.url)
        return "No Image"
    image_preview.short_description = 'Preview'

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'logo_preview', 'is_active']
    search_fields = ['name']
    prepopulated_fields = {'slug': ['name']}
    list_filter = ['is_active']
    
    def logo_preview(self, obj):
        if obj.logo:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%; object-fit: cover;" />', obj.logo.url)
        return "No Logo"
    logo_preview.short_description = 'Logo'

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = ['sku', 'name', 'price', 'stock_quantity', 'is_featured', 'is_active', 'image_preview']
    list_filter = ['is_active', 'is_featured', 'is_new', 'is_bestseller', 'category', 'brand']
    search_fields = ['sku', 'name', 'description']
    prepopulated_fields = {'slug': ['name']}
    readonly_fields = ['views_count', 'sales_count', 'rating_avg', 'rating_count', 'created_at', 'updated_at']
    inlines = [ProductImageInline, ProductVariantInline]
    
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
            'fields': ('stock_quantity', 'low_stock_threshold', 'is_in_stock', 'allow_backorder')
        }),
        ('Media', {
            'fields': ('main_image', 'video_url')
        }),
        ('SEO', {
            'fields': ('meta_title', 'meta_description', 'meta_keywords'),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('views_count', 'sales_count', 'rating_avg', 'rating_count'),
            'classes': ('collapse',)
        }),
        ('Features', {
            'fields': ('is_featured', 'is_new', 'is_bestseller', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def image_preview(self, obj):
        if obj.main_image:
            return format_html('<img src="{}" width="80" height="80" style="object-fit: cover; border-radius: 4px;" />', obj.main_image.url)
        return "No Image"
    image_preview.short_description = 'Preview'
    
    actions = ['mark_as_featured', 'mark_as_unfeatured']
    
    def mark_as_featured(self, request, queryset):
        queryset.update(is_featured=True)
    mark_as_featured.short_description = "Mark selected products as featured"
    
    def mark_as_unfeatured(self, request, queryset):
        queryset.update(is_featured=False)
    mark_as_unfeatured.short_description = "Unmark selected products as featured"

@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ['product', 'is_main', 'order', 'image_preview']
    list_filter = ['is_main', 'product']
    list_editable = ['order', 'is_main']
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="50" height="50" style="object-fit: cover;" />', obj.image.url)
        return "No Image"
    image_preview.short_description = 'Preview'

@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ['product', 'variant_type', 'name', 'value', 'sku', 'price_adjustment', 'stock_quantity', 'is_active']
    list_filter = ['variant_type', 'is_active', 'product']
    search_fields = ['sku', 'value']
    list_editable = ['price_adjustment', 'stock_quantity', 'is_active']
    readonly_fields = ['sku']

@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ['product', 'user', 'rating', 'title', 'verified_purchase', 'helpful_count', 'created_at', 'is_active']
    list_filter = ['rating', 'verified_purchase', 'is_active']
    search_fields = ['product__name', 'user__username', 'title']
    readonly_fields = ['helpful_count', 'created_at']
    
    actions = ['mark_as_verified', 'mark_as_unverified']
    
    def mark_as_verified(self, request, queryset):
        queryset.update(verified_purchase=True)
    mark_as_verified.short_description = "Mark as verified purchase"
    
    def mark_as_unverified(self, request, queryset):
        queryset.update(verified_purchase=False)
    mark_as_unverified.short_description = "Mark as unverified purchase"

@admin.register(ProductQnA)
class ProductQnAAdmin(admin.ModelAdmin):
    list_display = ['product', 'user', 'question_preview', 'has_answer', 'created_at', 'is_active']
    list_filter = ['is_active']  # Removed 'is_answered' since it's a method
    search_fields = ['product__name', 'user__username', 'question']
    
    def question_preview(self, obj):
        return obj.question[:50] + "..." if len(obj.question) > 50 else obj.question
    question_preview.short_description = 'Question'
    
    def has_answer(self, obj):
        return bool(obj.answer)
    has_answer.boolean = True
    has_answer.short_description = 'Answered'

@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ['user', 'product', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'product__name']

@admin.register(RecentlyViewed)
class RecentlyViewedAdmin(admin.ModelAdmin):
    list_display = ['user', 'product', 'viewed_at']
    list_filter = ['viewed_at']
    search_fields = ['user__username', 'product__name']
    readonly_fields = ['viewed_at']