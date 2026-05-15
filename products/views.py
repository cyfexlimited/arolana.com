from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Avg, Count, Sum, Prefetch, F
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.db import transaction
import json
from django.http import HttpResponse
from decimal import Decimal
from django.template.loader import render_to_string
from .models import (
    Product, Category, ProductReview, Wishlist, RecentlyViewed, 
    ProductVariant, ProductQuestion, Accessory, AccessoryProduct,
    ProductImage, ProductVideo, ProductVariantImage, Brand
)
from accounts.models import User
from currency.templatetags.currency_filters import currency as format_currency

try:
    from subscriptions.models import user_has_paid_subscription
except ImportError:
    def user_has_paid_subscription(user):
        return False

# Note: Adjust import based on your actual orders app structure
try:
    from orders.models import Cart, CartItem
except ImportError:
    Cart = None
    CartItem = None

try:
    from currency.models import Currency
    from currency.utils.exchange_rates import CurrencyConverter
except ImportError:
    Currency = None
    CurrencyConverter = None


# ================================
# 🔥 HELPER FUNCTIONS
# ================================

def get_user_currency(request):
    """Get user's active currency with fallback to base currency"""
    if not Currency:
        return None
    
    user_currency = getattr(request, 'user_currency', None)
    
    if user_currency and isinstance(user_currency, str):
        user_currency = Currency.objects.filter(
            code=user_currency, 
            is_active=True
        ).first()
    
    if not user_currency:
        user_currency = Currency.objects.filter(is_base=True).first()
    
    return user_currency


def convert_price(price, from_currency, to_currency):
    """Convert price between currencies safely"""
    if not price or not from_currency or not to_currency or not CurrencyConverter:
        return price
    
    if from_currency.code == to_currency.code:
        return price
    
    try:
        return CurrencyConverter.convert(price, from_currency, to_currency)
    except Exception:
        return price


def get_paginated_items(queryset, page_num, per_page=24):
    """Get paginated items with error handling"""
    paginator = Paginator(queryset, per_page)
    try:
        return paginator.page(page_num)
    except (PageNotAnInteger, EmptyPage):
        return paginator.page(1)


def apply_filters(queryset, request):
    """Apply all filters to queryset"""
    
    # ====== Category Filter ======
    categories = request.GET.getlist('categories')
    if categories:
        category_slugs = []
        for cat in categories:
            category_slugs.extend([c.strip() for c in cat.split(',') if c.strip()])
        if category_slugs:
            queryset = queryset.filter(category__slug__in=category_slugs)
    
    # ====== Price Range Filter ======
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    
    if min_price:
        try:
            queryset = queryset.filter(price__gte=Decimal(min_price))
        except (ValueError, TypeError):
            pass
    
    if max_price:
        try:
            queryset = queryset.filter(price__lte=Decimal(max_price))
        except (ValueError, TypeError):
            pass
    
    # ====== Brand Filter ======
    brands = request.GET.getlist('brands')
    if brands:
        brand_slugs = []
        for b in brands:
            brand_slugs.extend([s.strip() for s in b.split(',') if s.strip()])
        if brand_slugs:
            queryset = queryset.filter(brand__slug__in=brand_slugs)
    
    # ====== Rating Filter ======
    min_rating = request.GET.get('rating')
    if min_rating:
        try:
            queryset = queryset.filter(rating_avg__gte=int(min_rating))
        except (ValueError, TypeError):
            pass
    
    # ====== Stock Filter ======
    in_stock = request.GET.get('in_stock')
    if in_stock == 'true':
        queryset = queryset.filter(stock_quantity__gt=0)
    
    # ====== Free Shipping Filter ======
    free_shipping = request.GET.get('free_shipping')
    if free_shipping == 'true':
        queryset = queryset.filter(shipping_info__free_shipping=True)
    
    return queryset


def get_filter_counts(queryset):
    """Get count of products for each filter option (from filtered results)"""
    categories = Category.objects.filter(is_active=True, parent=None)
    brands = Brand.objects.filter(is_active=True)
    
    category_counts = {}
    for category in categories:
        count = queryset.filter(category=category).count()
        category_counts[category.slug] = count
    
    brand_counts = {}
    for brand in brands:
        count = queryset.filter(brand=brand).count()
        brand_counts[brand.slug] = count
    
    return {
        'categories': category_counts,
        'brands': brand_counts,
    }


# ================================
# 🔥 CART VIEWS (Optional)
# ================================

@login_required
@transaction.atomic
def add_to_cart(request, slug):
    """Add product to cart with variant and accessory support"""
    if not Cart or not CartItem:
        return redirect('products:detail', slug=slug)
    
    product = get_object_or_404(Product, slug=slug, is_active=True, approval_status='approved')
    
    # Get parameters
    quantity = int(request.POST.get('quantity', request.GET.get('quantity', 1)))
    variant_id = request.POST.get('variant_id') or request.GET.get('variant_id')
    accessory_ids = request.POST.getlist('accessories') or request.GET.getlist('accessories')
    
    # Validate quantity
    if quantity < 1:
        quantity = 1
    elif quantity > 999:
        quantity = 999
    
    # Get or create cart
    cart, created = Cart.objects.get_or_create(user=request.user, is_active=True)
    
    # ====== Handle Product ======
    price = product.price
    variant = None
    
    if variant_id:
        try:
            variant = ProductVariant.objects.get(
                id=variant_id,
                product=product,
                is_active=True
            )
            price = variant.final_price
            
            # Check variant stock
            if variant.stock_quantity < quantity:
                messages.error(
                    request, 
                    f"Only {variant.stock_quantity} {variant.value} available!"
                )
                return redirect('products:detail', slug=product.slug)
        except ProductVariant.DoesNotExist:
            messages.error(request, 'Selected variant not found.')
            return redirect('products:detail', slug=product.slug)
    else:
        # Check product stock
        available = product.get_available_stock()
        if available < quantity:
            messages.error(
                request,
                f"Only {available} items available!"
            )
            return redirect('products:detail', slug=product.slug)
    
    # Get or create cart item
    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        variant=variant,
        defaults={
            'quantity': quantity,
            'price_at_add': price
        }
    )
    
    if not created:
        # Check if new total exceeds stock
        stock = variant.stock_quantity if variant else product.get_available_stock()
        if cart_item.quantity + quantity > stock:
            messages.error(
                request,
                f"Cannot add more than {stock} items!"
            )
            return redirect('products:detail', slug=product.slug)
        
        cart_item.quantity += quantity
        cart_item.save(update_fields=['quantity'])
        message = f'Updated {product.name} quantity in cart!'
    else:
        message = f'Added {product.name} to cart!'
    
    # ====== Handle Accessories ======
    if accessory_ids:
        accessories = Accessory.objects.filter(
            id__in=accessory_ids,
            is_active=True
        )
        
        for accessory in accessories:
            acc_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product=None,
                accessory=accessory,
                defaults={
                    'quantity': 1,
                    'price_at_add': accessory.price
                }
            )
            
            if not created:
                acc_item.quantity += 1
                acc_item.save(update_fields=['quantity'])
    
    messages.success(request, message)
    request.session['cart_count'] = cart.total_items if hasattr(cart, 'total_items') else 0
    
    # ====== AJAX Response ======
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': message,
            'cart_count': getattr(cart, 'total_items', 0),
            'variant_selected': variant.value if variant else None
        })
    
    # ====== Redirect ======
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url:
        return redirect(next_url)
    
    return redirect('products:cart')


@login_required
def cart_view(request):
    """Display shopping cart with currency conversion"""
    if not Cart or not CartItem:
        return render(request, 'products/cart.html', {'cart': None, 'error': 'Cart feature not available'})
    
    cart, created = Cart.objects.get_or_create(
        user=request.user,
        is_active=True
    )
    request.session['cart_count'] = getattr(cart, 'total_items', 0)
    
    # Get currencies
    user_currency = get_user_currency(request)
    base_currency = Currency.objects.filter(is_base=True).first() if Currency else None
    
    # Calculate converted totals
    subtotal_converted = Decimal('0.00')
    
    for item in cart.items.all():
        converted_price = convert_price(
            item.price_at_add,
            base_currency,
            user_currency
        )
        
        item.converted_price = converted_price
        item.converted_subtotal = converted_price * item.quantity
        subtotal_converted += item.converted_subtotal
    
    total_converted = subtotal_converted
    
    return render(request, 'products/cart.html', {
        'cart': cart,
        'subtotal_converted': subtotal_converted,
        'total_converted': total_converted,
        'user_currency': user_currency,
        'base_currency': base_currency,
    })


@login_required
@require_http_methods(["POST"])
def update_cart(request):
    """Update cart item quantity"""
    if not CartItem:
        return JsonResponse({'success': False, 'error': 'Cart feature not available'}, status=400)
    
    try:
        item_id = request.POST.get('item_id')
        quantity = int(request.POST.get('quantity', 1))
        
        if quantity < 0:
            quantity = 0
        elif quantity > 999:
            quantity = 999
        
        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        
        if quantity <= 0:
            cart_item.delete()
            return JsonResponse({'success': True, 'deleted': True})
        
        cart_item.quantity = quantity
        cart_item.save(update_fields=['quantity'])
        
        return JsonResponse({'success': True})
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid quantity'}, status=400)


@login_required
def remove_from_cart(request, item_id):
    """Remove item from cart"""
    if not CartItem:
        return redirect('products:cart')
    
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    cart = cart_item.cart
    cart_item.delete()
    
    request.session['cart_count'] = getattr(cart, 'total_items', 0)
    messages.success(request, 'Item removed from cart')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'cart_count': getattr(cart, 'total_items', 0)
        })
    
    return redirect('products:cart')


# ================================
# 🔥 PRODUCT VIEWS (WITH APPROVAL SYSTEM)
# ================================

def product_list(request):
    """Display paginated product list with filtering and sorting - APPROVED ONLY"""
    products = Product.objects.filter(is_active=True, approval_status='approved').select_related(
        'category',
        'brand'
    )
    
    # ====== Apply Filters ======
    products = apply_filters(products, request)
    
    # ====== Sorting ======
    sort_param = request.GET.get('sort', 'featured')
    sort_mapping = {
        'featured': '-is_featured',
        'newest': '-created_at',
        'bestsellers': '-sales_count',
        'trending': '-views_count',
        'price_low': 'price',
        'price_high': '-price',
        'rating': '-rating_avg',
        'name_asc': 'name',
        'name_desc': '-name',
    }
    
    sort_field = sort_mapping.get(sort_param, '-is_featured')
    products = products.order_by(sort_field)
    
    # ====== Pagination ======
    paginator = Paginator(products, 24)
    page = request.GET.get('page', 1)
    try:
        products_page = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        products_page = paginator.page(1)
    
    # ====== Currency ======
    user_currency = get_user_currency(request)
    
    # ====== Prepare categories and brands for template ======
    product_count_filter = Q(products__is_active=True, products__approval_status='approved')
    categories_list = (
        Category.objects
        .filter(is_active=True, parent=None)
        .annotate(approved_product_count=Count('products', filter=product_count_filter))
        .order_by('order', 'name')
    )
    brands_list = (
        Brand.objects
        .filter(is_active=True)
        .annotate(approved_product_count=Count('products', filter=product_count_filter))
        .order_by('name')
    )
    filter_counts = {
        'categories': {category.slug: category.approved_product_count for category in categories_list},
        'brands': {brand.slug: brand.approved_product_count for brand in brands_list},
    }
    
    # ====== AJAX Request (return JSON for filtering) ======
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_to_string('products/product_grid.html', {
            'products': products_page,
            'user_currency': user_currency,
        }, request=request)
        
        return JsonResponse({
            'html': html,
            'total_count': paginator.count,
            'start_index': products_page.start_index(),
            'end_index': products_page.end_index(),
        })
    
    # ====== Regular Page Load ======
    return render(request, 'products/list.html', {
        'products': products_page,
        'categories': categories_list,
        'brands': brands_list,
        'filter_counts': filter_counts,
        'current_sort': sort_param,
        'user_currency': user_currency,
        'paginator': paginator,
    })


def product_detail(request, slug):
    """Display detailed product page with reviews, Q&A, and variants - APPROVED ONLY"""
    product = get_object_or_404(
        Product.objects.select_related(
            'category',
            'brand',
            'vendor'
        ).prefetch_related(
            Prefetch('images', queryset=ProductImage.objects.filter(is_active=True).order_by('order')),
            Prefetch(
                'variants',
                queryset=ProductVariant.objects.filter(is_active=True).prefetch_related(
                    Prefetch('images', queryset=ProductVariantImage.objects.filter(is_active=True).order_by('order'))
                ),
                to_attr='active_variants'
            ),
            Prefetch('reviews', queryset=ProductReview.objects.select_related('user').order_by('-created_at')),
            Prefetch('product_accessories__accessory', queryset=Accessory.objects.filter(is_active=True)),
            'additional_videos',
            Prefetch('questions', queryset=ProductQuestion.objects.filter(is_public=True).select_related('user', 'answered_by').order_by('-created_at'))
        ),
        slug=slug,
        is_active=True,
        approval_status='approved'
    )
    
    # ====== Track Views ======
    Product.objects.filter(pk=product.id).update(views_count=F('views_count') + 1)
    
    # ====== Track Recently Viewed ======
    if request.user.is_authenticated:
        RecentlyViewed.objects.update_or_create(
            user=request.user,
            product=product,
            defaults={'viewed_at': timezone.now()}
        )
    
    # ====== Get Variants with proper grouping ======
    all_variants = list(getattr(product, 'active_variants', []))
    
    # Group variants by type
    variants_by_type = {}
    variant_options = {}
    
    for variant in all_variants:
        variant_type = variant.variant_type or 'other'
        if variant_type not in variants_by_type:
            variants_by_type[variant_type] = []
            variant_options[variant_type] = []
        
        variants_by_type[variant_type].append(variant)
        
        # Store unique values for selection
        if variant.value not in variant_options[variant_type]:
            variant_options[variant_type].append(variant.value)
    
    # Separate size and color variants for backwards-compatible template/context use
    size_variants = variants_by_type.get('size', [])
    color_variants = variants_by_type.get('color', [])

    variant_groups = []
    for variant_type, variant_label in ProductVariant.VARIANT_TYPES:
        options = variants_by_type.get(variant_type, [])
        if options:
            variant_groups.append({
                'type': variant_type,
                'label': variant_label,
                'options': options,
            })
    
    # ====== Get selected variant from URL parameter or POST ======
    selected_variant_id = request.GET.get('variant_id') or request.POST.get('variant_id')
    selected_variant = None
    selected_variant_price = product.price
    
    if selected_variant_id:
        try:
            selected_variant = next(
                variant for variant in all_variants if variant.id == int(selected_variant_id)
            )
            selected_variant_price = product.price + selected_variant.price_adjustment
        except (ProductVariant.DoesNotExist, StopIteration, ValueError, TypeError):
            pass
    
    # ====== Get Default Variant (first active variant) ======
    default_variant = all_variants[0] if all_variants else None
    if not selected_variant and default_variant:
        selected_variant = default_variant
        selected_variant_price = product.price + selected_variant.price_adjustment
    
    # ====== Calculate current price based on selected variant ======
    current_price = selected_variant_price if selected_variant else product.price
    current_compare_price = product.compare_price
    
    if selected_variant and product.compare_price:
        current_compare_price = product.compare_price + selected_variant.price_adjustment
    
    # ====== Get Accessories ======
    accessories = product.product_accessories.filter(
        accessory__is_active=True
    ).select_related('accessory')
    
    # ====== Get Videos ======
    videos = product.additional_videos.order_by('display_order')
    
    # ====== Currency Conversion ======
    user_currency = get_user_currency(request)
    base_currency = Currency.objects.filter(is_base=True).first() if Currency else None
    
    # ====== Variant Data for JavaScript ======
    def push_image(images, src, alt):
        if src and src not in {image['src'] for image in images}:
            images.append({'src': src, 'alt': alt or product.name})

    gallery_images = []
    if product.main_image:
        push_image(gallery_images, product.main_image.url, product.name)
    for image in product.images.all():
        push_image(gallery_images, image.image.url, image.alt_text or product.name)

    variant_data = {}
    for variant in all_variants:
        variant_price = product.price + variant.price_adjustment
        variant_compare_price = product.compare_price + variant.price_adjustment if product.compare_price else None
        converted_variant_price = convert_price(
            variant_price,
            base_currency,
            user_currency
        )
        variant_images = []
        push_image(variant_images, variant.image.url if variant.image else None, f"{product.name} - {variant.value}")
        for image in variant.images.all():
            push_image(variant_images, image.image.url, image.alt_text or f"{product.name} - {variant.value}")
        
        variant_data[str(variant.id)] = {
            'id': variant.id,
            'name': variant.name,
            'value': variant.value,
            'variant_type': variant.variant_type,
            'price': float(converted_variant_price),
            'price_display': format_currency(variant_price, request),
            'price_raw': float(variant_price),
            'compare_price_display': format_currency(variant_compare_price, request) if variant_compare_price else '',
            'sku': variant.sku or f"{product.sku}-{variant.value[:3]}",
            'stock': variant.stock_quantity,
            'price_adjustment': float(variant.price_adjustment),
            'price_adjustment_display': format_currency(variant.price_adjustment, request),
            'image': variant.image.url if variant.image else None,
            'images': variant_images,
            'color_code': variant.color_code or '#CCCCCC',
            'is_available': variant.is_available,
        }
    
    # ====== Related Products (APPROVED ONLY) ======
    related_products = Product.objects.filter(
        category=product.category,
        is_active=True,
        approval_status='approved'
    ).exclude(id=product.id).select_related('brand').order_by('?')[:12]
    
    top_rated = Product.objects.filter(
        category=product.category,
        is_active=True,
        rating_avg__gt=0,
        approval_status='approved'
    ).exclude(id=product.id).order_by('?')[:12]
    
    bestsellers = Product.objects.filter(
        category=product.category,
        is_active=True,
        approval_status='approved'
    ).exclude(id=product.id).order_by('?')[:12]
    
    frequently_bought_together = Product.objects.filter(
        is_active=True,
        approval_status='approved'
    ).exclude(id=product.id).order_by('?')[:12]
    
    # ====== Recently Viewed ======
    recently_viewed = []
    if request.user.is_authenticated:
        recently_viewed = RecentlyViewed.objects.filter(
            user=request.user
        ).exclude(product=product).select_related('product').order_by('-viewed_at')[:12]
    
    # ====== AI Recommendations (APPROVED ONLY) ======
    ai_recommendations = Product.objects.filter(
        is_active=True,
        approval_status='approved'
    ).exclude(id=product.id).order_by('?')[:12]
    
    # ====== Calculate Rating Percentages ======
    total_reviews = product.rating_count or 1
    five_star_count = product.reviews.filter(rating=5).count()
    four_star_count = product.reviews.filter(rating=4).count()
    three_star_count = product.reviews.filter(rating=3).count()
    
    five_star_percent = int((five_star_count / total_reviews) * 100)
    four_star_percent = int((four_star_count / total_reviews) * 100)
    three_star_percent = int((three_star_count / total_reviews) * 100)
    
    # ====== All Categories for Explore Section ======
    all_categories = Category.objects.filter(is_active=True, parent=None).order_by('name')[:12]
    
    # ====== Wishlist Status ======
    in_wishlist = False
    if request.user.is_authenticated:
        in_wishlist = Wishlist.objects.filter(
            user=request.user,
            product=product
        ).exists()
    
    context = {
        'product': product,
        'size_variants': size_variants,
        'color_variants': color_variants,
        'all_variants': all_variants,
        'variants_by_type': variants_by_type,
        'variant_options': variant_options,
        'variant_groups': variant_groups,
        'variant_data_json': json.dumps(variant_data),
        'gallery_images': gallery_images,
        'gallery_images_json': json.dumps(gallery_images),
        'selected_variant': selected_variant,
        'selected_variant_id': selected_variant.id if selected_variant else None,
        'default_variant': default_variant,
        'current_price': current_price,
        'current_compare_price': current_compare_price,
        'vendor_chat_available': user_has_paid_subscription(product.vendor),
        'accessories': accessories,
        'product_accessories': accessories,
        'videos': videos,
        'product_videos': videos,
        'related_products': related_products,
        'top_rated_similar': top_rated,
        'best_sellers': bestsellers,
        'frequently_bought_together': frequently_bought_together,
        'recently_viewed': recently_viewed,
        'ai_recommendations': ai_recommendations,
        'all_categories': all_categories,
        'in_wishlist': in_wishlist,
        'five_star_percent': five_star_percent,
        'four_star_percent': four_star_percent,
        'three_star_percent': three_star_percent,
        'user_currency': user_currency,
    }
    
    return render(request, 'products/detail.html', context)


def category_view(request, slug):
    """Display category view with all subcategories and dynamic background - APPROVED ONLY"""
    category = get_object_or_404(Category, slug=slug, is_active=True)
    
    # ====== Get All Subcategories ======
    category_ids = [category.id]
    subcategories = category.children.filter(is_active=True)
    
    # Also collect products from subcategories
    for child in subcategories:
        category_ids.append(child.id)
        for grandchild in child.children.filter(is_active=True):
            category_ids.append(grandchild.id)
    
    # ====== Only show approved products ======
    products = Product.objects.filter(
        category_id__in=category_ids,
        is_active=True,
        approval_status='approved'
    ).select_related('brand')
    
    # ====== Sorting ======
    sort_param = request.GET.get('sort', 'featured')
    sort_mapping = {
        'featured': '-is_featured',
        'newest': '-created_at',
        'bestsellers': '-sales_count',
        'price_low': 'price',
        'price_high': '-price',
        'rating': '-rating_avg',
        'name_asc': 'name',
        'name_desc': '-name',
    }
    
    sort_field = sort_mapping.get(sort_param, '-created_at')
    products = products.order_by(sort_field)
    
    # ====== Vendor Count ======
    vendors_count = products.values('vendor').distinct().count()
    
    # ====== Pagination ======
    page = request.GET.get('page', 1)
    products_page = get_paginated_items(products, page, per_page=24)
    
    # ====== Currency ======
    user_currency = get_user_currency(request)
    
    # ====== Breadcrumb for better navigation ======
    breadcrumbs = []
    current = category
    while current:
        breadcrumbs.insert(0, current)
        current = current.parent
    
    return render(request, 'products/category_landing.html', {
        'category': category,
        'subcategories': subcategories,
        'products': products_page,
        'vendors_count': vendors_count,
        'current_sort': sort_param,
        'user_currency': user_currency,
        'breadcrumbs': breadcrumbs,
    })


# ================================
# 🔥 REVIEW VIEWS
# ================================

@login_required
@require_http_methods(["POST"])
@transaction.atomic
def add_review(request, slug):
    """Add product review"""
    product = get_object_or_404(Product, slug=slug, is_active=True, approval_status='approved')
    
    # Check if user already reviewed
    if ProductReview.objects.filter(product=product, user=request.user).exists():
        messages.warning(request, 'You have already reviewed this product.')
        return redirect('products:detail', slug=product.slug)
    
    # Get form data
    rating = int(request.POST.get('rating', 3))
    title = request.POST.get('title', '').strip()
    review_text = request.POST.get('review', '').strip()
    
    # Validate
    if not title or not review_text:
        messages.error(request, 'Title and review are required.')
        return redirect('products:detail', slug=product.slug)
    
    if len(title) < 5:
        messages.error(request, 'Title must be at least 5 characters.')
        return redirect('products:detail', slug=product.slug)
    
    if len(review_text) < 20:
        messages.error(request, 'Review must be at least 20 characters.')
        return redirect('products:detail', slug=product.slug)
    
    # Create review
    ProductReview.objects.create(
        product=product,
        user=request.user,
        rating=rating,
        title=title,
        review=review_text,
        verified_purchase=False
    )
    
    # Update product rating
    avg_rating = product.reviews.aggregate(Avg('rating'))['rating__avg'] or 0
    product.rating_avg = Decimal(str(avg_rating))
    product.rating_count = product.reviews.count()
    product.save(update_fields=['rating_avg', 'rating_count'])
    
    messages.success(request, 'Review added successfully!')
    return redirect('products:detail', slug=product.slug)


# ================================
# 🔥 WISHLIST VIEWS
# ================================

@login_required
def toggle_wishlist(request, slug):
    """Toggle product in wishlist"""
    product = get_object_or_404(Product, slug=slug, is_active=True, approval_status='approved')
    
    wishlist_item = Wishlist.objects.filter(
        user=request.user,
        product=product
    )
    
    if wishlist_item.exists():
        wishlist_item.delete()
        in_wishlist = False
        message = f'{product.name} removed from wishlist'
    else:
        Wishlist.objects.create(user=request.user, product=product)
        in_wishlist = True
        message = f'{product.name} added to wishlist'
    
    messages.success(request, message)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'in_wishlist': in_wishlist, 'message': message})
    
    return redirect('products:detail', slug=product.slug)


# ================================
# 🔥 Q&A VIEWS
# ================================

@login_required
@require_http_methods(["POST"])
def ask_question(request, slug):
    """Ask product question with validation and rate limiting"""
    product = get_object_or_404(Product, slug=slug, is_active=True, approval_status='approved')
    
    question_text = request.POST.get('question', '').strip()
    
    # ====== Validate ======
    if not question_text:
        messages.error(request, 'Please enter a question.')
        return redirect('products:detail', slug=product.slug)
    
    if len(question_text) < 10:
        messages.error(request, 'Question must be at least 10 characters.')
        return redirect('products:detail', slug=product.slug)
    
    if len(question_text) > 500:
        messages.error(request, 'Question must be less than 500 characters.')
        return redirect('products:detail', slug=product.slug)
    
    # ====== Rate Limiting ======
    recent_question = ProductQuestion.objects.filter(
        user=request.user,
        created_at__gte=timezone.now() - timezone.timedelta(minutes=5)
    ).exists()
    
    if recent_question:
        messages.error(request, 'Please wait 5 minutes before asking another question.')
        return redirect('products:detail', slug=product.slug)
    
    # ====== Create Question ======
    qna = ProductQuestion.objects.create(
        product=product,
        user=request.user,
        question=question_text,
        is_public=True
    )
    
    messages.success(request, 'Your question has been submitted successfully!')
    
    # ====== AJAX Response ======
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'question_id': qna.id,
            'question': question_text,
            'user': request.user.username,
            'date': qna.created_at.strftime('%b %d, %Y'),
            'message': 'Question submitted successfully!'
        })
    
    return redirect('products:detail', slug=product.slug)


@login_required
@require_http_methods(["POST"])
def answer_question(request, qna_id):
    """Answer product question (vendor/staff only)"""
    qna = get_object_or_404(ProductQuestion, id=qna_id)
    
    # ====== Permission Check ======
    if not (request.user == qna.product.vendor.user or request.user.is_staff):
        return JsonResponse(
            {'success': False, 'error': 'You do not have permission'},
            status=403
        )
    
    answer_text = request.POST.get('answer', '').strip()
    
    # ====== Validate ======
    if not answer_text:
        messages.error(request, 'Please enter an answer.')
        return redirect('products:detail', slug=qna.product.slug)
    
    if len(answer_text) < 10:
        messages.error(request, 'Answer must be at least 10 characters.')
        return redirect('products:detail', slug=qna.product.slug)
    
    # ====== Save Answer ======
    qna.answer = answer_text
    qna.answered_by = request.user
    qna.answered_at = timezone.now()
    qna.save()
    
    messages.success(request, 'Answer posted successfully!')
    
    # ====== AJAX Response ======
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'answer': answer_text,
            'answered_by': request.user.username,
            'answered_at': qna.answered_at.strftime('%b %d, %Y at %I:%M %p'),
        })
    
    return redirect('products:detail', slug=qna.product.slug)


@login_required
@require_http_methods(["POST"])
def helpful_question(request, qna_id):
    """Mark question as helpful"""
    qna = get_object_or_404(ProductQuestion, id=qna_id)
    
    qna.helpful_count = F('helpful_count') + 1
    qna.save(update_fields=['helpful_count'])
    qna.refresh_from_db()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'helpful_count': qna.helpful_count
        })
    
    return redirect('products:detail', slug=qna.product.slug)


# ================================
# 🔥 EDIT/DELETE VIEWS
# ================================

@login_required
@require_http_methods(["POST"])
def edit_question(request, qna_id):
    """Edit user's own question"""
    qna = get_object_or_404(ProductQuestion, id=qna_id)
    
    # Check permissions - only question owner can edit
    if qna.user != request.user:
        return JsonResponse({'success': False, 'error': 'You can only edit your own questions'}, status=403)
    
    # Check if already answered (can't edit answered questions)
    if qna.answer:
        messages.error(request, 'Cannot edit questions that have already been answered.')
        return redirect('products:detail', slug=qna.product.slug)
    
    question_text = request.POST.get('question', '').strip()
    
    if not question_text or len(question_text) < 10:
        messages.error(request, 'Question must be at least 10 characters.')
        return redirect('products:detail', slug=qna.product.slug)
    
    qna.question = question_text
    qna.save(update_fields=['question'])
    
    messages.success(request, 'Question updated successfully!')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'question': question_text})
    
    return redirect('products:detail', slug=qna.product.slug)


@login_required
@require_http_methods(["POST"])
def delete_question(request, qna_id):
    """Delete user's own question"""
    qna = get_object_or_404(ProductQuestion, id=qna_id)
    
    # Check permissions
    if qna.user != request.user and not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    product_slug = qna.product.slug
    qna.delete()
    
    messages.success(request, 'Question deleted successfully!')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    
    return redirect('products:detail', slug=product_slug)


@login_required
@require_http_methods(["POST"])
def edit_answer(request, qna_id):
    """Edit answer to question (vendor/staff only)"""
    qna = get_object_or_404(ProductQuestion, id=qna_id)
    
    # Check permissions - only vendor or staff can edit answers
    if not (request.user == qna.product.vendor.user or request.user.is_staff):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    answer_text = request.POST.get('answer', '').strip()
    
    if not answer_text or len(answer_text) < 10:
        messages.error(request, 'Answer must be at least 10 characters.')
        return redirect('products:detail', slug=qna.product.slug)
    
    qna.answer = answer_text
    qna.answered_by = request.user
    qna.answered_at = timezone.now()
    qna.save(update_fields=['answer', 'answered_by', 'answered_at'])
    
    messages.success(request, 'Answer updated successfully!')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'answer': answer_text,
            'answered_by': request.user.username,
            'answered_at': qna.answered_at.strftime('%b %d, %Y at %I:%M %p')
        })
    
    return redirect('products:detail', slug=qna.product.slug)


# ================================
# 🔥 API VIEWS
# ================================

def get_variant_details(request, variant_id):
    """API: Get variant details with pricing"""
    try:
        variant = ProductVariant.objects.select_related('product').get(
            id=variant_id,
            is_active=True
        )
        product = variant.product
        
        # ====== Currency Conversion ======
        user_currency = get_user_currency(request)
        base_currency = Currency.objects.filter(is_base=True).first() if Currency else None
        
        final_price = product.price + variant.price_adjustment
        final_price = convert_price(final_price, base_currency, user_currency)
        
        return JsonResponse({
            'success': True,
            'variant': {
                'id': variant.id,
                'name': variant.name,
                'value': variant.value,
                'variant_type': variant.variant_type,
                'price_adjustment': float(variant.price_adjustment),
                'stock_quantity': variant.stock_quantity,
                'image': variant.image.url if variant.image else None,
            },
            'product': {
                'id': product.id,
                'name': product.name,
                'base_price': float(product.price),
                'final_price': float(final_price),
                'main_image': product.main_image.url if product.main_image else None,
                'sku': variant.sku or product.sku,
            }
        })
    except ProductVariant.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Variant not found'},
            status=404
        )


def get_question_api(request, product_id):
    """API: Get product questions with pagination"""
    product = get_object_or_404(Product, id=product_id, is_active=True, approval_status='approved')
    
    page = int(request.GET.get('page', 1))
    questions = product.questions.filter(
        is_public=True
    ).select_related('user', 'answered_by').order_by('-created_at')
    
    paginator = Paginator(questions, 10)
    try:
        questions_page = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        questions_page = paginator.page(1)
    
    return JsonResponse({
        'questions': [
            {
                'id': q.id,
                'question': q.question,
                'user': q.user.username,
                'created_at': q.created_at.strftime('%b %d, %Y'),
                'answer': q.answer,
                'answered_by': q.answered_by.username if q.answered_by else None,
                'answered_at': q.answered_at.strftime('%b %d, %Y') if q.answered_at else None,
                'helpful_count': q.helpful_count,
            }
            for q in questions_page
        ],
        'has_next': questions_page.has_next(),
        'has_previous': questions_page.has_previous(),
        'current_page': page,
        'total_pages': paginator.num_pages,
        'total_questions': paginator.count,
    })


def quick_view(request, slug):
    """AJAX quick view endpoint"""
    product = get_object_or_404(Product, slug=slug, is_active=True, approval_status='approved')
    html = render_to_string('products/quick_view.html', {'product': product, 'request': request})
    return HttpResponse(html)


def quick_view_api(request, product_id):
    """API: Quick product view modal data"""
    product = get_object_or_404(
        Product.objects.select_related('category', 'brand'),
        id=product_id,
        is_active=True,
        approval_status='approved'
    )
    
    # ====== Currency ======
    user_currency = get_user_currency(request)
    base_currency = Currency.objects.filter(is_base=True).first() if Currency else None
    
    converted_price = convert_price(
        product.price,
        base_currency,
        user_currency
    )
    
    # ====== Get Related Data ======
    accessories = AccessoryProduct.objects.filter(
        product=product,
        accessory__is_active=True
    ).select_related('accessory')[:5]
    
    variants = product.variants.filter(is_active=True)[:10]
    
    return JsonResponse({
        'id': product.id,
        'name': product.name,
        'slug': product.slug,
        'category': product.category.name,
        'brand': product.brand.name if product.brand else None,
        'description': (product.description[:300] + '...') if len(product.description) > 300 else product.description,
        'price': str(converted_price),
        'compare_price': str(convert_price(product.compare_price, base_currency, user_currency)) if product.compare_price else None,
        'discount_percent': product.discount_percent,
        'image': product.main_image.url if product.main_image else None,
        'rating_avg': float(product.rating_avg),
        'rating_count': product.rating_count,
        'in_stock': product.is_in_stock,
        'stock_quantity': product.stock_quantity,
        'add_to_cart_url': reverse('products:add_to_cart', args=[product.slug]),
        'variants': [
            {
                'id': v.id,
                'name': v.name,
                'value': v.value,
                'variant_type': v.variant_type,
                'price_adjustment': float(v.price_adjustment),
            }
            for v in variants
        ],
        'accessories': [
            {
                'id': a.accessory.id,
                'name': a.accessory.name,
                'price': str(a.accessory.price),
                'image': a.accessory.image.url if a.accessory.image else None,
            }
            for a in accessories
        ],
    })


def cart_count(request):
    """API: Get current cart count"""
    if not request.user.is_authenticated or not Cart:
        return JsonResponse({'count': 0})
    
    cart = Cart.objects.filter(user=request.user, is_active=True).first()
    count = getattr(cart, 'total_items', 0) if cart else 0
    
    return JsonResponse({'count': count})


def checkout(request):
    """Checkout page"""
    if not request.user.is_authenticated:
        return redirect('account_login')
    
    if not Cart or not CartItem:
        messages.error(request, 'Checkout feature not available')
        return redirect('products:list')
    
    cart = Cart.objects.filter(user=request.user, is_active=True).first()
    
    if not cart or cart.items.count() == 0:
        messages.info(request, 'Your cart is empty.')
        return redirect('products:list')
    
    return render(request, 'products/checkout.html', {'cart': cart})


@login_required
def add_accessory_to_cart(request, accessory_id):
    """Add accessory directly to cart"""
    if not Cart or not CartItem:
        return redirect('products:list')
    
    accessory = get_object_or_404(Accessory, id=accessory_id, is_active=True)
    quantity = int(request.POST.get('quantity', 1))
    
    if quantity < 1:
        quantity = 1
    elif quantity > 999:
        quantity = 999
    
    cart, created = Cart.objects.get_or_create(user=request.user, is_active=True)
    
    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=None,
        accessory=accessory,
        defaults={'quantity': quantity, 'price_at_add': accessory.price}
    )
    
    if not created:
        cart_item.quantity += quantity
        cart_item.save(update_fields=['quantity'])
    
    messages.success(request, f'{accessory.name} added to cart!')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'cart_count': getattr(cart, 'total_items', 0),
            'message': f'{accessory.name} added to cart'
        })
    
    return redirect('products:cart')


def debug_colors(request, product_id):
    """Debug view for product colors/variants"""
    product = get_object_or_404(Product, id=product_id)
    
    html = f"""
    <html>
    <head><title>Debug Colors - {product.name}</title></head>
    <body>
        <h1>Debug Colors for {product.name}</h1>
        <h2>Variants:</h2>
        <ul>
    """
    for variant in product.variants.filter(is_active=True):
        html += f"<li>{variant.variant_type}: {variant.name} = {variant.value}</li>"
    
    html += """
        </ul>
    </body>
    </html>
    """
    return HttpResponse(html)
