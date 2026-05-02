from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Avg, Count, Sum
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
import json

from .models import Product, Category, ProductReview, Wishlist, RecentlyViewed, ProductVariant, ProductQnA
from orders.models import Cart, CartItem
from currency.models import Currency
from currency.utils.exchange_rates import CurrencyConverter

def product_list(request):
    products = Product.objects.filter(is_active=True)
    
    category = request.GET.get('category')
    if category:
        products = products.filter(category__slug=category)
    
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    if min_price:
        products = products.filter(price__gte=min_price)
    if max_price:
        products = products.filter(price__lte=max_price)
    
    sort_param = request.GET.get('sort', '-created_at')
    sort_mapping = {
        'featured': '-is_featured',
        'new': '-created_at',
        'bestsellers': '-sales_count',
        'trending': '-views_count',
        'price_low': 'price',
        'price_high': '-price',
        'rating': '-rating_avg',
        'name_asc': 'name',
        'name_desc': '-name',
    }
    
    sort_field = sort_mapping.get(sort_param, sort_param)
    products = products.order_by(sort_field)
    
    paginator = Paginator(products, 24)
    page = request.GET.get('page', 1)
    products_page = paginator.get_page(page)
    
    user_currency = getattr(request, 'user_currency', None)
    if not user_currency:
        user_currency = Currency.objects.filter(is_base=True).first()
    
    return render(request, 'products/list.html', {
        'products': products_page,
        'categories': Category.objects.filter(is_active=True, parent=None),
        'current_sort': sort_param,
        'user_currency': user_currency,
    })

def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    
    product.views_count += 1
    product.save()
    
    if request.user.is_authenticated:
        RecentlyViewed.objects.get_or_create(user=request.user, product=product)
    
    size_variants = product.variants.filter(variant_type='size', is_active=True).order_by('value')
    color_variants = product.variants.filter(variant_type='color', is_active=True).order_by('value')
    
    user_currency = getattr(request, 'user_currency', None)
    if not user_currency:
        user_currency = Currency.objects.filter(is_base=True).first()
    
    base_currency = Currency.objects.filter(is_base=True).first()
    converted_price = product.price
    converted_compare_price = product.compare_price
    
    if user_currency and base_currency and user_currency.code != base_currency.code:
        converted_price = CurrencyConverter.convert(product.price, base_currency, user_currency)
        if product.compare_price:
            converted_compare_price = CurrencyConverter.convert(product.compare_price, base_currency, user_currency)
    
    variant_data = {}
    for variant in product.variants.filter(is_active=True):
        converted_variant_price = product.price + variant.price_adjustment
        if user_currency and base_currency and user_currency.code != base_currency.code:
            converted_variant_price = CurrencyConverter.convert(converted_variant_price, base_currency, user_currency)
        
        variant_data[variant.id] = {
            'id': variant.id,
            'name': variant.name,
            'value': variant.value,
            'variant_type': variant.variant_type,
            'price': float(converted_variant_price),
            'sku': variant.sku or f"{product.sku}-{variant.value[:3]}",
            'stock': variant.stock_quantity,
            'price_adjustment': float(variant.price_adjustment),
        }
    
    related_products = Product.objects.filter(category=product.category, is_active=True).exclude(id=product.id)[:8]
    top_rated_similar = Product.objects.filter(category=product.category, is_active=True, rating_avg__gt=0).exclude(id=product.id).order_by('-rating_avg', '-sales_count')[:8]
    best_sellers = Product.objects.filter(category=product.category, is_active=True).exclude(id=product.id).order_by('-sales_count')[:8]
    
    recently_viewed = []
    if request.user.is_authenticated:
        recently_viewed = RecentlyViewed.objects.filter(user=request.user).exclude(product=product).select_related('product')[:6]
    
    ai_recommendations = Product.objects.filter(is_active=True).exclude(id=product.id).order_by('-rating_avg', '-sales_count', '-views_count')[:8]
    reviews = product.reviews.filter(is_active=True)
    
    in_wishlist = False
    if request.user.is_authenticated:
        in_wishlist = Wishlist.objects.filter(user=request.user, product=product).exists()
    
    context = {
        'product': product,
        'size_variants': size_variants,
        'color_variants': color_variants,
        'variant_data_json': json.dumps(variant_data),
        'related_products': related_products,
        'top_rated_similar': top_rated_similar,
        'best_sellers': best_sellers,
        'recently_viewed': recently_viewed,
        'ai_recommendations': ai_recommendations,
        'reviews': reviews,
        'in_wishlist': in_wishlist,
        'converted_price': converted_price,
        'converted_compare_price': converted_compare_price,
        'user_currency': user_currency,
        'base_currency': base_currency,
    }
    
    return render(request, 'products/detail.html', context)

@login_required
def add_review(request, slug):
    product = get_object_or_404(Product, slug=slug)
    
    if request.method == 'POST':
        rating = int(request.POST.get('rating', 3))
        title = request.POST.get('title')
        review_text = request.POST.get('review')
        
        if ProductReview.objects.filter(product=product, user=request.user).exists():
            messages.warning(request, 'You have already reviewed this product.')
            return redirect('products:detail', slug=product.slug)
        
        ProductReview.objects.create(
            product=product,
            user=request.user,
            rating=rating,
            title=title,
            review=review_text,
            verified_purchase=False
        )
        
        avg_rating = product.reviews.aggregate(Avg('rating'))['rating__avg']
        product.rating_avg = avg_rating
        product.rating_count = product.reviews.count()
        product.save()
        
        messages.success(request, 'Review added successfully')
    
    return redirect('products:detail', slug=product.slug)

@login_required
def add_to_cart(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    quantity = int(request.POST.get('quantity', request.GET.get('quantity', 1)))
    variant_id = request.POST.get('variant_id') or request.GET.get('variant_id')
    
    if quantity < 1:
        quantity = 1
    
    cart, created = Cart.objects.get_or_create(user=request.user, is_active=True)
    
    price = product.price
    if variant_id:
        try:
            selected_variant = ProductVariant.objects.get(id=variant_id, is_active=True)
            price = selected_variant.final_price
        except ProductVariant.DoesNotExist:
            pass
    
    cart_item = CartItem.objects.filter(cart=cart, product=product).first()
    
    if cart_item:
        cart_item.quantity += quantity
        cart_item.save()
        message = f'Updated {product.name} quantity to {cart_item.quantity}'
    else:
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=quantity,
            price_at_add=price
        )
        message = f'{product.name} added to cart (x{quantity})'
    
    messages.success(request, message)
    request.session['cart_count'] = cart.total_items
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True, 
            'cart_count': cart.total_items,
            'message': message,
            'quantity': quantity,
            'cart_total': float(cart.subtotal)
        })
    
    return redirect('products:cart')

@login_required
def cart_view(request):
    cart, created = Cart.objects.get_or_create(user=request.user, is_active=True)
    request.session['cart_count'] = cart.total_items
    
    # Get user's currency for conversion
    user_currency = getattr(request, 'user_currency', None)
    base_currency = Currency.objects.filter(is_base=True).first()
    
    # Calculate converted totals
    subtotal_converted = 0
    shipping_converted = 0
    total_converted = 0
    
    for item in cart.items.all():
        # Convert individual item price
        converted_price = item.price_at_add
        if user_currency and base_currency and user_currency.code != base_currency.code:
            converted_price = CurrencyConverter.convert(item.price_at_add, base_currency, user_currency)
        
        # Calculate converted subtotal for this item
        item_converted_subtotal = converted_price * item.quantity
        subtotal_converted += item_converted_subtotal
        
        # Add converted values to item for template
        item.converted_price = converted_price
        item.converted_subtotal = item_converted_subtotal
    
    # Calculate total (subtotal + shipping)
    total_converted = subtotal_converted + shipping_converted
    
    return render(request, 'products/cart.html', {
        'cart': cart,
        'subtotal_converted': subtotal_converted,
        'total_converted': total_converted,
        'shipping_converted': shipping_converted,
        'user_currency': user_currency,
    })

@login_required
def update_cart(request):
    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        quantity = int(request.POST.get('quantity', 1))
        
        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        
        if quantity <= 0:
            cart_item.delete()
        else:
            cart_item.quantity = quantity
            cart_item.save()
        
        return JsonResponse({'success': True})

@login_required
def remove_from_cart(request, item_id):
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    cart = cart_item.cart
    cart_item.delete()
    request.session['cart_count'] = cart.total_items
    messages.success(request, 'Item removed from cart')
    return redirect('products:cart')

@login_required
def toggle_wishlist(request, slug):
    product = get_object_or_404(Product, slug=slug)
    wishlist_item = Wishlist.objects.filter(user=request.user, product=product)
    
    if wishlist_item.exists():
        wishlist_item.delete()
        in_wishlist = False
    else:
        Wishlist.objects.create(user=request.user, product=product)
        in_wishlist = True
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'in_wishlist': in_wishlist})
    
    return redirect('products:detail', slug=product.slug)

def checkout(request):
    cart = Cart.objects.filter(user=request.user, is_active=True).first()
    if not cart or cart.items.count() == 0:
        return redirect('products:cart')
    
    return render(request, 'products/checkout.html', {'cart': cart})

def category_view(request, slug):
    category = get_object_or_404(Category, slug=slug, is_active=True)
    
    category_ids = [category.id]
    for child in category.children.filter(is_active=True):
        category_ids.append(child.id)
        for grandchild in child.children.filter(is_active=True):
            category_ids.append(grandchild.id)
    
    products = Product.objects.filter(category_id__in=category_ids, is_active=True)
    
    paginator = Paginator(products, 24)
    page = request.GET.get('page', 1)
    products_page = paginator.get_page(page)
    
    user_currency = getattr(request, 'user_currency', None)
    
    return render(request, 'products/category.html', {
        'category': category,
        'products': products_page,
        'user_currency': user_currency,
    })

def get_variant_details(request, variant_id):
    try:
        variant = ProductVariant.objects.get(id=variant_id, is_active=True)
        product = variant.product
        
        user_currency = getattr(request, 'user_currency', None)
        base_currency = Currency.objects.filter(is_base=True).first()
        
        final_price = product.price + variant.price_adjustment
        if user_currency and base_currency and user_currency.code != base_currency.code:
            final_price = CurrencyConverter.convert(final_price, base_currency, user_currency)
        
        data = {
            'success': True,
            'variant': {
                'id': variant.id,
                'name': variant.name,
                'value': variant.value,
                'variant_type': variant.variant_type,
                'price_adjustment': float(variant.price_adjustment),
                'stock_quantity': variant.stock_quantity,
            },
            'product': {
                'id': product.id,
                'name': product.name,
                'base_price': float(product.price),
                'final_price': float(final_price),
                'main_image': product.main_image.url if product.main_image else None,
                'sku': variant.sku or product.sku,
            }
        }
        return JsonResponse(data)
    except ProductVariant.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Variant not found'})

def debug_colors(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    color_variants = product.variants.filter(variant_type='color', is_active=True)
    size_variants = product.variants.filter(variant_type='size', is_active=True)
    
    return render(request, 'products/color_debug.html', {
        'product': product,
        'color_variants': color_variants,
        'size_variants': size_variants,
    })

@login_required
def cart_count(request):
    cart = Cart.objects.filter(user=request.user, is_active=True).first()
    count = cart.total_items if cart else 0
    return JsonResponse({'count': count})

@login_required
def ask_question(request, slug):
    """Ask a question about a product"""
    product = get_object_or_404(Product, slug=slug, is_active=True)
    
    if request.method == 'POST':
        question_text = request.POST.get('question', '').strip()
        
        if question_text:
            ProductQnA.objects.create(
                product=product,
                user=request.user,
                question=question_text
            )
            messages.success(request, 'Your question has been submitted. We will answer it soon!')
        else:
            messages.error(request, 'Please enter a question.')
    
    return redirect('products:detail', slug=product.slug)

@login_required
def answer_question(request, qna_id):
    """Answer a question (for vendors/admins)"""
    qna = get_object_or_404(ProductQnA, id=qna_id)
    
    # Check if user is vendor of this product or admin
    if request.user == qna.product.vendor or request.user.is_staff:
        if request.method == 'POST':
            answer_text = request.POST.get('answer', '').strip()
            if answer_text:
                qna.answer = answer_text
                qna.answered_by = request.user
                qna.answered_at = timezone.now()
                qna.save()
                messages.success(request, 'Answer posted successfully!')
            else:
                messages.error(request, 'Please enter an answer.')
    
    return redirect('products:detail', slug=qna.product.slug)

def quick_view_api(request, product_id):
    """API endpoint for quick product view"""
    product = get_object_or_404(Product, id=product_id, is_active=True)
    
    data = {
        'id': product.id,
        'name': product.name,
        'category': product.category.name,
        'description': product.description[:200] + '...' if len(product.description) > 200 else product.description,
        'price': str(product.price),
        'image': product.main_image.url if product.main_image else '',
        'add_to_cart_url': reverse('products:add_to_cart', args=[product.slug]),
    }
    return JsonResponse(data)