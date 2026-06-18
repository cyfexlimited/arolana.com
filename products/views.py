from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Avg, Count, Sum, Prefetch, F
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from django.views.decorators.http import require_http_methods, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
import json
import re
from django.http import HttpResponse
from decimal import Decimal, InvalidOperation
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from core.local_cache import local_get_or_set
from core.models import HomePageAppearance
from core.media_optimization import get_optimized_image_url
from .models import (
    Product, Category, ProductReview, Wishlist, RecentlyViewed, 
    ProductVariant, ProductQuestion, Accessory, AccessoryProduct,
    ProductImage, ProductVideo, ProductVariantImage, Brand, ProductListingBanner,
    ProductArticleLink, ProductWholesaleTier, ProductDetailSection,
    ProductDetailFieldConfig, ProductVariantTypeConfig
)
from accounts.models import User
from currency.templatetags.currency_filters import currency as format_currency
from arolana_payments.services import get_gateway_options
from products.ranking import order_storefront_products

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

try:
    from homepage.models import HomepageBanner, HomepageCategory, HomepageVendorSection, HomepageVideoSection
except ImportError:
    HomepageBanner = None
    HomepageCategory = None
    HomepageVendorSection = None
    HomepageVideoSection = None

try:
    from hero_banners.models import HeroBanner
except ImportError:
    HeroBanner = None

try:
    from ads.models import Advertisement, AdBanner, AdCreative, AdPlacement
except ImportError:
    Advertisement = None
    AdBanner = None
    AdCreative = None
    AdPlacement = None

try:
    from mobile_customers.views import _auth_mobile_customer_from_request_data
except ImportError:
    _auth_mobile_customer_from_request_data = None

try:
    from vendors.models import VendorProfile, VendorFollow, VendorRFQ
except ImportError:
    VendorProfile = None
    VendorFollow = None
    VendorRFQ = None

try:
    from notifications.models import Notification
except ImportError:
    Notification = None


# ================================
# 🔥 HELPER FUNCTIONS
# ================================

def get_user_currency(request):
    """Get user's active currency with fallback to base currency"""
    if not Currency:
        return None
    
    user_currency = getattr(request, 'user_currency', None)
    
    if user_currency and isinstance(user_currency, str):
        currency_code = user_currency.upper()
        user_currency = local_get_or_set(
            f"currency:active:{currency_code}",
            lambda: Currency.objects.filter(
                code=currency_code,
                is_active=True,
            ).first(),
            300,
        )
    
    if not user_currency:
        user_currency = get_base_currency()
    
    return user_currency


def get_base_currency():
    """Get the catalog currency prices are stored in."""
    if not Currency:
        return None

    base_code = (
        getattr(settings, 'AROLANA_BASE_CURRENCY', None)
        or getattr(settings, 'AROLANA_DEFAULT_CURRENCY', None)
        or getattr(settings, 'CURRENCY_DEFAULT', None)
        or 'NGN'
    )
    return local_get_or_set(
        f"currency:base:{base_code.upper()}",
        lambda: (
            Currency.objects.filter(code=base_code.upper(), is_active=True).first()
            or Currency.objects.filter(is_base=True, is_active=True).first()
            or Currency.objects.filter(code='NGN', is_active=True).first()
            or Currency.objects.filter(code='USD', is_active=True).first()
        ),
        300,
    )


def convert_price(price, from_currency, to_currency):
    """Convert price between currencies safely"""
    try:
        price_decimal = Decimal(str(price or '0'))
    except (InvalidOperation, TypeError, ValueError):
        price_decimal = Decimal('0')

    if not from_currency or not to_currency or not CurrencyConverter:
        return price_decimal
    
    if from_currency.code == to_currency.code:
        return price_decimal
    
    try:
        return Decimal(str(CurrencyConverter.convert(price_decimal, from_currency, to_currency)))
    except Exception:
        return price_decimal


def get_paginated_items(queryset, page_num, per_page=24):
    """Get paginated items with error handling"""
    paginator = Paginator(queryset, per_page)
    try:
        return paginator.page(page_num)
    except (PageNotAnInteger, EmptyPage):
        return paginator.page(1)


PRODUCT_SEARCH_STOP_WORDS = {
    "do", "you", "u", "have", "has", "please", "pls", "can", "i", "get",
    "buy", "want", "need", "looking", "for", "show", "me", "find", "search",
    "available", "stock", "in", "the", "a", "an", "on", "arolana", "any", "is",
    "there", "with", "under", "below", "above", "best", "good", "cheap",
    "affordable", "price", "prices", "sell", "selling",
}

PRODUCT_SEARCH_ALIASES = {
    "google": ("google", "pixel"),
    "pixel": ("pixel", "google"),
    "phone": ("phone", "phones", "smartphone", "mobile"),
    "phones": ("phone", "phones", "smartphone", "mobile"),
    "tv": ("tv", "television"),
    "television": ("tv", "television"),
    "earbud": ("earbud", "earbuds", "earphone", "headphone"),
    "earbuds": ("earbud", "earbuds", "earphone", "headphone"),
}

PRODUCT_SEARCH_BRANDS = {
    "acer", "apple", "asus", "google", "hp", "huawei", "infinix", "itel",
    "lenovo", "lg", "nokia", "oneplus", "oppo", "pixel", "samsung", "sony",
    "tecno", "vivo", "xiaomi",
}


def _product_search_terms(query):
    text = re.sub(r"[^a-zA-Z0-9\s-]", " ", str(query or "").lower())
    terms = [
        term.strip()
        for term in text.split()
        if len(term.strip()) > 1 and term.strip() not in PRODUCT_SEARCH_STOP_WORDS
    ]
    cleaned = []
    for term in terms:
        singular = term[:-1] if term.endswith("s") and len(term) > 3 else term
        for item in (singular, term):
            if item and item not in cleaned:
                cleaned.append(item)
    return cleaned[:8]


def _product_term_q(term):
    values = PRODUCT_SEARCH_ALIASES.get(term, (term,))
    term_q = Q()
    for value in values:
        term_q |= (
            Q(name__icontains=value)
            | Q(description__icontains=value)
            | Q(sku__icontains=value)
            | Q(manufacturer_sku__icontains=value)
            | Q(country_of_origin__icontains=value)
            | Q(category__name__icontains=value)
            | Q(brand__name__icontains=value)
            | Q(vendor__vendor_profile__store_name__icontains=value)
            | Q(vendor__vendor_profile__company_name__icontains=value)
            | Q(vendor__vendor_profile__vendor_type__icontains=value)
        )
    return term_q


def _product_search_q(query, strict=True):
    text = str(query or "").strip()
    terms = _product_search_terms(text)
    exact_q = Q()
    if text:
        exact_q = _product_term_q(text.lower())
    if not terms:
        return exact_q
    if not strict:
        loose_q = exact_q
        for term in terms:
            loose_q |= _product_term_q(term)
        return loose_q
    strict_q = Q()
    for term in terms:
        strict_q &= _product_term_q(term)
    return strict_q


def apply_product_search(queryset, query):
    query = str(query or "").strip()
    if not query:
        return queryset
    strict_queryset = queryset.filter(_product_search_q(query, strict=True)).distinct()
    if strict_queryset.exists():
        return strict_queryset
    if PRODUCT_SEARCH_BRANDS.intersection(_product_search_terms(query)):
        return queryset.none()
    return queryset.filter(_product_search_q(query, strict=False)).distinct()


def apply_filters(queryset, request):
    """Apply all filters to queryset"""
    collection = request.GET.get('collection', '').strip().lower()
    if collection == 'featured':
        queryset = queryset.filter(is_featured=True)
    elif collection == 'new':
        queryset = queryset.filter(is_new=True)
    elif collection == 'bestsellers':
        queryset = queryset.filter(is_bestseller=True)
    elif collection == 'trending':
        queryset = queryset.filter(Q(views_count__gt=0) | Q(sales_count__gt=0))

    query = request.GET.get('q', '').strip()
    if query:
        queryset = apply_product_search(queryset, query)
    
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
    user_currency = get_user_currency(request)
    base_currency = get_base_currency()

    def price_in_catalog_currency(value):
        return convert_price(Decimal(value), user_currency, base_currency)
    
    if min_price:
        try:
            queryset = queryset.filter(price__gte=price_in_catalog_currency(min_price))
        except (InvalidOperation, ValueError, TypeError):
            pass
    
    if max_price:
        try:
            queryset = queryset.filter(price__lte=price_in_catalog_currency(max_price))
        except (InvalidOperation, ValueError, TypeError):
            pass
    
    # ====== Brand Filter ======
    brands = request.GET.getlist('brands')
    if brands:
        brand_slugs = []
        for b in brands:
            brand_slugs.extend([s.strip() for s in b.split(',') if s.strip()])
        if brand_slugs:
            queryset = queryset.filter(brand__slug__in=brand_slugs)

    # ====== Product Condition Filter ======
    conditions = request.GET.getlist('conditions')
    if not conditions and request.GET.get('condition'):
        conditions = [request.GET.get('condition')]
    condition_values = []
    valid_conditions = {value for value, _label in Product.PRODUCT_CONDITION_CHOICES}
    for condition in conditions:
        condition_values.extend([
            value.strip()
            for value in str(condition).split(',')
            if value.strip() in valid_conditions
        ])
    if condition_values:
        queryset = queryset.filter(condition__in=condition_values)
    
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

GUEST_CART_SESSION_KEY = 'guest_cart'
GUEST_WISHLIST_SESSION_KEY = 'guest_wishlist'


class GuestCartItems:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items

    def exists(self):
        return bool(self._items)

    def count(self):
        return len(self._items)


class GuestCartItem:
    def __init__(self, item_id, product=None, variant=None, accessory=None, quantity=1, price_at_add=Decimal('0.00')):
        self.id = item_id
        self.product = product
        self.variant = variant
        self.accessory = accessory
        self.quantity = quantity
        self.price_at_add = price_at_add

    @property
    def subtotal(self):
        return self.price_at_add * self.quantity

    @property
    def item_name(self):
        if self.product:
            return self.product.name
        if self.variant:
            return f"{self.variant.product.name} - {self.variant.value}"
        if self.accessory:
            return self.accessory.name
        return "Item"


class GuestCart:
    def __init__(self, items):
        self.items = GuestCartItems(items)

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def subtotal(self):
        return sum((item.subtotal for item in self.items.all()), Decimal('0.00'))

    @property
    def total(self):
        return self.subtotal


def _safe_quantity(value, default=1):
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        quantity = default

    if quantity < 1:
        return 1
    if quantity > 999:
        return 999
    return quantity


def _guest_cart_data(request):
    data = request.session.get(GUEST_CART_SESSION_KEY)
    return data if isinstance(data, dict) else {}


def _guest_cart_count(cart_data):
    count = 0
    for line in cart_data.values():
        try:
            count += int(line.get('quantity') or 0)
        except (TypeError, ValueError):
            continue
    return count


def _save_guest_cart(request, cart_data):
    cleaned = {}
    for key, value in cart_data.items():
        try:
            quantity = int(value.get('quantity') or 0)
        except (TypeError, ValueError):
            continue
        if quantity > 0:
            cleaned[key] = {**value, 'quantity': min(quantity, 999)}
    request.session[GUEST_CART_SESSION_KEY] = cleaned
    request.session['cart_count'] = _guest_cart_count(cleaned)
    request.session.modified = True
    return cleaned


def _guest_cart_key(product=None, variant=None, accessory=None):
    if accessory:
        return f"accessory:{accessory.id}"
    variant_id = variant.id if variant else ''
    return f"product:{product.id}:variant:{variant_id}"


def _build_guest_cart(request):
    cart_data = _guest_cart_data(request)
    if not cart_data:
        request.session['cart_count'] = 0
        return GuestCart([])

    product_ids = set()
    variant_ids = set()
    accessory_ids = set()

    for line in cart_data.values():
        if line.get('accessory_id'):
            accessory_ids.add(line.get('accessory_id'))
        elif line.get('product_id'):
            product_ids.add(line.get('product_id'))
            if line.get('variant_id'):
                variant_ids.add(line.get('variant_id'))

    products = {
        str(product.id): product
        for product in Product.objects.filter(id__in=product_ids, is_active=True, approval_status='approved')
    }
    variants = {
        str(variant.id): variant
        for variant in ProductVariant.objects.select_related('product').filter(
            id__in=variant_ids,
            is_active=True,
            product__is_active=True,
            product__approval_status='approved',
        )
    }
    accessories = {
        str(accessory.id): accessory
        for accessory in Accessory.objects.filter(id__in=accessory_ids, is_active=True)
    }

    items = []
    valid_cart_data = {}

    for key, line in cart_data.items():
        quantity = _safe_quantity(line.get('quantity'), default=1)
        try:
            price = Decimal(str(line.get('price_at_add') or '0'))
        except (InvalidOperation, TypeError, ValueError):
            price = Decimal('0.00')

        if line.get('accessory_id'):
            accessory = accessories.get(str(line.get('accessory_id')))
            if not accessory:
                continue
            if not price:
                price = accessory.price
            items.append(GuestCartItem(key, accessory=accessory, quantity=quantity, price_at_add=price))
            valid_cart_data[key] = {**line, 'quantity': quantity, 'price_at_add': str(price)}
            continue

        product = products.get(str(line.get('product_id')))
        variant = variants.get(str(line.get('variant_id'))) if line.get('variant_id') else None
        if not product:
            continue
        if line.get('variant_id') and not variant:
            continue
        if not price:
            price = variant.final_price if variant else product.price

        items.append(GuestCartItem(key, product=product, variant=variant, quantity=quantity, price_at_add=price))
        valid_cart_data[key] = {**line, 'quantity': quantity, 'price_at_add': str(price)}

    if valid_cart_data != cart_data:
        _save_guest_cart(request, valid_cart_data)
    else:
        request.session['cart_count'] = _guest_cart_count(valid_cart_data)

    return GuestCart(items)


def _merge_guest_cart_into_user_cart(request):
    if not request.user.is_authenticated or not Cart or not CartItem:
        return None

    guest_cart = _build_guest_cart(request)
    cart, _ = Cart.objects.get_or_create(user=request.user, is_active=True)

    for item in guest_cart.items.all():
        if item.accessory:
            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product=None,
                accessory=item.accessory,
                defaults={'quantity': item.quantity, 'price_at_add': item.price_at_add}
            )
            if not created:
                cart_item.quantity = min(cart_item.quantity + item.quantity, 999)
                cart_item.save(update_fields=['quantity'])
            continue

        stock = item.variant.stock_quantity if item.variant else item.product.get_available_stock()
        quantity = min(item.quantity, max(stock, 0))
        if quantity <= 0:
            continue

        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            product=item.product,
            variant=item.variant,
            defaults={'quantity': quantity, 'price_at_add': item.price_at_add}
        )
        if not created:
            cart_item.quantity = min(cart_item.quantity + quantity, stock, 999)
            cart_item.save(update_fields=['quantity'])

    if guest_cart.items.exists():
        _save_guest_cart(request, {})
        request.session['cart_count'] = getattr(cart, 'total_items', 0)

    return cart


@transaction.atomic
def add_to_cart(request, slug):
    """Add product to cart with variant and accessory support"""
    if not Cart or not CartItem:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': 'Cart feature is not available.'}, status=400)
        return redirect('products:detail', slug=slug)
    
    product = get_object_or_404(Product, slug=slug, is_active=True, approval_status='approved')
    
    # Get parameters
    quantity = _safe_quantity(request.POST.get('quantity', request.GET.get('quantity', 1)))
    variant_id = request.POST.get('variant_id') or request.GET.get('variant_id')
    accessory_ids = request.POST.getlist('accessories') or request.GET.getlist('accessories')
    
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
                message = f"Only {variant.stock_quantity} {variant.value} available!"
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': message}, status=400)
                messages.error(request, message)
                return redirect('products:detail', slug=product.slug)
        except ProductVariant.DoesNotExist:
            message = 'Selected variant not found.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': message}, status=400)
            messages.error(request, message)
            return redirect('products:detail', slug=product.slug)
    else:
        # Check product stock
        available = product.get_available_stock()
        if available < quantity:
            message = f"Only {available} items available!"
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': message}, status=400)
            messages.error(request, message)
            return redirect('products:detail', slug=product.slug)

    if request.user.is_authenticated:
        cart, created = Cart.objects.get_or_create(user=request.user, is_active=True)

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
                message = f"Cannot add more than {stock} items!"
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': message}, status=400)
                messages.error(request, message)
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

        cart_count = getattr(cart, 'total_items', 0)
    else:
        cart_data = _guest_cart_data(request)
        key = _guest_cart_key(product=product, variant=variant)
        current_quantity = int(cart_data.get(key, {}).get('quantity') or 0)
        stock = variant.stock_quantity if variant else product.get_available_stock()

        if current_quantity + quantity > stock:
            message = f"Cannot add more than {stock} items!"
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': message}, status=400)
            messages.error(request, message)
            return redirect('products:detail', slug=product.slug)

        cart_data[key] = {
            'product_id': product.id,
            'variant_id': variant.id if variant else '',
            'quantity': current_quantity + quantity,
            'price_at_add': str(price),
        }
        message = f'Added {product.name} to cart!'

        accessories = Accessory.objects.filter(id__in=accessory_ids, is_active=True) if accessory_ids else []
        for accessory in accessories:
            acc_key = _guest_cart_key(accessory=accessory)
            acc_quantity = int(cart_data.get(acc_key, {}).get('quantity') or 0)
            cart_data[acc_key] = {
                'accessory_id': accessory.id,
                'quantity': min(acc_quantity + 1, 999),
                'price_at_add': str(accessory.price),
            }

        cart_data = _save_guest_cart(request, cart_data)
        cart_count = _guest_cart_count(cart_data)

    messages.success(request, message)
    request.session['cart_count'] = cart_count
    
    # ====== AJAX Response ======
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': message,
            'cart_count': cart_count,
            'variant_selected': variant.value if variant else None
        })
    
    # ====== Redirect ======
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url:
        return redirect(next_url)
    
    return redirect('products:cart')



def _support_contact_context():
    """
    Support contact details for templates.

    Do not hardcode admin/support numbers inside templates.
    Add these values in settings.py or environment variables:
    - AROLANA_SUPPORT_PHONE
    - AROLANA_SUPPORT_WHATSAPP
    - AROLANA_SUPPORT_EMAIL
    """
    support_phone = str(getattr(settings, 'AROLANA_SUPPORT_PHONE', '') or '').strip()
    support_whatsapp = str(getattr(settings, 'AROLANA_SUPPORT_WHATSAPP', '') or support_phone).strip()
    support_email = str(getattr(settings, 'AROLANA_SUPPORT_EMAIL', '') or '').strip()

    def digits_only(value):
        return ''.join(ch for ch in str(value or '') if ch.isdigit())

    whatsapp_digits = digits_only(support_whatsapp)
    phone_digits = digits_only(support_phone)

    return {
        'support_phone_display': support_phone,
        'support_phone_tel': f'+{phone_digits}' if phone_digits else '',
        'support_whatsapp_url': f'https://wa.me/{whatsapp_digits}' if whatsapp_digits else '',
        'support_email': support_email,
    }

def cart_view(request):
    """Display shopping cart with currency conversion"""
    if not Cart or not CartItem:
        return render(request, 'products/cart.html', {
            'cart': None,
            'error': 'Cart feature not available',
            **_support_contact_context(),
        })

    if request.user.is_authenticated:
        cart = _merge_guest_cart_into_user_cart(request) or Cart.objects.get_or_create(
            user=request.user,
            is_active=True
        )[0]
    else:
        cart = _build_guest_cart(request)

    request.session['cart_count'] = getattr(cart, 'total_items', 0)
    
    # Get currencies
    user_currency = get_user_currency(request)
    base_currency = get_base_currency()
    
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
        **_support_contact_context(),
    })


@require_http_methods(["POST"])
def update_cart(request):
    """Update cart item quantity"""
    if request.user.is_authenticated and not CartItem:
        return JsonResponse({'success': False, 'error': 'Cart feature not available'}, status=400)
    
    try:
        item_id = request.POST.get('item_id')
        quantity = int(request.POST.get('quantity', 1))

        if quantity < 0:
            quantity = 0
        elif quantity > 999:
            quantity = 999

        if not request.user.is_authenticated:
            cart_data = _guest_cart_data(request)
            if item_id not in cart_data:
                return JsonResponse({'success': False, 'error': 'Cart item not found'}, status=404)

            if quantity <= 0:
                cart_data.pop(item_id, None)
                _save_guest_cart(request, cart_data)
                return JsonResponse({'success': True, 'deleted': True, 'cart_count': _guest_cart_count(cart_data)})

            cart_data[item_id]['quantity'] = quantity
            cart_data = _save_guest_cart(request, cart_data)
            return JsonResponse({'success': True, 'cart_count': _guest_cart_count(cart_data)})

        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        
        if quantity <= 0:
            cart_item.delete()
            return JsonResponse({'success': True, 'deleted': True})
        
        cart_item.quantity = quantity
        cart_item.save(update_fields=['quantity'])
        
        return JsonResponse({'success': True})
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid quantity'}, status=400)


def remove_from_cart(request, item_id):
    """Remove item from cart"""
    if request.user.is_authenticated and not CartItem:
        return redirect('products:cart')

    if request.user.is_authenticated:
        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        cart = cart_item.cart
        cart_item.delete()
        cart_count = getattr(cart, 'total_items', 0)
    else:
        cart_data = _guest_cart_data(request)
        cart_data.pop(str(item_id), None)
        cart_data = _save_guest_cart(request, cart_data)
        cart_count = _guest_cart_count(cart_data)

    request.session['cart_count'] = cart_count
    messages.success(request, 'Item removed from cart')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'cart_count': cart_count
        })
    
    return redirect('products:cart')


def secure_payments(request):
    """Customer-facing secure payments information page."""
    return render(request, 'products/secure_payments.html', {
        'meta_title': 'Secure Payments | Arolana',
        'meta_description': (
            'Learn how Arolana helps protect customers with secure checkout, '
            'trusted payment processing, order tracking, and safer marketplace transactions.'
        ),
    })

def product_list(request):
    """Display paginated product list with filtering and sorting - APPROVED ONLY"""

    # ====== Admin-editable product listing banner ======
    # This must be loaded BEFORE render so templates/products/list.html can use {{ shop_banner }}.
    shop_banner = ProductListingBanner.objects.filter(
        placement="products_list",
        is_active=True,
    ).order_by("display_order", "-created_at").first()

    products = Product.objects.filter(
        is_active=True,
        approval_status="approved",
    ).select_related(
        "category",
        "brand",
        "vendor",
        "vendor__vendor_profile",
    )

    # ====== Apply Filters ======
    products = apply_filters(products, request)

    # ====== Sorting ======
    collection = request.GET.get("collection", "").strip().lower()
    collection_details = {
        "featured": {
            "title": "Featured Products",
            "description": "Handpicked products selected by the Arolana team.",
            "sort": "featured",
            "icon": "star",
        },
        "new": {
            "title": "New Arrivals",
            "description": "The latest approved products from Arolana vendors.",
            "sort": "newest",
            "icon": "sparkles",
        },
        "bestsellers": {
            "title": "Best Sellers",
            "description": "Popular products customers are buying across Arolana.",
            "sort": "bestsellers",
            "icon": "trophy",
        },
        "trending": {
            "title": "Trending Deals",
            "description": "Products attracting the most interest and sales right now.",
            "sort": "trending",
            "icon": "fire",
        },
    }
    collection_info = collection_details.get(collection)
    if not collection_info:
        collection = ""

    sort_param = request.GET.get(
        "sort",
        collection_info["sort"] if collection_info else "featured",
    )
    sort_mapping = {
        "featured": ("-is_featured", "-rating_avg", "-created_at"),
        "newest": ("-created_at",),
        "bestsellers": ("-sales_count", "-rating_avg"),
        "trending": ("-views_count", "-sales_count"),
        "price_low": ("price",),
        "price_high": ("-price",),
        "rating": ("-rating_avg", "-rating_count"),
        "name_asc": ("name",),
        "name_desc": ("-name",),
    }

    sort_fields = sort_mapping.get(sort_param, sort_mapping["featured"])
    products = order_storefront_products(products, *sort_fields)

    # ====== Pagination ======
    paginator = Paginator(products, 24)
    page = request.GET.get("page", 1)

    try:
        products_page = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        products_page = paginator.page(1)

    # ====== Currency ======
    user_currency = get_user_currency(request)
    base_currency = get_base_currency()
    price_presets = []
    catalog_ranges = (
        ((0, 50000), (50000, 150000), (150000, 500000), (500000, 1000000), (1000000, None))
        if base_currency.code == "NGN"
        else ((0, 50), (50, 100), (100, 200), (200, 500), (500, None))
    )
    for minimum, maximum in catalog_ranges:
        converted_minimum = convert_price(minimum, base_currency, user_currency)
        converted_maximum = (
            convert_price(maximum, base_currency, user_currency)
            if maximum is not None else None
        )
        price_presets.append({
            "value": (
                f"{converted_minimum:.2f}+"
                if converted_maximum is None
                else f"{converted_minimum:.2f}-{converted_maximum:.2f}"
            ),
            "label": (
                f"Over {user_currency.format_amount(converted_minimum)}"
                if converted_maximum is None
                else (
                    f"Under {user_currency.format_amount(converted_maximum)}"
                    if minimum == 0
                    else (
                        f"{user_currency.format_amount(converted_minimum)} - "
                        f"{user_currency.format_amount(converted_maximum)}"
                    )
                )
            ),
        })

    # ====== Prepare categories and brands for template ======
    product_count_filter = Q(
        products__is_active=True,
        products__approval_status="approved",
    )

    categories_list = (
        Category.objects
        .filter(is_active=True, parent=None)
        .annotate(approved_product_count=Count("products", filter=product_count_filter))
        .order_by("order", "name")
    )

    brands_list = (
        Brand.objects
        .filter(is_active=True)
        .annotate(approved_product_count=Count("products", filter=product_count_filter))
        .order_by("name")
    )

    filter_counts = {
        "categories": {
            category.slug: category.approved_product_count
            for category in categories_list
        },
        "brands": {
            brand.slug: brand.approved_product_count
            for brand in brands_list
        },
    }

    # ====== AJAX Request (return JSON for filtering) ======
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        html = render_to_string(
            "products/product_grid.html",
            {
                "products": products_page,
                "user_currency": user_currency,
            },
            request=request,
        )
        pagination_html = render_to_string(
            "products/partials/ajax_pagination.html",
            {
                "page_obj": products_page,
                "pagination_id": "products-pagination",
                "wrapper_class": "pagination",
            },
            request=request,
        )

        return JsonResponse({
            "html": html,
            "pagination_html": pagination_html,
            "total_count": paginator.count,
            "start_index": products_page.start_index(),
            "end_index": products_page.end_index(),
        })

    # ====== Regular Page Load ======
    return render(request, "products/list.html", {
        "products": products_page,
        "categories": categories_list,
        "brands": brands_list,
        "product_conditions": Product.PRODUCT_CONDITION_CHOICES,
        "price_presets": price_presets,
        "filter_counts": filter_counts,
        "current_sort": sort_param,
        "user_currency": user_currency,
        "paginator": paginator,
        "shop_banner": shop_banner,
        "current_collection": collection,
        "collection_info": collection_info,
    })


def product_detail(request, slug):
    """
    Display detailed product page with reviews, Q&A, variants and full galleries.

    IMPORTANT:
    - Page refresh always loads the main product gallery.
    - No variant is auto-selected on page load.
    - Every variant sends ALL its images to variant_data_json.
    """
    product = get_object_or_404(
        Product.objects.select_related(
            'category',
            'brand',
            'vendor',
            'vendor__vendor_profile',
        ).prefetch_related(
            Prefetch(
                'images',
                queryset=ProductImage.objects.filter(is_active=True).order_by('-is_main', 'order', 'id')
            ),
            Prefetch(
                'variants',
                queryset=ProductVariant.objects.filter(is_active=True).prefetch_related(
                    Prefetch(
                        'images',
                        queryset=ProductVariantImage.objects.filter(is_active=True).order_by('-is_main', 'order', 'id')
                    )
                ).order_by('variant_type', 'name', 'value', 'id'),
                to_attr='active_variants'
            ),
            Prefetch(
                'reviews',
                queryset=ProductReview.objects.select_related('user').order_by('-created_at')[:10],
                to_attr='visible_reviews',
            ),
            Prefetch(
                'product_accessories',
                queryset=AccessoryProduct.objects.filter(
                    accessory__is_active=True,
                ).select_related('accessory'),
                to_attr='active_accessory_links',
            ),
            Prefetch(
                'article_links',
                queryset=ProductArticleLink.objects.filter(
                    is_active=True,
                    article__is_published=True,
                ).select_related('article', 'article__category', 'article__author').order_by('sort_order', '-article__published_at'),
                to_attr='active_article_links'
            ),
            Prefetch(
                'additional_videos',
                queryset=ProductVideo.objects.filter(is_active=True).order_by('display_order'),
                to_attr='active_videos',
            ),
            Prefetch(
                'questions',
                queryset=ProductQuestion.objects.filter(is_public=True).select_related(
                    'user',
                    'answered_by',
                ).order_by('-created_at')[:10],
                to_attr='visible_questions',
            )
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

    # ====== Currency ======
    user_currency = get_user_currency(request)
    base_currency = get_base_currency()

    # ====== Small safe image helpers ======
    def safe_url(image_field):
        """
        Return a usable URL for ImageField/FileField.
        Keeps the page safe if an image is missing or storage is not ready.
        """
        if not image_field:
            return None
        try:
            return image_field.url
        except Exception:
            return None

    def push_image(images, image_field, alt):
        """
        Add image once only. This prevents duplicates between:
        product.main_image + ProductImage marked as main,
        variant.image + ProductVariantImage marked as main.
        """
        original_src = safe_url(image_field)
        if not original_src:
            return
        src = get_optimized_image_url(image_field, 'product_detail')
        thumb = get_optimized_image_url(image_field, 'product_thumb')
        if original_src not in {image['original'] for image in images}:
            images.append({
                'src': src,
                'thumb': thumb,
                'original': original_src,
                'alt': alt or product.name,
            })

    def build_product_gallery():
        """
        Main product gallery.
        This is what must load after every refresh.
        """
        images = []

        # Main product image first
        push_image(images, product.main_image, product.name)

        # Then all ProductImage rows from admin
        for image in product.images.all():
            push_image(images, image.image, image.alt_text or product.name)

        return images

    def build_variant_gallery(variant):
        """
        Variant gallery.
        This sends ALL variant images to the frontend, not only variant.image.
        """
        images = []

        # Main variant image first
        push_image(
            images,
            variant.image,
            f"{product.name} - {variant.value}"
        )

        # Then all ProductVariantImage rows from admin
        for image in variant.images.all():
            push_image(
                images,
                image.image,
                image.alt_text or f"{product.name} - {variant.value}"
            )

        return images

    # ====== Variants ======
    all_variants = list(getattr(product, 'active_variants', []))

    variants_by_type = {}
    variant_options = {}

    for variant in all_variants:
        variant_type = variant.variant_type or 'other'

        if variant_type not in variants_by_type:
            variants_by_type[variant_type] = []
            variant_options[variant_type] = []

        variants_by_type[variant_type].append(variant)

        if variant.value not in variant_options[variant_type]:
            variant_options[variant_type].append(variant.value)

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

    # ====== CRITICAL FIX ======
    # Do not read variant_id from GET/POST for the page initial render.
    # Do not auto-select the first/default variant.
    # This makes every browser refresh return to the main product image/gallery.
    selected_variant = None
    selected_variant_id = None
    default_variant = all_variants[0] if all_variants else None

    current_price = product.price
    current_compare_price = product.compare_price

    # ====== Product Gallery JSON ======
    gallery_images = build_product_gallery()

    # ====== Variant Data JSON ======
    variant_data = {}

    for variant in all_variants:
        variant_price = product.price + variant.price_adjustment
        variant_compare_price = product.compare_price + variant.price_adjustment if product.compare_price else None
        converted_variant_price = convert_price(
            variant_price,
            base_currency,
            user_currency
        )

        variant_images = build_variant_gallery(variant)

        variant_data[str(variant.id)] = {
            'id': variant.id,
            'name': variant.name,
            'value': variant.value,
            'variant_type': variant.variant_type,
            'price': float(converted_variant_price or variant_price),
            'price_display': format_currency(variant_price, request),
            'price_raw': float(variant_price),
            'compare_price_display': format_currency(variant_compare_price, request) if variant_compare_price else '',
            'sku': variant.sku or f"{product.sku}-{variant.value[:3]}",
            'stock': variant.stock_quantity,
            'price_adjustment': float(variant.price_adjustment),
            'price_adjustment_display': format_currency(variant.price_adjustment, request),
            'image': variant_images[0]['src'] if variant_images else '',
            'images': variant_images,
            'gallery_images': variant_images,
            'variant_images': variant_images,
            'color_code': variant.color_code or '#CCCCCC',
            'is_available': variant.is_available,
        }

    # ====== Accessories ======
    accessories = getattr(product, 'active_accessory_links', [])

    # ====== Videos ======
    videos = getattr(product, 'active_videos', [])

    # ====== Editorial articles attached from admin ======
    product_article_links = list(getattr(product, 'active_article_links', []))
    product_article_links_hero = [link for link in product_article_links if link.placement == 'hero']
    product_article_links_overview = [link for link in product_article_links if link.placement in {'overview', 'description'}]
    product_article_links_tab = [link for link in product_article_links if link.placement == 'articles_tab']

    # ====== Related Products (APPROVED ONLY) ======
    related_products = Product.objects.filter(
        category=product.category,
        is_active=True,
        approval_status='approved'
    ).exclude(id=product.id).select_related(
        'brand', 'vendor', 'vendor__vendor_profile'
    )
    related_products = order_storefront_products(
        related_products,
        '-is_featured',
        '-rating_avg',
        '-sales_count',
    )[:8]

    top_rated = Product.objects.filter(
        category=product.category,
        is_active=True,
        rating_avg__gt=0,
        approval_status='approved'
    ).exclude(id=product.id).select_related('vendor', 'vendor__vendor_profile')
    top_rated = order_storefront_products(
        top_rated,
        '-rating_avg',
        '-rating_count',
    )[:8]

    bestsellers = Product.objects.filter(
        category=product.category,
        is_active=True,
        approval_status='approved'
    ).exclude(id=product.id).select_related('vendor', 'vendor__vendor_profile')
    bestsellers = order_storefront_products(
        bestsellers,
        '-sales_count',
        '-rating_avg',
    )[:8]

    frequently_bought_together = Product.objects.filter(
        is_active=True,
        approval_status='approved'
    ).exclude(id=product.id).select_related('vendor', 'vendor__vendor_profile')
    frequently_bought_together = order_storefront_products(
        frequently_bought_together,
        '-sales_count',
        '-rating_avg',
    )[:8]

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
    ).exclude(id=product.id).select_related('vendor', 'vendor__vendor_profile')
    ai_recommendations = order_storefront_products(
        ai_recommendations,
        '-views_count',
        '-rating_avg',
        '-sales_count',
    )[:8]

    # ====== Rating Percentages ======
    total_reviews = product.rating_count or 1
    review_breakdown = ProductReview.objects.filter(product=product).aggregate(
        five_star_count=Count('id', filter=Q(rating=5)),
        four_star_count=Count('id', filter=Q(rating=4)),
        three_star_count=Count('id', filter=Q(rating=3)),
    )
    five_star_count = review_breakdown['five_star_count']
    four_star_count = review_breakdown['four_star_count']
    three_star_count = review_breakdown['three_star_count']
    question_count = ProductQuestion.objects.filter(
        product=product,
        is_public=True,
    ).count()

    five_star_percent = int((five_star_count / total_reviews) * 100)
    four_star_percent = int((four_star_count / total_reviews) * 100)
    three_star_percent = int((three_star_count / total_reviews) * 100)

    # ====== Explore Categories ======
    all_categories = Category.objects.filter(
        is_active=True,
        parent=None,
    ).annotate(
        approved_product_count=Count(
            'products',
            filter=Q(
                products__is_active=True,
                products__approval_status='approved',
            ),
        )
    ).order_by('name')[:12]

    # ====== Wishlist ======
    in_wishlist = False
    if request.user.is_authenticated:
        in_wishlist = Wishlist.objects.filter(
            user=request.user,
            product=product
        ).exists()
    else:
        guest_wishlist = {str(product_id) for product_id in request.session.get(GUEST_WISHLIST_SESSION_KEY, [])}
        in_wishlist = str(product.id) in guest_wishlist

    context = {
        'product': product,
        'size_variants': size_variants,
        'color_variants': color_variants,
        'all_variants': all_variants,
        'variants_by_type': variants_by_type,
        'variant_options': variant_options,
        'variant_groups': variant_groups,

        # JSON for frontend gallery + variant switching
        'variant_data_json': json.dumps(variant_data),
        'gallery_images': gallery_images,
        'gallery_images_json': json.dumps(gallery_images),

        # CRITICAL: keep empty on refresh/page load
        'selected_variant': selected_variant,
        'selected_variant_id': selected_variant_id,
        'default_variant': default_variant,

        # Main product price on refresh/page load
        'current_price': current_price,
        'current_compare_price': current_compare_price,

        'vendor_chat_available': user_has_paid_subscription(product.vendor),
        'accessories': accessories,
        'product_accessories': accessories,
        'videos': videos,
        'product_videos': videos,
        'product_article_links': product_article_links,
        'product_article_links_hero': product_article_links_hero,
        'product_article_links_overview': product_article_links_overview,
        'product_article_links_tab': product_article_links_tab,
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
        'question_count': question_count,
        'user_currency': user_currency,
        'product_detail_sections': ProductDetailSection.objects.filter(is_enabled=True, web_enabled=True).order_by('display_order', 'title'),
        'product_detail_fields': ProductDetailFieldConfig.objects.filter(is_enabled=True).order_by('display_order', 'label'),
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
    ).select_related('brand', 'vendor', 'vendor__vendor_profile')
    
    # ====== Sorting ======
    sort_param = request.GET.get('sort', 'featured')
    sort_mapping = {
        'featured': ('-is_featured', '-rating_avg', '-created_at'),
        'newest': ('-created_at',),
        'bestsellers': ('-sales_count', '-rating_avg'),
        'price_low': ('price',),
        'price_high': ('-price',),
        'rating': ('-rating_avg', '-rating_count'),
        'name_asc': ('name',),
        'name_desc': ('-name',),
    }
    
    sort_fields = sort_mapping.get(sort_param, sort_mapping['featured'])
    products = order_storefront_products(products, *sort_fields)
    
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
    
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        html = render_to_string(
            "products/product_grid.html",
            {
                "products": products_page,
                "user_currency": user_currency,
            },
            request=request,
        )
        pagination_html = render_to_string(
            "products/partials/ajax_pagination.html",
            {
                "page_obj": products_page,
                "pagination_id": "category-pagination",
                "wrapper_class": "mt-8 flex justify-center",
            },
            request=request,
        )
        return JsonResponse({
            "html": html,
            "pagination_html": pagination_html,
            "total_count": products_page.paginator.count,
            "start_index": products_page.start_index() if products_page.paginator.count else 0,
            "end_index": products_page.end_index() if products_page.paginator.count else 0,
        })

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

def toggle_wishlist(request, slug):
    """Toggle product in wishlist"""
    product = get_object_or_404(Product, slug=slug, is_active=True, approval_status='approved')

    if request.user.is_authenticated:
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

        wishlist_count = request.user.wishlist_items.count()
    else:
        wishlist_ids = [str(product_id) for product_id in request.session.get(GUEST_WISHLIST_SESSION_KEY, [])]
        product_id = str(product.id)

        if product_id in wishlist_ids:
            wishlist_ids = [saved_id for saved_id in wishlist_ids if saved_id != product_id]
            in_wishlist = False
            message = f'{product.name} removed from wishlist'
        else:
            wishlist_ids.append(product_id)
            in_wishlist = True
            message = f'{product.name} added to wishlist'

        request.session[GUEST_WISHLIST_SESSION_KEY] = wishlist_ids
        request.session.modified = True
        wishlist_count = len(wishlist_ids)
    
    messages.success(request, message)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'in_wishlist': in_wishlist,
            'message': message,
            'wishlist_count': wishlist_count,
        })
    
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
    """API: Get variant details with pricing and ALL variant images."""
    try:
        variant = ProductVariant.objects.select_related('product').prefetch_related(
            Prefetch(
                'images',
                queryset=ProductVariantImage.objects.filter(is_active=True).order_by('-is_main', 'order', 'id')
            )
        ).get(
            id=variant_id,
            is_active=True
        )
        product = variant.product

        def safe_url(image_field):
            if not image_field:
                return None
            try:
                return image_field.url
            except Exception:
                return None

        def push_image(images, src, alt):
            if not src:
                return
            if src not in {image['src'] for image in images}:
                images.append({
                    'src': src,
                    'alt': alt or product.name,
                })

        variant_images = []
        push_image(
            variant_images,
            safe_url(variant.image),
            f"{product.name} - {variant.value}"
        )
        for image in variant.images.all():
            push_image(
                variant_images,
                safe_url(image.image),
                image.alt_text or f"{product.name} - {variant.value}"
            )

        product_gallery = []
        push_image(product_gallery, safe_url(product.main_image), product.name)
        for image in product.images.filter(is_active=True).order_by('-is_main', 'order', 'id'):
            push_image(product_gallery, safe_url(image.image), image.alt_text or product.name)

        # ====== Currency Conversion ======
        user_currency = get_user_currency(request)
        base_currency = get_base_currency()

        final_price_raw = product.price + variant.price_adjustment
        final_price = convert_price(final_price_raw, base_currency, user_currency)

        return JsonResponse({
            'success': True,
            'variant': {
                'id': variant.id,
                'name': variant.name,
                'value': variant.value,
                'variant_type': variant.variant_type,
                'price_adjustment': float(variant.price_adjustment),
                'stock_quantity': variant.stock_quantity,
                'image': variant_images[0]['src'] if variant_images else None,
                'images': variant_images,
                'gallery_images': variant_images,
                'variant_images': variant_images,
                'is_available': variant.is_available,
            },
            'product': {
                'id': product.id,
                'name': product.name,
                'base_price': float(product.price),
                'final_price': float(final_price or final_price_raw),
                'final_price_display': format_currency(final_price_raw, request),
                'main_image': safe_url(product.main_image),
                'gallery_images': product_gallery,
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
    base_currency = get_base_currency()
    
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
    if not request.user.is_authenticated:
        return JsonResponse({'count': _guest_cart_count(_guest_cart_data(request))})

    if not Cart:
        return JsonResponse({'count': 0})

    if _guest_cart_data(request):
        _merge_guest_cart_into_user_cart(request)
    
    cart = Cart.objects.filter(user=request.user, is_active=True).first()
    count = getattr(cart, 'total_items', 0) if cart else 0
    
    return JsonResponse({'count': count})


def checkout(request):
    """Checkout page"""
    if not request.user.is_authenticated:
        messages.info(request, 'Please sign in or create an account to continue checkout.')
        login_url = f"{reverse('account_login')}?next={request.get_full_path()}"
        return redirect(login_url)
    
    if not Cart or not CartItem:
        messages.error(request, 'Checkout feature not available')
        return redirect('products:list')
    
    cart = _merge_guest_cart_into_user_cart(request) or Cart.objects.filter(user=request.user, is_active=True).first()
    
    if not cart or cart.items.count() == 0:
        messages.info(request, 'Your cart is empty.')
        return redirect('products:list')
    
    # Checkout now exposes only service levels. Arolana chooses the matching
    # delivery provider behind the scenes so customers do not see confusing
    # pickup/dispatch provider choices.
    delivery_providers = []
    delivery_origin = {}
    package_weight_kg = Decimal('0.00')
    try:
        from deliveries.services import cart_package_weight_kg, cart_pickup_context
        delivery_origin = cart_pickup_context(cart)
        package_weight_kg = cart_package_weight_kg(cart)
    except Exception:
        delivery_origin = {}

    delivery_options = [
        {
            'value': 'standard',
            'label': 'Standard Delivery',
            'description': 'Reliable delivery calculated by your location.',
            'icon': 'fa-truck',
            'provider_type': 'manual_dispatch',
        },
        {
            'value': 'express',
            'label': 'Express Delivery',
            'description': 'Faster dispatch where available.',
            'icon': 'fa-bolt',
            'provider_type': 'arolana_driver',
        },
    ]

    return render(request, 'products/checkout.html', {
        'cart': cart,
        'payment_options': get_gateway_options(),
        'delivery_options': delivery_options,
        'delivery_providers': delivery_providers,
        'delivery_origin': delivery_origin,
        'package_weight_kg': package_weight_kg,
        **_support_contact_context(),
    })


def add_accessory_to_cart(request, accessory_id):
    """Add accessory directly to cart"""
    if not Cart or not CartItem:
        return redirect('products:list')
    
    accessory = get_object_or_404(Accessory, id=accessory_id, is_active=True)
    quantity = _safe_quantity(request.POST.get('quantity', 1))

    if request.user.is_authenticated:
        cart, created = Cart.objects.get_or_create(user=request.user, is_active=True)

        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            product=None,
            accessory=accessory,
            defaults={'quantity': quantity, 'price_at_add': accessory.price}
        )

        if not created:
            cart_item.quantity = min(cart_item.quantity + quantity, 999)
            cart_item.save(update_fields=['quantity'])

        cart_count = getattr(cart, 'total_items', 0)
    else:
        cart_data = _guest_cart_data(request)
        key = _guest_cart_key(accessory=accessory)
        current_quantity = int(cart_data.get(key, {}).get('quantity') or 0)
        cart_data[key] = {
            'accessory_id': accessory.id,
            'quantity': min(current_quantity + quantity, 999),
            'price_at_add': str(accessory.price),
        }
        cart_data = _save_guest_cart(request, cart_data)
        cart_count = _guest_cart_count(cart_data)
    
    messages.success(request, f'{accessory.name} added to cart!')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'cart_count': cart_count,
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

def _mobile_get_value(obj, *field_names, default=None):
    for field_name in field_names:
        if hasattr(obj, field_name):
            value = getattr(obj, field_name)
            if value is not None:
                return value
    return default


def _mobile_get_image_url(request, product):
    image = _mobile_get_value(
        product,
        "image",
        "main_image",
        "thumbnail",
        "featured_image",
        "product_image",
        "cover_image",
        default=None,
    )

    if not image:
        return None

    try:
        image_url = image.url
    except Exception:
        return None

    if image_url.startswith("http://") or image_url.startswith("https://"):
        return image_url

    return request.build_absolute_uri(image_url)


def parse_price_safe(value):
    try:
        return Decimal(str(value or "0").replace(",", ""))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _mobile_file_url(request, file_field):
    if not file_field:
        return None

    try:
        file_url = file_field.url
    except Exception:
        return None

    if file_url.startswith("http://") or file_url.startswith("https://"):
        return file_url

    return request.build_absolute_uri(file_url)


def _category_descendant_ids(category):
    if not category:
        return []

    category_ids = [category.id]
    stack = list(category.children.filter(is_active=True).only("id"))

    while stack:
        child = stack.pop()
        category_ids.append(child.id)
        stack.extend(child.children.filter(is_active=True).only("id"))

    return category_ids


def _mobile_category_product_count(category):
    if not category:
        return 0

    return Product.objects.filter(
        category_id__in=_category_descendant_ids(category),
        is_active=True,
        approval_status="approved",
    ).count()


def _mobile_category_payload(request, category, include_children=True):
    if not category:
        return None

    children = []
    if include_children:
        children = [
            _mobile_category_payload(request, child, include_children=False)
            for child in category.children.filter(is_active=True).order_by("name")
        ]
        children = [child for child in children if child]

    return {
        "id": category.id,
        "name": category.name,
        "slug": category.slug,
        "description": strip_tags(category.description or "")[:180],
        "image": _mobile_file_url(request, getattr(category, "image", None)),
        "background_image": _mobile_file_url(request, getattr(category, "background_image", None)),
        "url": request.build_absolute_uri(reverse("products:category", args=[category.slug])),
        "hero_title": getattr(category, "hero_title", "") or "",
        "hero_subtitle": getattr(category, "hero_subtitle", "") or "",
        "show_hero_title": bool(getattr(category, "show_hero_title", True)),
        "show_hero_subtitle": bool(getattr(category, "show_hero_subtitle", True)),
        "show_hero_text": bool(getattr(category, "show_hero_title", True) or getattr(category, "show_hero_subtitle", True)),
        "hero_height_mobile": getattr(category, "hero_height_mobile", None) or 360,
        "hero_image_brightness": getattr(category, "hero_image_brightness", None) or 62,
        "hero_text_color": getattr(category, "hero_text_color", "") or "",
        "product_count": _mobile_category_product_count(category),
        "children": children,
    }


def _mobile_vendor_payload(request, vendor_profile, include_products=False):
    if not vendor_profile:
        return None

    vendor_user = getattr(vendor_profile, "user", None)
    product_qs = Product.objects.filter(
        vendor=vendor_user,
        is_active=True,
        approval_status="approved",
    ) if vendor_user else Product.objects.none()

    badges = []
    vendor_type = getattr(vendor_profile, "vendor_type", "retailer")
    vendor_type_display = vendor_profile.get_vendor_type_display() if hasattr(vendor_profile, "get_vendor_type_display") else vendor_type.replace("_", " ").title()
    if getattr(vendor_profile, "is_verified", False):
        badges.append(f"Verified {vendor_type_display}")
    if vendor_type == "manufacturer" and getattr(vendor_profile, "manufacturer_verified", False):
        badges.append(getattr(vendor_profile, "manufacturer_badge_label", "") or "Verified Manufacturer")
    if getattr(vendor_profile, "is_trusted", False):
        badges.append("Trusted Supplier")
    if getattr(vendor_profile, "is_top_rated", False):
        badges.append("Top Supplier")
    subscription_badge = getattr(vendor_profile, "badge_level", "") or getattr(vendor_profile, "subscription_plan_label", "")
    if subscription_badge:
        badges.append(subscription_badge)

    payload = {
        "id": vendor_profile.id,
        "user_id": getattr(vendor_user, "id", None),
        "name": vendor_profile.store_name,
        "store_name": vendor_profile.store_name,
        "company_name": getattr(vendor_profile, "company_name", ""),
        "vendor_type": vendor_type,
        "vendor_type_display": vendor_type_display,
        "country": getattr(vendor_profile, "country", ""),
        "logo": _mobile_file_url(request, getattr(vendor_profile, "store_logo", None)),
        "banner": _mobile_file_url(request, getattr(vendor_profile, "store_banner", None)),
        "description": getattr(vendor_profile, "description", ""),
        "verified": bool(getattr(vendor_profile, "is_verified", False)),
        "is_verified": bool(getattr(vendor_profile, "is_verified", False)),
        "manufacturer_verified": bool(vendor_type == "manufacturer" and getattr(vendor_profile, "manufacturer_verified", False)),
        "manufacturer_badge_label": getattr(vendor_profile, "manufacturer_badge_label", "") or "Verified Manufacturer",
        "badges": badges,
        "subscription_tier": getattr(vendor_profile, "subscription_tier", "free"),
        "subscription_label": subscription_badge,
        "subscription_badge": subscription_badge,
        "rating_avg": str(getattr(vendor_profile, "rating_avg", "0") or "0"),
        "total_reviews": getattr(vendor_profile, "total_reviews", 0),
        "total_sales": getattr(vendor_profile, "total_sales", 0),
        "followers_count": getattr(vendor_profile, "followers_count", 0),
        "total_products": product_qs.count(),
        "response_time": getattr(vendor_profile, "response_time", ""),
        "fulfillment_rate": str(getattr(vendor_profile, "fulfillment_rate", "") or ""),
        "return_rate": str(getattr(vendor_profile, "return_rate", "") or ""),
        "support_email": getattr(vendor_profile, "support_email", ""),
        "support_phone": getattr(vendor_profile, "support_phone", ""),
        "website": getattr(vendor_profile, "website", ""),
        "business_address": getattr(vendor_profile, "business_address", ""),
        "manufacturer_address": getattr(vendor_profile, "manufacturer_address", ""),
        "warehouse_address": getattr(vendor_profile, "warehouse_address", ""),
        "pickup_address": getattr(vendor_profile, "pickup_address", ""),
        "factory_name": getattr(vendor_profile, "factory_name", ""),
        "factory_video_url": getattr(vendor_profile, "factory_video_url", ""),
        "years_in_business": getattr(vendor_profile, "years_in_business", None),
        "number_of_employees": getattr(vendor_profile, "number_of_employees", None),
        "production_capacity": getattr(vendor_profile, "production_capacity", ""),
        "quality_control_details": getattr(vendor_profile, "quality_control_details", ""),
        "export_countries": getattr(vendor_profile, "export_countries", ""),
        "main_product_categories": getattr(vendor_profile, "main_product_categories", ""),
        "chat_available": bool(vendor_user and user_has_paid_subscription(vendor_user)),
        "url": request.build_absolute_uri(vendor_profile.get_absolute_url()) if hasattr(vendor_profile, "get_absolute_url") else "",
    }

    if include_products:
        payload["products"] = [_mobile_product_payload(request, product) for product in product_qs.select_related("category", "brand", "vendor")[:60]]

    return payload


def _mobile_ad_payload(request, ad, ad_type):
    if ad_type == "creative":
        image = _mobile_file_url(request, getattr(ad, "image_mobile", None) or getattr(ad, "image", None))
        return {
            "id": f"creative-{ad.id}",
            "type": "creative",
            "title": ad.headline,
            "description": ad.description,
            "cta_text": ad.cta_text,
            "cta_background_color": ad.cta_background_color,
            "cta_text_color": ad.cta_text_color,
            "url": ad.clickthrough_url,
            "image": image,
            "creative_type": ad.creative_type,
        }

    if ad_type == "banner":
        image = _mobile_file_url(request, getattr(ad, "image_mobile", None) or getattr(ad, "image", None))
        placement = getattr(ad, "placement", None)
        return {
            "id": f"banner-{ad.id}",
            "type": "banner",
            "title": ad.title,
            "description": ad.description,
            "cta_text": ad.cta_text,
            "cta_background_color": ad.cta_background_color,
            "cta_text_color": ad.cta_text_color,
            "url": ad.target_url,
            "image": image,
            "video_url": ad.video_url,
            "mobile_height": ad.mobile_height_override or ad.height_override or (placement.height if placement else 220),
            "mobile_width": ad.mobile_width_override or ad.width_override or (placement.width if placement else 1200),
            "mobile_image_fit": ad.mobile_image_fit,
            "image_fit": ad.image_fit,
        }

    image = _mobile_file_url(request, getattr(ad, "image", None))
    return {
        "id": f"ad-{ad.id}",
        "type": "simple",
        "title": ad.title,
        "description": ad.description,
        "cta_text": ad.button_text,
        "cta_background_color": ad.button_background_color,
        "cta_text_color": ad.button_text_color,
        "url": ad.target_url,
        "image": image,
        "is_featured": ad.is_featured,
    }


def _mobile_home_ads_payload(request, limit=8):
    now = timezone.now()
    ads_payload = []

    if AdCreative:
        creatives = (
            AdCreative.objects.filter(
                is_active=True,
                campaign__status="active",
                campaign__approved=True,
                campaign__start_date__lte=now,
            )
            .filter(Q(campaign__end_date__isnull=True) | Q(campaign__end_date__gte=now))
            .select_related("campaign")
            .order_by("-ab_weight", "-created_at")[:limit]
        )
        ads_payload.extend(_mobile_ad_payload(request, creative, "creative") for creative in creatives)

    if AdBanner and AdPlacement:
        placement = AdPlacement.objects.filter(slug="homepage", is_active=True).first()
        if placement:
            banners = (
                AdBanner.objects.filter(
                    placement=placement,
                    is_active=True,
                    start_date__lte=now,
                )
                .filter(Q(end_date__isnull=True) | Q(end_date__gte=now))
                .select_related("placement", "creative", "campaign")
                .order_by("-priority", "-created_at")[:limit]
            )
            ads_payload.extend(_mobile_ad_payload(request, banner, "banner") for banner in banners)

    if Advertisement:
        simple_ads = Advertisement.objects.filter(
            placement="homepage",
            is_active=True,
            start_date__lte=now,
        ).filter(Q(end_date__isnull=True) | Q(end_date__gte=now))
        if request.user.is_authenticated:
            simple_ads = simple_ads.filter(show_to_logged_in=True)
        else:
            simple_ads = simple_ads.filter(show_to_guests=True)
        ads_payload.extend(_mobile_ad_payload(request, ad, "simple") for ad in simple_ads.order_by("-is_featured", "-created_at")[:limit])

    seen = set()
    unique_ads = []
    for ad in ads_payload:
        if ad["id"] in seen:
            continue
        seen.add(ad["id"])
        unique_ads.append(ad)
        if len(unique_ads) >= limit:
            break
    return unique_ads


def _mobile_home_video_payload(request):
    if not HomepageVideoSection:
        return {}

    video = HomepageVideoSection.objects.filter(is_active=True).order_by("display_order", "id").first()
    if not video:
        return {}

    video_url = ""
    embed_url = ""
    if video.video_source == "local" and video.local_video:
        video_url = _mobile_file_url(request, video.local_video)
    elif video.video_source == "youtube":
        video_url = video.youtube_url
        if video.youtube_id:
            embed_url = f"https://www.youtube.com/embed/{video.youtube_id}"
    elif video.video_source == "vimeo":
        video_url = video.vimeo_url
        if video.vimeo_id:
            embed_url = f"https://player.vimeo.com/video/{video.vimeo_id}"

    return {
        "id": video.id,
        "title": video.title,
        "subtitle": video.subtitle,
        "video_source": video.video_source,
        "video_url": video_url,
        "embed_url": embed_url,
        "youtube_id": video.youtube_id,
        "vimeo_id": video.vimeo_id,
        "poster_image": _mobile_file_url(request, video.poster_image),
        "position": video.position,
        "info_position": video.info_position,
        "video_height": video.video_height,
        "autoplay": video.autoplay,
        "loop": video.loop,
        "show_controls": video.show_controls,
        "background_color": video.background_color,
        "text_color": video.text_color,
        "button_text": video.button_text,
        "button_url": video.button_url,
        "button_color": video.button_color,
    }


def _mobile_product_payload(request, product):
    category = _mobile_get_value(product, "category", default=None)
    brand = _mobile_get_value(product, "brand", default=None)
    vendor_user = getattr(product, "vendor", None)
    vendor_profile = getattr(vendor_user, "vendor_profile", None) if vendor_user else None

    category_name = category.name if category and hasattr(category, "name") else "Arolana"
    brand_name = brand.name if brand and hasattr(brand, "name") else ""

    regular_price = _mobile_get_value(product, "regular_price", "compare_price", "old_price", default="")
    price = _mobile_get_value(product, "price", "sale_price", "current_price", "amount", default="")
    rating = getattr(product, "rating_avg", 0) or 0

    minimum_order_quantity = getattr(product, "minimum_order_quantity", 1) or 1
    wholesale_price = getattr(product, "wholesale_price", None)
    bulk_price = getattr(product, "bulk_price", None)
    vendor_type = getattr(vendor_profile, "vendor_type", "") if vendor_profile else ""
    vendor_type_display = vendor_profile.get_vendor_type_display() if vendor_profile and hasattr(vendor_profile, "get_vendor_type_display") else vendor_type.replace("_", " ").title()
    manufacturer_verified = bool(vendor_type == "manufacturer" and getattr(vendor_profile, "manufacturer_verified", False)) if vendor_profile else False
    vendor_verified = bool(getattr(vendor_profile, "is_verified", False)) if vendor_profile else False
    vendor_name = getattr(vendor_profile, "store_name", "") if vendor_profile else ""

    badges = []
    if vendor_verified:
        badges.append(f"Verified {vendor_type_display or 'Vendor'}")
    if manufacturer_verified:
        badges.append(getattr(vendor_profile, "manufacturer_badge_label", "") or "Verified Manufacturer")
    if minimum_order_quantity > 1:
        badges.append(f"MOQ {minimum_order_quantity}")
    if wholesale_price or bulk_price:
        badges.append("Wholesale")
    subscription_badge = getattr(vendor_profile, "badge_level", "") or getattr(vendor_profile, "subscription_plan_label", "") if vendor_profile else ""
    if subscription_badge:
        badges.append(subscription_badge)

    return {
        "id": product.id,
        "name": _mobile_get_value(product, "name", "title", "product_name", default="Unnamed product"),
        "slug": _mobile_get_value(product, "slug", default=""),
        "price": str(price or ""),
        "regular_price": str(regular_price or ""),
        "compare_price": str(regular_price or ""),
        "wholesale_price": str(wholesale_price or ""),
        "bulk_price": str(bulk_price or ""),
        "minimum_order_quantity": minimum_order_quantity,
        "moq": minimum_order_quantity,
        "moq_unit": getattr(product, "moq_unit", "") or "unit",
        "lead_time_days": getattr(product, "lead_time_days", None),
        "country_of_origin": getattr(product, "country_of_origin", "") or "",
        "manufacturer_sku": getattr(product, "manufacturer_sku", "") or "",
        "sample_available": bool(getattr(product, "sample_available", False)),
        "sample_price": str(getattr(product, "sample_price", "") or ""),
        "category_name": category_name,
        "category_slug": getattr(category, "slug", "") if category else "",
        "brand_name": brand_name,
        "brand": brand_name,
        "condition": getattr(product, "condition", "") or "",
        "sku": getattr(product, "sku", "") or "",
        "arolana_sku": getattr(product, "sku", "") or "",
        "stock_quantity": getattr(product, "stock_quantity", 0) or 0,
        "in_stock": bool(getattr(product, "stock_quantity", 0) or getattr(product, "is_in_stock", False)),
        "is_featured": bool(getattr(product, "is_featured", False)),
        "is_new": bool(getattr(product, "is_new", False)),
        "is_bestseller": bool(getattr(product, "is_bestseller", False)),
        "rating": str(rating or 0),
        "rating_count": getattr(product, "rating_count", 0) or 0,
        "image": _mobile_get_image_url(request, product),
        "url": request.build_absolute_uri(reverse("products:detail", args=[product.slug])),
        "vendor_id": getattr(vendor_profile, "id", None),
        "vendor_user_id": getattr(vendor_user, "id", None),
        "vendor_name": vendor_name,
        "vendor_type": vendor_type,
        "vendor_type_display": vendor_type_display,
        "vendor_verified": vendor_verified,
        "manufacturer_verified": manufacturer_verified,
        "subscription_tier": getattr(vendor_profile, "subscription_tier", "free") if vendor_profile else "free",
        "subscription_label": subscription_badge,
        "subscription_badge": subscription_badge,
        "badges": badges,
        "wholesale_available": bool(wholesale_price or bulk_price),
        "rfq_available": bool(vendor_profile),
    }


@require_GET
def mobile_home_api(request):
    product_queryset = Product.objects.filter(
        is_active=True,
        approval_status="approved",
    ).select_related(
        "category",
        "brand",
        "vendor",
        "vendor__vendor_profile",
    )
    product_queryset = order_storefront_products(
        product_queryset,
        "-is_featured",
        "-sales_count",
        "-created_at",
    )[:48]

    hero_banner_payloads = []
    if HeroBanner:
        hero_banners = HeroBanner.objects.filter(is_active=True).order_by("display_order", "-created_at")[:8]
        for banner in hero_banners:
            hero_banner_payloads.append({
                "id": banner.id,
                "title": banner.title,
                "subtitle": banner.subtitle,
                "description": banner.description,
                "show_content": banner.show_content,
                "show_title": banner.show_title,
                "show_subtitle": banner.show_subtitle,
                "show_description": banner.show_description,
                "show_button": banner.show_buttons,
                "button_text": banner.button1_text,
                "button_url": banner.button1_url,
                "button1_text": banner.button1_text,
                "button1_url": banner.button1_url,
                "button2_text": banner.button2_text,
                "button2_url": banner.button2_url,
                "button3_text": banner.button3_text,
                "button3_url": banner.button3_url,
                "effective_slide_link_url": banner.effective_slide_link_url,
                "slide_link_url": banner.slide_link_url,
                "enable_slide_link": banner.enable_slide_link,
                "mobile_content_layout": banner.mobile_content_layout,
                "content_layout": banner.mobile_content_layout,
                "text_alignment": banner.text_alignment,
                "content_position": banner.content_position,
                "overlay_color": banner.overlay_color,
                "overlay_opacity": banner.overlay_opacity,
                "text_color": banner.text_color,
                "desktop_height": banner.desktop_height,
                "tablet_height": banner.tablet_height,
                "mobile_height": banner.mobile_height,
                "image_fit_mobile": banner.image_fit_mobile,
                "image_fit_tablet": banner.image_fit_tablet,
                "image_fit_desktop": banner.image_fit_desktop,
                "image_position_mobile": banner.image_position_mobile,
                "image_mobile": _mobile_file_url(request, banner.image_mobile),
                "image_tablet": _mobile_file_url(request, banner.image_tablet),
                "image_desktop": _mobile_file_url(request, banner.image_desktop),
                "image": _mobile_file_url(request, banner.image_mobile or banner.image_tablet or banner.image_desktop),
                "source": "hero_banners",
            })

    promo_banner_payloads = []
    if HomepageBanner:
        banners = (
            HomepageBanner.objects.filter(is_active=True, show_on_homepage=True)
            .prefetch_related("uploaded_images")
            .order_by("display_order", "-id")[:8]
        )
        for banner in banners:
            uploaded_images = [image for image in banner.uploaded_images.all() if image.is_active]
            background = next((image for image in uploaded_images if image.position == "background"), None)
            center = next((image for image in uploaded_images if image.position == "center"), None)
            left = next((image for image in uploaded_images if image.position == "left"), None)
            right = next((image for image in uploaded_images if image.position == "right"), None)
            image = background or center or (uploaded_images[0] if uploaded_images else None)
            promo_banner_payloads.append({
                "id": banner.id,
                "title": banner.title,
                "subtitle": banner.subtitle,
                "button_text": banner.button_text,
                "button_url": banner.button_url,
                "background_color_start": banner.background_color_start,
                "background_color_end": banner.background_color_end,
                "content_layout": banner.content_layout,
                "content_alignment": banner.content_alignment,
                "background_fit": banner.background_fit,
                "background_position": banner.background_position,
                "background_opacity": banner.background_opacity,
                "desktop_height": banner.desktop_height,
                "tablet_height": banner.tablet_height,
                "mobile_height": banner.mobile_height,
                "image": _mobile_file_url(request, image.image) if image else None,
                "background_image": _mobile_file_url(request, background.image) if background else None,
                "center_image_upload": _mobile_file_url(request, center.image) if center else None,
                "left_image_upload": _mobile_file_url(request, left.image) if left else None,
                "right_image_upload": _mobile_file_url(request, right.image) if right else None,
                "left_image": banner.left_image,
                "right_image": banner.right_image,
                "center_image": banner.center_image,
                "banner_style": banner.banner_style,
                "placement": banner.placement,
                "show_content": banner.content_layout != "image_only",
                "show_button": banner.show_button,
                "source": "homepage_banners",
            })

    homepage_background = {}
    appearance = HomePageAppearance.objects.filter(is_active=True).order_by("-updated_at", "-id").first()
    if appearance:
        homepage_background = {
            "desktop_background_image": _mobile_file_url(request, appearance.desktop_background_image),
            "mobile_background_image": _mobile_file_url(request, appearance.mobile_background_image),
            "image": _mobile_file_url(request, appearance.mobile_background_image or appearance.desktop_background_image),
            "desktop_overlay_opacity": str(appearance.desktop_overlay_opacity),
            "mobile_overlay_opacity": str(appearance.mobile_overlay_opacity),
            "desktop_position": appearance.desktop_position,
            "mobile_position": appearance.mobile_position,
            "blur_background": appearance.blur_background,
            "make_sections_glass": appearance.make_sections_glass,
        }

    category_payloads = []
    if HomepageCategory:
        homepage_categories = (
            HomepageCategory.objects.filter(is_active=True, category__is_active=True)
            .select_related("category")
            .order_by("display_order")[:12]
        )
        category_payloads = [
            _mobile_category_payload(request, item.category)
            for item in homepage_categories
            if item.category
        ]

    if not category_payloads:
        roots = Category.objects.filter(is_active=True, parent=None).order_by("name")[:12]
        category_payloads = [_mobile_category_payload(request, category) for category in roots]

    products = [_mobile_product_payload(request, product) for product in product_queryset]
    verified_vendors = []
    factory_direct_manufacturers = []
    top_retailers = []
    distributors_wholesalers = []
    service_providers = []
    top_vendors = []
    if VendorProfile:
        section_payloads = {}
        if HomepageVendorSection:
            for section in HomepageVendorSection.objects.filter(is_active=True).order_by("sort_order", "title"):
                section_payloads[section.section_type] = [
                    _mobile_vendor_payload(request, vendor_profile)
                    for vendor_profile in section.get_vendor_queryset()
                    if vendor_profile
                ]

        verified_vendors = section_payloads["verified_vendors"] if "verified_vendors" in section_payloads else [
            _mobile_vendor_payload(request, vendor_profile)
            for vendor_profile in VendorProfile.objects.filter(
                approval_status="approved",
                is_verified=True,
            ).select_related("user").order_by("-manufacturer_verified", "-priority_score", "-rating_avg")[:12]
        ]
        factory_direct_manufacturers = section_payloads["factory_direct_manufacturers"] if "factory_direct_manufacturers" in section_payloads else [
            _mobile_vendor_payload(request, vendor_profile)
            for vendor_profile in VendorProfile.objects.filter(
                approval_status="approved",
                vendor_type="manufacturer",
            ).filter(
                Q(is_verified=True) | Q(manufacturer_verified=True)
            ).select_related("user").order_by("-manufacturer_verified", "-priority_score", "-rating_avg")[:12]
        ]
        top_vendors = verified_vendors[:8]
        top_retailers = section_payloads["top_retailers"] if "top_retailers" in section_payloads else [
            _mobile_vendor_payload(request, vendor_profile)
            for vendor_profile in VendorProfile.objects.filter(approval_status="approved", is_verified=True, vendor_type="retailer").select_related("user").order_by("-priority_score", "-rating_avg")[:12]
        ]
        distributors_wholesalers = section_payloads["distributors_wholesalers"] if "distributors_wholesalers" in section_payloads else [
            _mobile_vendor_payload(request, vendor_profile)
            for vendor_profile in VendorProfile.objects.filter(approval_status="approved", is_verified=True, vendor_type__in=["distributor", "wholesaler"]).select_related("user").order_by("-priority_score", "-rating_avg")[:12]
        ]
        service_providers = section_payloads["service_providers"] if "service_providers" in section_payloads else [
            _mobile_vendor_payload(request, vendor_profile)
            for vendor_profile in VendorProfile.objects.filter(approval_status="approved", is_verified=True, vendor_type="service_provider").select_related("user").order_by("-priority_score", "-rating_avg")[:12]
        ]

    factory_direct = [
        item for item in products
        if item.get("vendor_type") == "manufacturer"
    ][:12]
    wholesale_deals = [
        item for item in products
        if item.get("wholesale_available")
    ][:12]
    moq_products = [
        item for item in products
        if int(item.get("minimum_order_quantity") or 1) > 1
    ][:12]
    price_drop_products = [
        item for item in products
        if parse_price_safe(item.get("compare_price")) > parse_price_safe(item.get("price"))
    ][:12]

    return JsonResponse({
        "hero_banners": hero_banner_payloads,
        "promo_banners": promo_banner_payloads,
        "homepage_banners": promo_banner_payloads,
        "homepage_background": homepage_background,
        "homepage_ads": _mobile_home_ads_payload(request),
        "homepage_video": _mobile_home_video_payload(request),
        "mega_categories": [category for category in category_payloads if category],
        "products": products,
        "recommended_products": products[:12],
        "new_arrivals": products[:12],
        "trending_products": products[:12],
        "verified_vendors": verified_vendors,
        "factory_direct_manufacturers": factory_direct_manufacturers,
        "verified_manufacturers": factory_direct_manufacturers,
        "top_vendors": top_vendors,
        "top_retailers": top_retailers,
        "distributors_wholesalers": distributors_wholesalers,
        "service_providers": service_providers,
        "homepage_vendor_sections": [
            {
                "key": section.section_type,
                "title": section.title,
                "description": section.description,
                "empty_state_text": section.empty_state_text,
                "view_all_url": section.view_all_url,
                "show_view_all": section.show_view_all,
                "show_when_empty": section.show_when_empty,
                "max_items": section.max_items,
                "sort_order": section.sort_order,
                "vendors": section_payloads.get(section.section_type, []),
            }
            for section in HomepageVendorSection.objects.filter(is_active=True).order_by("sort_order", "title")
            if section_payloads.get(section.section_type, []) or section.show_when_empty
        ] if HomepageVendorSection and VendorProfile else [],
        "factory_direct_deals": factory_direct,
        "bulk_order_deals": wholesale_deals,
        "wholesale_deals": wholesale_deals,
        "moq_products": moq_products,
        "request_quote_products": moq_products or factory_direct,
        "price_drop_products": price_drop_products,
    })


@require_GET
def mobile_product_config_api(request):
    sections = ProductDetailSection.objects.filter(is_enabled=True, mobile_enabled=True).order_by("display_order", "title")
    fields = ProductDetailFieldConfig.objects.filter(is_enabled=True).order_by("display_order", "label")
    variant_types = ProductVariantTypeConfig.objects.filter(is_active=True).order_by("display_order", "label")
    if not variant_types.exists():
        variant_type_payload = [{"key": value, "label": label} for value, label in ProductVariant.VARIANT_TYPES]
    else:
        variant_type_payload = [{"key": item.key, "label": item.label} for item in variant_types]
    return JsonResponse({
        "success": True,
        "sections": [
            {
                "key": section.key,
                "title": section.title,
                "display_order": section.display_order,
                "web_enabled": section.web_enabled,
                "mobile_enabled": section.mobile_enabled,
            }
            for section in sections
        ],
        "fields": [
            {
                "key": field.key,
                "label": field.label,
                "is_required": field.is_required,
                "display_order": field.display_order,
                "help_text": field.help_text,
            }
            for field in fields
        ],
        "variant_types": variant_type_payload,
    })


@require_GET
def mobile_category_detail_api(request, slug):
    category = get_object_or_404(Category, slug=slug, is_active=True)
    sort = request.GET.get("sort", "").strip().lower()
    page = request.GET.get("page", "1").strip()
    page_size = request.GET.get("page_size", "24").strip()

    try:
        page_number = max(int(page), 1)
    except (TypeError, ValueError):
        page_number = 1

    try:
        per_page = min(max(int(page_size), 1), 60)
    except (TypeError, ValueError):
        per_page = 24

    category_ids = _category_descendant_ids(category)
    products = Product.objects.filter(
        category_id__in=category_ids,
        is_active=True,
        approval_status="approved",
    ).select_related("category", "brand", "vendor", "vendor__vendor_profile").prefetch_related("reviews")

    if sort == "price_low":
        products = order_storefront_products(products, "price")
    elif sort == "price_high":
        products = order_storefront_products(products, "-price")
    elif sort == "newest":
        products = order_storefront_products(products, "-created_at")
    elif sort in {"top_rated", "rated"}:
        products = order_storefront_products(products, "-rating_avg", "-rating_count")
    else:
        products = order_storefront_products(products, "-is_featured", "-created_at")

    paginator = Paginator(products, per_page)
    page_obj = paginator.get_page(page_number)
    category_payload = _mobile_category_payload(request, category, include_children=True)

    return JsonResponse({
        "success": True,
        "category": category_payload,
        "breadcrumbs": [
            {"name": ancestor.name, "slug": ancestor.slug}
            for ancestor in category.get_ancestors()
        ] + [{"name": category.name, "slug": category.slug}],
        "subcategories": category_payload.get("children", []),
        "products": [_mobile_product_payload(request, product) for product in page_obj.object_list],
        "product_count": paginator.count,
        "count": paginator.count,
        "page": page_obj.number,
        "page_size": per_page,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
        "sort_options": [
            {"value": "featured", "label": "Featured"},
            {"value": "newest", "label": "Newest"},
            {"value": "price_low", "label": "Low price"},
            {"value": "price_high", "label": "High price"},
        ],
    })


@require_GET
def mobile_products_api(request):
    products = Product.objects.filter(
        is_active=True,
        approval_status="approved",
    ).select_related("category", "brand", "vendor", "vendor__vendor_profile").prefetch_related("reviews")

    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    brand = request.GET.get("brand", "").strip()
    condition = request.GET.get("condition", "").strip()
    vendor_type = request.GET.get("vendor_type", "").strip()
    country = request.GET.get("country", "").strip()
    verified_manufacturer = request.GET.get("verified_manufacturer", "").strip().lower()
    wholesale = request.GET.get("wholesale", "").strip().lower()
    moq = request.GET.get("moq", "").strip().lower()
    min_price = request.GET.get("min_price", "").strip()
    max_price = request.GET.get("max_price", "").strip()
    in_stock = request.GET.get("in_stock", "").strip().lower()
    sort = request.GET.get("sort", "").strip().lower()

    if query:
        products = apply_product_search(products, query)
    if category:
        category_obj = Category.objects.filter(
            Q(name__iexact=category) | Q(slug=category),
            is_active=True,
        ).first()
        if category_obj:
            products = products.filter(category_id__in=_category_descendant_ids(category_obj))
        else:
            products = products.filter(Q(category__name__iexact=category) | Q(category__slug=category))
    if brand:
        products = products.filter(Q(brand__name__iexact=brand) | Q(brand__slug=brand))
    if condition:
        products = products.filter(condition=condition)
    if vendor_type:
        products = products.filter(vendor__vendor_profile__vendor_type=vendor_type)
    if country:
        products = products.filter(Q(country_of_origin__icontains=country) | Q(vendor__vendor_profile__country__icontains=country))
    if verified_manufacturer in {"1", "true", "yes"}:
        products = products.filter(vendor__vendor_profile__manufacturer_verified=True)
    if wholesale in {"1", "true", "yes"}:
        products = products.filter(Q(wholesale_price__isnull=False) | Q(bulk_price__isnull=False))
    if moq in {"1", "true", "yes"}:
        products = products.filter(minimum_order_quantity__gt=1)
    if min_price:
        try:
            products = products.filter(price__gte=Decimal(min_price))
        except InvalidOperation:
            pass
    if max_price:
        try:
            products = products.filter(price__lte=Decimal(max_price))
        except InvalidOperation:
            pass
    if in_stock in {"1", "true", "yes"}:
        products = products.filter(stock_quantity__gt=0)

    if sort == "price_low":
        products = order_storefront_products(products, "price")
    elif sort == "price_high":
        products = order_storefront_products(products, "-price")
    elif sort == "newest":
        products = order_storefront_products(products, "-created_at")
    elif sort == "popular":
        products = order_storefront_products(products, "-sales_count")
    elif sort == "verified":
        products = order_storefront_products(
            products,
            "-vendor__vendor_profile__manufacturer_verified",
            "-vendor__vendor_profile__is_verified",
            "-rating_avg",
            priority_position=2,
        )
    elif sort == "wholesale":
        products = order_storefront_products(
            products,
            F("wholesale_price").desc(nulls_last=True),
        )
    elif sort == "top_rated":
        products = order_storefront_products(products, "-rating_avg", "-rating_count")
    else:
        products = order_storefront_products(products, "-is_featured", "-created_at")

    data = [_mobile_product_payload(request, product) for product in products[:120]]

    return JsonResponse(
        {
            "count": len(data),
            "products": data,
        },
        safe=False,
    )

@csrf_exempt
@require_http_methods(["POST"])
@transaction.atomic
def mobile_product_review_api(request, slug):
    if _auth_mobile_customer_from_request_data is None:
        return JsonResponse({"success": False, "message": "Mobile customer app is not available."}, status=500)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"success": False, "message": "Invalid JSON payload."}, status=400)

    try:
        customer = _auth_mobile_customer_from_request_data(payload)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except ValueError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    product = get_object_or_404(Product, slug=slug, is_active=True, approval_status="approved")
    user = getattr(customer, "user", None)
    if not user:
        return JsonResponse({"success": False, "message": "Customer account is not linked to a user yet."}, status=400)

    rating = int(payload.get("rating") or 5)
    rating = max(1, min(5, rating))
    title = str(payload.get("title") or "").strip()
    review_text = str(payload.get("review") or payload.get("message") or "").strip()

    if len(title) < 3:
        return JsonResponse({"success": False, "message": "Please add a short review title."}, status=400)
    if len(review_text) < 10:
        return JsonResponse({"success": False, "message": "Please write a little more about the product."}, status=400)

    review, _created = ProductReview.objects.update_or_create(
        product=product,
        user=user,
        defaults={
            "rating": rating,
            "title": title,
            "review": review_text,
            "verified_purchase": False,
        },
    )

    avg_rating = product.reviews.aggregate(Avg("rating"))["rating__avg"] or 0
    product.rating_avg = Decimal(str(avg_rating))
    product.rating_count = product.reviews.count()
    product.save(update_fields=["rating_avg", "rating_count"])

    return JsonResponse({
        "success": True,
        "message": "Review saved successfully.",
        "review": {
            "id": review.id,
            "rating": review.rating,
            "title": review.title,
            "review": review.review,
            "customer_name": customer.full_name or getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "Arolana customer"),
            "verified_purchase": review.verified_purchase,
        },
    })


@csrf_exempt
@require_http_methods(["POST"])
def mobile_product_question_api(request, slug):
    if _auth_mobile_customer_from_request_data is None:
        return JsonResponse({"success": False, "message": "Mobile customer app is not available."}, status=500)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"success": False, "message": "Invalid JSON payload."}, status=400)

    try:
        customer = _auth_mobile_customer_from_request_data(payload)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except ValueError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    product = get_object_or_404(Product, slug=slug, is_active=True, approval_status="approved")
    user = getattr(customer, "user", None)
    if not user:
        return JsonResponse({"success": False, "message": "Customer account is not linked to a user yet."}, status=400)

    question_text = str(payload.get("question") or "").strip()
    if len(question_text) < 10:
        return JsonResponse({"success": False, "message": "Question must be at least 10 characters."}, status=400)
    if len(question_text) > 500:
        return JsonResponse({"success": False, "message": "Question must be less than 500 characters."}, status=400)

    qna = ProductQuestion.objects.create(
        product=product,
        user=user,
        question=question_text,
        is_public=True,
    )

    return JsonResponse({
        "success": True,
        "message": "Question submitted successfully.",
        "question": {
            "id": qna.id,
            "question": qna.question,
            "answer": "",
            "answered": False,
            "helpful_count": 0,
        },
    })

@require_GET
def mobile_product_detail_api(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category", "brand", "vendor").prefetch_related(
            "images",
            "variants",
            "variants__images",
            "reviews__user",
            "questions__user",
            "additional_videos",
            "wholesale_tiers",
            "product_accessories__accessory",
        ),
        slug=slug,
        is_active=True,
        approval_status="approved",
    )

    def safe_url(file_field):
        if not file_field:
            return None
        try:
            url = file_field.url
        except Exception:
            return None

        if url.startswith("http://") or url.startswith("https://"):
            return url

        return request.build_absolute_uri(url)

    images = []

    main_image = safe_url(getattr(product, "main_image", None))
    if main_image:
        images.append(main_image)

    for image in product.images.all():
        image_url = safe_url(getattr(image, "image", None))
        if image_url and image_url not in images:
            images.append(image_url)

    variants = []
    for variant in product.variants.filter(is_active=True):
        variant_images = []
        variant_image = safe_url(getattr(variant, "image", None))
        if variant_image:
            variant_images.append(variant_image)
        for gallery_image in variant.images.all():
            gallery_url = safe_url(getattr(gallery_image, "image", None))
            if gallery_url and gallery_url not in variant_images:
                variant_images.append(gallery_url)
        variants.append({
            "id": variant.id,
            "name": getattr(variant, "name", ""),
            "value": getattr(variant, "value", ""),
            "variant_type": getattr(variant, "variant_type", ""),
            "sku": getattr(variant, "sku", ""),
            "final_price": str(getattr(variant, "final_price", product.price)),
            "price_adjustment": str(getattr(variant, "price_adjustment", "0")),
            "stock_quantity": getattr(variant, "stock_quantity", 0),
            "color_code": getattr(variant, "color_code", ""),
            "image": variant_image,
            "images": variant_images,
        })

    category = getattr(product, "category", None)
    brand = getattr(product, "brand", None)
    vendor = getattr(product, "vendor", None)
    vendor_profile = getattr(vendor, "vendor_profile", None) if vendor else None
    vendor_chat_available = bool(vendor and user_has_paid_subscription(vendor))

    def product_card(item):
        return _mobile_product_payload(request, item)

    mobile_customer = None
    if _auth_mobile_customer_from_request_data is not None:
        try:
            mobile_customer = _auth_mobile_customer_from_request_data(request.GET)
        except Exception:
            mobile_customer = None

    related_queryset = Product.objects.filter(
        is_active=True,
        approval_status="approved",
    ).exclude(id=product.id).select_related(
        "category",
        "brand",
        "vendor",
        "vendor__vendor_profile",
    )
    related_queryset = order_storefront_products(
        related_queryset,
        "-is_featured",
        "-rating_avg",
        "-created_at",
    )

    bought_together_ids = []
    try:
        from orders.models import OrderItem

        order_ids = OrderItem.objects.filter(product=product).values_list("order_id", flat=True)
        bought_together_ids = list(
            OrderItem.objects.filter(order_id__in=order_ids, product_id__isnull=False)
            .exclude(product_id=product.id)
            .exclude(order__status__in=["cancelled", "refunded"])
            .values("product_id")
            .annotate(times=Count("id"))
            .order_by("-times")
            .values_list("product_id", flat=True)[:8]
        )
    except Exception:
        bought_together_ids = []

    frequently_bought = list(related_queryset.filter(id__in=bought_together_ids))
    if bought_together_ids:
        frequently_bought.sort(key=lambda item: bought_together_ids.index(item.id))
    if len(frequently_bought) < 8:
        extra_frequently_bought = related_queryset.filter(brand=brand).exclude(id__in=[item.id for item in frequently_bought]) if brand else related_queryset.exclude(id__in=[item.id for item in frequently_bought])
        frequently_bought.extend(list(extra_frequently_bought[: 8 - len(frequently_bought)]))

    recommended_ids = []
    if mobile_customer:
        try:
            from arolana_ops.views import _build_recommendation_scores

            recommended_ids = [
                product_id
                for product_id, _meta in sorted(
                    _build_recommendation_scores(mobile_customer).items(),
                    key=lambda item: item[1]["score"],
                    reverse=True,
                )
                if product_id != product.id
            ][:12]
        except Exception:
            recommended_ids = []

    recommended = list(related_queryset.filter(id__in=recommended_ids[:8]))
    if recommended_ids:
        recommended.sort(key=lambda item: recommended_ids.index(item.id))
    if len(recommended) < 8:
        extra_recommended = related_queryset.filter(category=category).exclude(id__in=[item.id for item in recommended]) if category else related_queryset.exclude(id__in=[item.id for item in recommended])
        recommended.extend(list(extra_recommended[: 8 - len(recommended)]))

    supplier_products = list(related_queryset.filter(vendor=vendor)[:8]) if vendor else []
    recently_viewed = []
    if mobile_customer:
        try:
            interactions = (
                mobile_customer.product_interactions.select_related("product", "product__category", "product__brand")
                .filter(product__is_active=True, product__approval_status="approved")
                .exclude(product=product)
                .order_by("-last_viewed_at")[:8]
            )
            recently_viewed = [interaction.product for interaction in interactions]
        except Exception:
            recently_viewed = []
    if len(recently_viewed) < 8:
        recently_viewed.extend(list(related_queryset.exclude(id__in=[item.id for item in recently_viewed])[: 8 - len(recently_viewed)]))

    reviews = []
    for review in product.reviews.all()[:8]:
        user = getattr(review, "user", None)
        reviews.append({
            "id": review.id,
            "rating": getattr(review, "rating", 0),
            "title": getattr(review, "title", ""),
            "review": getattr(review, "review", ""),
            "customer_name": getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "Arolana customer"),
            "verified_purchase": getattr(review, "verified_purchase", False),
            "helpful_count": getattr(review, "helpful_count", 0),
            "created_at": getattr(review, "created_at", None).isoformat() if getattr(review, "created_at", None) else "",
        })

    questions = []
    for question in product.questions.filter(is_public=True)[:8]:
        questions.append({
            "id": question.id,
            "question": getattr(question, "question", ""),
            "answer": getattr(question, "answer", "") or "",
            "answered": bool(getattr(question, "answer", "")),
            "helpful_count": getattr(question, "helpful_count", 0),
        })

    videos = []
    if getattr(product, "video_url", "") or getattr(product, "local_video", None):
        videos.append({
            "title": product.video_title or "Product video",
            "source": getattr(product, "video_type", "youtube"),
            "url": product.video_url or safe_url(getattr(product, "local_video", None)),
            "thumbnail": safe_url(getattr(product, "video_thumbnail", None)),
        })
    for video in product.additional_videos.all():
        videos.append({
            "title": video.title or "Product video",
            "description": getattr(video, "description", ""),
            "source": getattr(video, "source", ""),
            "url": getattr(video, "youtube_url", "") or getattr(video, "vimeo_url", "") or safe_url(getattr(video, "local_video", None)),
            "thumbnail": safe_url(getattr(video, "thumbnail", None)),
        })

    shipping_info = getattr(product, "shipping_info", None)
    delivery_info = {
        "title": "Delivery calculated at checkout",
        "message": "Use your accurate location at checkout so Arolana can calculate delivery from the vendor pickup address to you.",
        "estimate": shipping_info.delivery_estimate() if shipping_info else "Calculated by location",
        "free_shipping": getattr(shipping_info, "free_shipping", False) if shipping_info else False,
        "weight": str(getattr(shipping_info, "weight_shipping", "") or getattr(product, "weight", "") or ""),
        "dimensions": getattr(shipping_info, "dimensions_package", "") if shipping_info else "",
        "restrictions": getattr(shipping_info, "shipping_restrictions", "") if shipping_info else "",
        "hazmat": bool(getattr(shipping_info, "hazmat", False)) if shipping_info else False,
    }
    package_details = {
        "weight": str(getattr(product, "weight", "") or ""),
        "weight_unit": getattr(product, "weight_unit", "") or "",
        "package_weight": str(getattr(shipping_info, "weight_shipping", "") or ""),
        "dimensions_length": str(getattr(product, "dimensions_length", "") or ""),
        "dimensions_width": str(getattr(product, "dimensions_width", "") or ""),
        "dimensions_height": str(getattr(product, "dimensions_height", "") or ""),
        "dimension_unit": getattr(product, "dimension_unit", "") or "",
        "package_dimensions": getattr(shipping_info, "dimensions_package", "") if shipping_info else getattr(product, "dimensions", "") or "",
        "free_shipping": getattr(shipping_info, "free_shipping", False) if shipping_info else False,
        "estimated_delivery": shipping_info.delivery_estimate() if shipping_info else "",
        "estimated_delivery_days_min": getattr(shipping_info, "estimated_delivery_days_min", None) if shipping_info else None,
        "estimated_delivery_days_max": getattr(shipping_info, "estimated_delivery_days_max", None) if shipping_info else None,
        "shipping_restrictions": getattr(shipping_info, "shipping_restrictions", "") if shipping_info else "",
        "hazmat": bool(getattr(shipping_info, "hazmat", False)) if shipping_info else False,
    }

    wholesale_tiers = [
        {
            "id": tier.id,
            "min_quantity": tier.min_quantity,
            "max_quantity": tier.max_quantity,
            "price_per_unit": str(tier.price_per_unit),
        }
        for tier in product.wholesale_tiers.filter(is_active=True)
    ]

    accessories = []
    for accessory_link in product.product_accessories.select_related("accessory").filter(accessory__is_active=True)[:12]:
        accessory = accessory_link.accessory
        accessories.append({
            "id": accessory.id,
            "name": accessory.name,
            "slug": accessory.slug,
            "description": getattr(accessory, "description", ""),
            "price": str(accessory.price),
            "compare_price": str(accessory.compare_price or ""),
            "image": safe_url(getattr(accessory, "image", None)),
            "required": accessory_link.required,
            "discount_when_bought_together": str(accessory_link.discount_when_bought_together),
        })

    vendor_url = ""
    if vendor_profile:
        try:
            vendor_url = request.build_absolute_uri(vendor_profile.get_absolute_url())
        except Exception:
            vendor_url = ""

    chat_url = ""
    if vendor:
        try:
            chat_url = request.build_absolute_uri(reverse("chat:start_vendor_product", args=[vendor.id, product.id]))
        except Exception:
            chat_url = ""

    return JsonResponse({
        "id": product.id,
        "name": product.name,
        "slug": product.slug,
        "sku": product.sku,
        "arolana_sku": product.sku,
        "manufacturer_sku": getattr(product, "manufacturer_sku", ""),
        "condition": product.get_condition_display() if hasattr(product, "get_condition_display") else getattr(product, "condition", ""),
        "price": str(product.price),
        "compare_price": str(getattr(product, "compare_price", "") or ""),
        "wholesale_price": str(getattr(product, "wholesale_price", "") or ""),
        "bulk_price": str(getattr(product, "bulk_price", "") or ""),
        "minimum_order_quantity": getattr(product, "minimum_order_quantity", 1) or 1,
        "moq": getattr(product, "minimum_order_quantity", 1) or 1,
        "moq_unit": getattr(product, "moq_unit", "") or "unit",
        "lead_time_days": getattr(product, "lead_time_days", None),
        "country_of_origin": getattr(product, "country_of_origin", "") or "",
        "manufacturer_address": getattr(product, "manufacturer_address", "") or "",
        "certifications": getattr(product, "certifications", []) or [],
        "sample_available": bool(getattr(product, "sample_available", False)),
        "sample_price": str(getattr(product, "sample_price", "") or ""),
        "shipping_weight": getattr(product, "formatted_weight", "") or str(getattr(product, "weight", "") or ""),
        "package_dimensions": getattr(product, "dimensions", "") or "",
        "package_details": package_details,
        "wholesale_tiers": wholesale_tiers,
        "accessories": accessories,
        "rfq_available": bool(vendor_profile),
        "badges": _mobile_product_payload(request, product).get("badges", []),
        "description": getattr(product, "description", "") or "",
        "short_description": getattr(product, "short_description", "") or "",
        "specifications": getattr(product, "specifications", "") or "",
        "specifications_text": strip_tags(getattr(product, "specifications", "") or ""),
        "category_name": category.name if category else "Arolana",
        "brand_name": brand.name if brand else "",
        "stock_quantity": getattr(product, "stock_quantity", 0),
        "rating_avg": str(getattr(product, "rating_avg", "0") or "0"),
        "rating_count": getattr(product, "rating_count", 0),
        "manual_pdf": safe_url(getattr(product, "manual_pdf", None)),
        "delivery_info": delivery_info,
        "vendor": {
            **(_mobile_vendor_payload(request, vendor_profile) or {
                "id": vendor.id if vendor else None,
                "name": getattr(vendor, "get_full_name", lambda: "")() or getattr(vendor, "email", "Arolana vendor"),
            }),
            "chat_available": vendor_chat_available,
            "chat_url": chat_url,
            "url": vendor_url,
        },
        "image": main_image,
        "images": images,
        "variants": variants,
        "videos": videos,
        "reviews": reviews,
        "questions": questions,
        "recommended_products": [product_card(item) for item in recommended],
        "frequently_bought": [product_card(item) for item in frequently_bought],
        "supplier_products": [product_card(item) for item in supplier_products],
        "recently_viewed": [product_card(item) for item in recently_viewed],
        "detail_sections": [
            {
                "key": section.key,
                "title": section.title,
                "display_order": section.display_order,
            }
            for section in ProductDetailSection.objects.filter(is_enabled=True, mobile_enabled=True).order_by("display_order", "title")
        ],
        "detail_fields": [
            {
                "key": field.key,
                "label": field.label,
                "is_required": field.is_required,
                "display_order": field.display_order,
                "help_text": field.help_text,
            }
            for field in ProductDetailFieldConfig.objects.filter(is_enabled=True).order_by("display_order", "label")
        ],
    })


def _mobile_customer_from_payload(payload):
    if _auth_mobile_customer_from_request_data is None:
        raise ValueError("Mobile customer app is not available.")
    return _auth_mobile_customer_from_request_data(payload)


def _rfq_payload(request, rfq):
    product = getattr(rfq, "product", None)
    vendor = getattr(rfq, "vendor", None)
    return {
        "id": rfq.id,
        "status": rfq.status,
        "status_label": rfq.get_status_display() if hasattr(rfq, "get_status_display") else rfq.status,
        "quantity": rfq.quantity,
        "budget": str(rfq.budget or ""),
        "country": rfq.country,
        "delivery_location": rfq.delivery_location,
        "message": rfq.message,
        "quote_price": str(rfq.quote_price or ""),
        "quote_lead_time_days": rfq.quote_lead_time_days,
        "vendor_note": rfq.vendor_note,
        "created_at": rfq.created_at.isoformat() if getattr(rfq, "created_at", None) else "",
        "expires_at": rfq.expires_at.isoformat() if getattr(rfq, "expires_at", None) else "",
        "product": _mobile_product_payload(request, product) if product else None,
        "vendor": _mobile_vendor_payload(request, vendor) if vendor else None,
    }


@require_GET
def mobile_vendors_api(request):
    if VendorProfile is None:
        return JsonResponse({"success": False, "message": "Vendor system is not available."}, status=500)

    query = request.GET.get("q", "").strip()
    vendor_type = request.GET.get("vendor_type", "").strip()
    verified = request.GET.get("verified", "").strip().lower()

    vendors = VendorProfile.objects.filter(approval_status="approved").select_related("user")
    if query:
        vendors = vendors.filter(
            Q(store_name__icontains=query)
            | Q(company_name__icontains=query)
            | Q(description__icontains=query)
            | Q(country__icontains=query)
            | Q(main_product_categories__icontains=query)
        )
    if vendor_type:
        vendors = vendors.filter(vendor_type=vendor_type)
    if verified in {"1", "true", "yes"}:
        vendors = vendors.filter(Q(is_verified=True) | Q(manufacturer_verified=True))

    vendors = vendors.order_by("-manufacturer_verified", "-is_verified", "-priority_score", "-rating_avg")[:80]
    return JsonResponse({
        "success": True,
        "vendors": [_mobile_vendor_payload(request, vendor) for vendor in vendors],
    })


@require_GET
def mobile_vendor_detail_api(request, vendor_id):
    if VendorProfile is None:
        return JsonResponse({"success": False, "message": "Vendor system is not available."}, status=500)

    vendor = get_object_or_404(VendorProfile.objects.select_related("user"), id=vendor_id, approval_status="approved")
    return JsonResponse({
        "success": True,
        "vendor": _mobile_vendor_payload(request, vendor, include_products=True),
    })


@require_GET
def mobile_vendor_products_api(request, vendor_id):
    if VendorProfile is None:
        return JsonResponse({"success": False, "message": "Vendor system is not available."}, status=500)

    vendor = get_object_or_404(VendorProfile.objects.select_related("user"), id=vendor_id, approval_status="approved")
    products = Product.objects.filter(
        vendor=vendor.user,
        is_active=True,
        approval_status="approved",
    ).select_related("category", "brand", "vendor", "vendor__vendor_profile").order_by("-is_featured", "-created_at")[:120]
    return JsonResponse({
        "success": True,
        "vendor": _mobile_vendor_payload(request, vendor),
        "products": [_mobile_product_payload(request, product) for product in products],
    })


@csrf_exempt
@require_http_methods(["POST"])
def mobile_vendor_follow_api(request, vendor_id):
    if VendorProfile is None or VendorFollow is None:
        return JsonResponse({"success": False, "message": "Vendor follow system is not available."}, status=500)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        customer = _mobile_customer_from_payload(payload)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    user = getattr(customer, "user", None)
    if not user:
        return JsonResponse({"success": False, "message": "Customer account is not linked to a user yet."}, status=400)

    vendor = get_object_or_404(VendorProfile, id=vendor_id, approval_status="approved")
    VendorFollow.objects.get_or_create(user=user, vendor=vendor)
    vendor.followers_count = vendor.followers.count()
    vendor.save(update_fields=["followers_count"])
    return JsonResponse({"success": True, "message": f"You are now following {vendor.store_name}.", "followers_count": vendor.followers_count})


@csrf_exempt
@require_http_methods(["POST"])
def mobile_vendor_unfollow_api(request, vendor_id):
    if VendorProfile is None or VendorFollow is None:
        return JsonResponse({"success": False, "message": "Vendor follow system is not available."}, status=500)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        customer = _mobile_customer_from_payload(payload)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    user = getattr(customer, "user", None)
    if not user:
        return JsonResponse({"success": False, "message": "Customer account is not linked to a user yet."}, status=400)

    vendor = get_object_or_404(VendorProfile, id=vendor_id, approval_status="approved")
    VendorFollow.objects.filter(user=user, vendor=vendor).delete()
    vendor.followers_count = vendor.followers.count()
    vendor.save(update_fields=["followers_count"])
    return JsonResponse({"success": True, "message": f"{vendor.store_name} removed from followed suppliers.", "followers_count": vendor.followers_count})


@require_GET
def mobile_rfqs_api(request):
    if VendorRFQ is None:
        return JsonResponse({"success": False, "message": "RFQ system is not available."}, status=500)

    try:
        customer = _mobile_customer_from_payload(request.GET)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    user = getattr(customer, "user", None)
    rfqs = VendorRFQ.objects.filter(customer=user).select_related("vendor", "vendor__user", "product", "product__category", "product__brand", "product__vendor")[:80]
    return JsonResponse({"success": True, "rfqs": [_rfq_payload(request, rfq) for rfq in rfqs]})


@csrf_exempt
@require_http_methods(["POST"])
@transaction.atomic
def mobile_rfq_create_api(request):
    if VendorRFQ is None or VendorProfile is None:
        return JsonResponse({"success": False, "message": "RFQ system is not available."}, status=500)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        customer = _mobile_customer_from_payload(payload)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    user = getattr(customer, "user", None)
    if not user:
        return JsonResponse({"success": False, "message": "Customer account is not linked to a user yet."}, status=400)

    product_id = payload.get("product_id")
    vendor_id = payload.get("vendor_id")
    product = Product.objects.filter(id=product_id, is_active=True, approval_status="approved").select_related("vendor__vendor_profile").first() if product_id else None
    vendor = None
    if vendor_id:
        vendor = VendorProfile.objects.filter(id=vendor_id, approval_status="approved").first()
    if not vendor and product:
        vendor = getattr(getattr(product, "vendor", None), "vendor_profile", None)
    if not vendor:
        return JsonResponse({"success": False, "message": "Choose a supplier before requesting quotation."}, status=400)

    try:
        quantity = max(1, int(payload.get("quantity") or 1))
    except (TypeError, ValueError):
        quantity = 1
    minimum_order_quantity = getattr(product, "minimum_order_quantity", 1) if product else 1
    if product and quantity < minimum_order_quantity:
        return JsonResponse({
            "success": False,
            "message": f"Minimum order quantity for this product is {minimum_order_quantity} {getattr(product, 'moq_unit', 'unit')}.",
        }, status=400)

    budget_value = payload.get("budget") or None
    try:
        budget = Decimal(str(budget_value)) if budget_value not in {"", None} else None
    except (InvalidOperation, TypeError, ValueError):
        budget = None

    rfq = VendorRFQ.objects.create(
        vendor=vendor,
        customer=user,
        product=product,
        quantity=quantity,
        budget=budget,
        country=str(payload.get("country") or "").strip(),
        delivery_location=str(payload.get("delivery_location") or "").strip(),
        message=str(payload.get("message") or "").strip(),
    )

    if Notification:
        Notification.objects.create(
            user=vendor.user,
            notification_type="vendor",
            title="New RFQ received",
            message=f"{customer.full_name or user.get_full_name() or user.username} requested a quote from {vendor.store_name}.",
            metadata={"rfq_id": rfq.id, "product_id": product.id if product else None},
        )

    return JsonResponse({"success": True, "message": "Quotation request sent to the supplier.", "rfq": _rfq_payload(request, rfq)})


@require_GET
def mobile_rfq_detail_api(request, rfq_id):
    if VendorRFQ is None:
        return JsonResponse({"success": False, "message": "RFQ system is not available."}, status=500)

    try:
        customer = _mobile_customer_from_payload(request.GET)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    rfq = get_object_or_404(VendorRFQ.objects.select_related("vendor", "vendor__user", "product", "product__category", "product__brand", "product__vendor"), id=rfq_id, customer=getattr(customer, "user", None))
    return JsonResponse({"success": True, "rfq": _rfq_payload(request, rfq)})


@csrf_exempt
@require_http_methods(["POST"])
def mobile_rfq_status_api(request, rfq_id, action):
    if VendorRFQ is None:
        return JsonResponse({"success": False, "message": "RFQ system is not available."}, status=500)

    if action not in {"accept", "reject"}:
        return JsonResponse({"success": False, "message": "Invalid RFQ action."}, status=400)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        customer = _mobile_customer_from_payload(payload)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    rfq = get_object_or_404(VendorRFQ, id=rfq_id, customer=getattr(customer, "user", None))
    rfq.status = "accepted" if action == "accept" else "rejected"
    rfq.save(update_fields=["status", "updated_at"])

    if Notification:
        Notification.objects.create(
            user=rfq.vendor.user,
            notification_type="vendor",
            title=f"RFQ {rfq.status}",
            message=f"Customer {rfq.status} your quotation request response.",
            metadata={"rfq_id": rfq.id},
        )

    return JsonResponse({"success": True, "message": f"RFQ {rfq.status}.", "rfq": _rfq_payload(request, rfq)})
