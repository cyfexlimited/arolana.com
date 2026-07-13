from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Avg, Count, Sum, Prefetch, F
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from django.views.decorators.http import require_http_methods, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.db import IntegrityError, transaction
from django.contrib.admin.views.decorators import staff_member_required

import json
import re

from urllib.parse import quote, urlparse
from django.http import HttpResponse
from decimal import Decimal, InvalidOperation
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from core.content_i18n import (
    prime_translations,
    translated_field,
    translated_key,
    translation_key_for_condition,
)
from core.local_cache import local_get_or_set
from core.models import HomePageAppearance
from core.media_optimization import get_optimized_image_url, optimized_name_for
from .models import (
    Product, Category, ProductReview, Wishlist, RecentlyViewed,
    ProductVariant, ProductQuestion, Accessory, AccessoryProduct,
    ProductImage, ProductVideo, ProductVariantImage, Brand, ProductListingBanner,
    ProductArticleLink, CategoryArticleLink, ProductWholesaleTier, ProductDetailSection,
    ProductDetailFieldConfig, ProductVariantTypeConfig, ManufacturerWarranty,
    VendorProductOffer, ReviewVideo,
)
from accounts.models import User
from currency.templatetags.currency_filters import currency as format_currency
from arolana_payments.services import get_gateway_options
from products.ranking import order_storefront_products
from .review_stats import (
    calculate_product_review_stats,
    refresh_product_review_stats,
)

try:
    from subscriptions.models import get_tier_limits, user_has_paid_subscription
except ImportError:
    def get_tier_limits(tier):
        return {}

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
    from blog.models import BlogCategory, BlogComment, BlogPost, BlogTag
except ImportError:
    BlogCategory = None
    BlogComment = None
    BlogPost = None
    BlogTag = None

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
    from vendors.models import VendorCallbackRequest, VendorLead, VendorProfile, VendorFollow, VendorRFQ
except ImportError:
    VendorCallbackRequest = None
    VendorLead = None
    VendorProfile = None
    VendorFollow = None
    VendorRFQ = None

try:
    from chat.models import VendorChatRoom, VendorChatMessage
except ImportError:
    VendorChatRoom = None
    VendorChatMessage = None

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
GUEST_RECENTLY_VIEWED_SESSION_KEY = 'guest_recently_viewed_products'


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
    def __init__(self, item_id, product=None, variant=None, accessory=None, vendor_offer=None, quantity=1, price_at_add=Decimal('0.00')):
        self.id = item_id
        self.product = product
        self.variant = variant
        self.accessory = accessory
        self.vendor_offer = vendor_offer
        self.quantity = quantity
        self.price_at_add = price_at_add

    @property
    def subtotal(self):
        return self.price_at_add * self.quantity

    @property
    def item_name(self):
        if self.vendor_offer:
            return self.vendor_offer.display_name
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


def _prefetch_cart_items(cart):
    """
    Keep cart page/update reads lean for product, variant, and accessory images.
    GuestCart already carries hydrated item objects, so only database carts need this.
    """
    if not cart or isinstance(cart, GuestCart):
        return cart

    prefetched_items = (
        CartItem.objects
        .filter(cart=cart)
        .select_related(
            'product',
            'product__category',
            'product__brand',
            'variant',
            'variant__product',
            'accessory',
        )
        .order_by('created_at', 'id')
    )
    return (
        Cart.objects
        .filter(pk=cart.pk)
        .prefetch_related(Prefetch('items', queryset=prefetched_items))
        .first()
    ) or cart


def _cart_ajax_payload(request, cart, item=None, deleted=False):
    """Return all cart numbers the frontend needs to update without a refresh."""
    subtotal = getattr(cart, 'subtotal', Decimal('0.00')) or Decimal('0.00')
    total = getattr(cart, 'total', subtotal) or subtotal
    cart_count = getattr(cart, 'total_items', 0) or 0

    payload = {
        'success': True,
        'deleted': bool(deleted),
        'cart_count': cart_count,
        'subtotal': str(subtotal),
        'total': str(total),
        'subtotal_display': format_currency(subtotal, request),
        'total_display': format_currency(total, request),
    }

    if item is not None:
        item_subtotal = getattr(item, 'subtotal', Decimal('0.00')) or Decimal('0.00')
        payload.update({
            'item_id': str(getattr(item, 'id', '')),
            'quantity': getattr(item, 'quantity', 0),
            'item_subtotal': str(item_subtotal),
            'item_subtotal_display': format_currency(item_subtotal, request),
            'item_price_display': format_currency(getattr(item, 'price_at_add', Decimal('0.00')), request),
        })

    return payload


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


def _guest_recently_viewed_ids(request):
    values = request.session.get(GUEST_RECENTLY_VIEWED_SESSION_KEY, [])
    cleaned = []
    for value in values:
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if product_id not in cleaned:
            cleaned.append(product_id)
    return cleaned


def _save_guest_recently_viewed(request, product):
    if not product:
        return
    product_ids = _guest_recently_viewed_ids(request)
    product_ids = [product.id] + [item for item in product_ids if item != product.id]
    request.session[GUEST_RECENTLY_VIEWED_SESSION_KEY] = product_ids[:20]
    request.session.modified = True


def _cart_product_ids(cart):
    ids = set()
    try:
        items = cart.items.all()
    except Exception:
        return ids
    for item in items:
        product = getattr(item, 'product', None)
        if product:
            ids.add(product.id)
    return ids


def _recently_viewed_for_cart(request, cart, limit=12):
    exclude_ids = _cart_product_ids(cart)
    if request.user.is_authenticated:
        recent_ids = list(
            RecentlyViewed.objects.filter(user=request.user)
            .exclude(product_id__in=exclude_ids)
            .values_list('product_id', flat=True)[:limit]
        )
    else:
        recent_ids = [item for item in _guest_recently_viewed_ids(request) if item not in exclude_ids][:limit]
    if not recent_ids:
        return []
    products_by_id = Product.objects.filter(
        id__in=recent_ids,
        is_active=True,
        approval_status='approved',
    ).select_related('category', 'brand', 'vendor').in_bulk()
    return [products_by_id[item] for item in recent_ids if item in products_by_id]


def _guest_cart_key(product=None, variant=None, accessory=None, vendor_offer=None):
    if accessory:
        return f"accessory:{accessory.id}"
    if vendor_offer:
        return f"offer:{vendor_offer.id}"
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
    offer_ids = set()

    for line in cart_data.values():
        if line.get('accessory_id'):
            accessory_ids.add(line.get('accessory_id'))
        elif line.get('vendor_offer_id'):
            offer_ids.add(line.get('vendor_offer_id'))
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
    offers = {
        str(offer.id): offer
        for offer in VendorProductOffer.objects.select_related('product', 'variant', 'vendor').filter(
            id__in=offer_ids,
            is_active=True,
            approval_status=VendorProductOffer.STATUS_APPROVED,
            product__is_active=True,
            product__approval_status='approved',
        )
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

        if line.get('vendor_offer_id'):
            offer = offers.get(str(line.get('vendor_offer_id')))
            if not offer:
                continue
            if not price:
                price = offer.final_price
            items.append(GuestCartItem(key, product=offer.product, variant=offer.variant, vendor_offer=offer, quantity=quantity, price_at_add=price))
            valid_cart_data[key] = {
                **line,
                'product_id': offer.product_id,
                'variant_id': offer.variant_id or '',
                'vendor_offer_id': offer.id,
                'quantity': quantity,
                'price_at_add': str(price),
            }
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

        if item.vendor_offer:
            stock = item.vendor_offer.available_stock
            quantity = min(item.quantity, max(stock, 0))
            if quantity <= 0:
                continue
            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                vendor_offer=item.vendor_offer,
                defaults={
                    'product': item.vendor_offer.product,
                    'variant': item.vendor_offer.variant,
                    'quantity': quantity,
                    'price_at_add': item.vendor_offer.final_price,
                }
            )
            if not created:
                cart_item.quantity = min(cart_item.quantity + quantity, stock, 999)
                cart_item.price_at_add = item.vendor_offer.final_price
                cart_item.product = item.vendor_offer.product
                cart_item.variant = item.vendor_offer.variant
                cart_item.save(update_fields=['quantity', 'price_at_add', 'product', 'variant'])
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
    vendor_offer_id = request.POST.get('vendor_offer_id') or request.POST.get('offer_id') or request.GET.get('vendor_offer_id') or request.GET.get('offer_id')
    accessory_ids = request.POST.getlist('accessories') or request.GET.getlist('accessories')
    
    # ====== Handle Product ======
    price = product.price
    variant = None
    vendor_offer = None

    if vendor_offer_id:
        try:
            vendor_offer = VendorProductOffer.objects.select_related('product', 'variant', 'vendor').get(
                id=vendor_offer_id,
                product=product,
                is_active=True,
                approval_status=VendorProductOffer.STATUS_APPROVED,
            )
            variant = vendor_offer.variant
            price = vendor_offer.final_price
            available = vendor_offer.available_stock
            if available < quantity:
                message = f"Only {available} items available from this vendor!"
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': message}, status=400)
                messages.error(request, message)
                return redirect('products:detail', slug=product.slug)
        except VendorProductOffer.DoesNotExist:
            message = 'Selected vendor offer is no longer available.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': message}, status=400)
            messages.error(request, message)
            return redirect('products:detail', slug=product.slug)
    
    if variant_id and not vendor_offer:
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
    elif not vendor_offer:
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
        lookup = {'cart': cart}
        if vendor_offer:
            lookup['vendor_offer'] = vendor_offer
        else:
            lookup['product'] = product
            lookup['variant'] = variant

        cart_item, created = CartItem.objects.get_or_create(
            **lookup,
            defaults={
                'product': product,
                'variant': variant,
                'quantity': quantity,
                'price_at_add': price
            }
        )

        if not created:
            # Check if new total exceeds stock
            stock = vendor_offer.available_stock if vendor_offer else (variant.stock_quantity if variant else product.get_available_stock())
            if cart_item.quantity + quantity > stock:
                message = f"Cannot add more than {stock} items!"
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': message}, status=400)
                messages.error(request, message)
                return redirect('products:detail', slug=product.slug)

            cart_item.quantity += quantity
            cart_item.price_at_add = price
            cart_item.product = product
            cart_item.variant = variant
            cart_item.save(update_fields=['quantity', 'price_at_add', 'product', 'variant'])
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
        key = _guest_cart_key(product=product, variant=variant, vendor_offer=vendor_offer)
        current_quantity = int(cart_data.get(key, {}).get('quantity') or 0)
        stock = vendor_offer.available_stock if vendor_offer else (variant.stock_quantity if variant else product.get_available_stock())

        if current_quantity + quantity > stock:
            message = f"Cannot add more than {stock} items!"
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': message}, status=400)
            messages.error(request, message)
            return redirect('products:detail', slug=product.slug)

        cart_data[key] = {
            'product_id': product.id,
            'variant_id': variant.id if variant else '',
            'vendor_offer_id': vendor_offer.id if vendor_offer else '',
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

    vendor_profile = vendor_offer.vendor if vendor_offer else getattr(getattr(product, 'vendor', None), 'vendor_profile', None)
    if vendor_profile:
        _create_vendor_lead(
            request,
            vendor_profile,
            'add_to_cart',
            product=product,
            payload={
                'source': request.POST.get('source') or request.GET.get('source') or 'web',
                'quantity': quantity,
                'variant_id': variant.id if variant else '',
                'page_url': request.META.get('HTTP_REFERER', ''),
            },
            metadata={'cart_count': cart_count},
        )

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
        cart = _prefetch_cart_items(cart)
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
        'recently_viewed_products': _recently_viewed_for_cart(request, cart),
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
                cart = _build_guest_cart(request)
                payload = _cart_ajax_payload(request, cart, deleted=True)
                request.session['cart_count'] = payload['cart_count']
                return JsonResponse(payload)

            cart_data[item_id]['quantity'] = quantity
            cart_data = _save_guest_cart(request, cart_data)
            cart = _build_guest_cart(request)
            updated_item = next((item for item in cart.items.all() if str(item.id) == str(item_id)), None)
            payload = _cart_ajax_payload(request, cart, item=updated_item)
            request.session['cart_count'] = payload['cart_count']
            return JsonResponse(payload)

        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        
        if quantity <= 0:
            cart = cart_item.cart
            cart_item.delete()
            cart = _prefetch_cart_items(cart)
            payload = _cart_ajax_payload(request, cart, deleted=True)
            request.session['cart_count'] = payload['cart_count']
            return JsonResponse(payload)
        
        cart_item.quantity = quantity
        cart_item.save(update_fields=['quantity'])

        cart_item.refresh_from_db()
        cart = _prefetch_cart_items(cart_item.cart)
        payload = _cart_ajax_payload(request, cart, item=cart_item)
        request.session['cart_count'] = payload['cart_count']
        return JsonResponse(payload)
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
        cart = _prefetch_cart_items(cart) if request.user.is_authenticated else _build_guest_cart(request)
        return JsonResponse(_cart_ajax_payload(request, cart, deleted=True))
    
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
    Display the complete product page.

    Behaviour:
    - Page refresh loads the main product gallery.
    - No product variant is automatically selected.
    - Every active variant sends its complete gallery to the frontend.
    - Reviews support ProductReview.video_review and ReviewVideo.video_file.
    """

    product = get_object_or_404(
        Product.objects
        .select_related(
            "category",
            "brand",
            "vendor",
            "vendor__vendor_profile",
            "manufacturer_warranty",
            "shipping_info",
        )
        .prefetch_related(
            Prefetch(
                "images",
                queryset=(
                    ProductImage.objects
                    .filter(is_active=True)
                    .order_by(
                        "-is_main",
                        "order",
                        "id",
                    )
                ),
            ),
            Prefetch(
                "variants",
                queryset=(
                    ProductVariant.objects
                    .filter(is_active=True)
                    .prefetch_related(
                        Prefetch(
                            "images",
                            queryset=(
                                ProductVariantImage.objects
                                .filter(is_active=True)
                                .order_by(
                                    "-is_main",
                                    "order",
                                    "id",
                                )
                            ),
                        )
                    )
                    .order_by(
                        "variant_type",
                        "name",
                        "value",
                        "id",
                    )
                ),
                to_attr="active_variants",
            ),
            Prefetch(
                "product_accessories",
                queryset=(
                    AccessoryProduct.objects
                    .filter(accessory__is_active=True)
                    .select_related("accessory")
                ),
                to_attr="active_accessory_links",
            ),
            Prefetch(
                "article_links",
                queryset=(
                    ProductArticleLink.objects
                    .filter(
                        is_active=True,
                        article__is_published=True,
                    )
                    .select_related(
                        "article",
                        "article__category",
                        "article__author",
                    )
                    .order_by(
                        "sort_order",
                        "-article__published_at",
                    )
                ),
                to_attr="active_article_links",
            ),
            Prefetch(
                "additional_videos",
                queryset=(
                    ProductVideo.objects
                    .filter(is_active=True)
                    .order_by("display_order")
                ),
                to_attr="active_videos",
            ),
            Prefetch(
                "questions",
                queryset=(
                    ProductQuestion.objects
                    .filter(is_public=True)
                    .select_related(
                        "user",
                        "answered_by",
                    )
                    .order_by("-created_at")[:10]
                ),
                to_attr="visible_questions",
            ),
        ),
        slug=slug,
        is_active=True,
        approval_status="approved",
    )

    # ============================================================
    # Track product view
    # ============================================================

    Product.objects.filter(
        pk=product.pk,
    ).update(
        views_count=F("views_count") + 1
    )

    # ============================================================
    # Recently viewed
    # ============================================================

    if request.user.is_authenticated:
        RecentlyViewed.objects.update_or_create(
            user=request.user,
            product=product,
            defaults={
                "viewed_at": timezone.now(),
            },
        )
    else:
        _save_guest_recently_viewed(
            request,
            product,
        )

    # ============================================================
    # Currency
    # ============================================================

    user_currency = get_user_currency(
        request
    )

    base_currency = get_base_currency()

    # ============================================================
    # Product and variant image helpers
    # ============================================================

    def safe_url(image_field):
        if not image_field:
            return None

        try:
            return image_field.url
        except Exception:
            return None

    def push_image(
        images,
        image_field,
        alt,
    ):
        original_src = safe_url(
            image_field
        )

        if not original_src:
            return

        existing_originals = {
            item["original"]
            for item in images
            if item.get("original")
        }

        if original_src in existing_originals:
            return

        src = get_optimized_image_url(
            image_field,
            "product_detail",
        )

        thumb = get_optimized_image_url(
            image_field,
            "product_gallery",
        )

        images.append({
            "src": src or original_src,
            "thumb": thumb or src or original_src,
            "original": original_src,
            "alt": alt or product.name,
        })

    def build_product_gallery():
        images = []

        push_image(
            images,
            product.main_image,
            product.name,
        )

        for image in product.images.all():
            push_image(
                images,
                image.image,
                image.alt_text or product.name,
            )

        return images

    def build_variant_gallery(variant):
        images = []

        variant_label = (
            f"{product.name} - "
            f"{variant.value or variant.name}"
        )

        push_image(
            images,
            variant.image,
            variant_label,
        )

        for image in variant.images.all():
            push_image(
                images,
                image.image,
                image.alt_text or variant_label,
            )

        return images

    # ============================================================
    # Variants
    # ============================================================

    all_variants = list(
        getattr(
            product,
            "active_variants",
            [],
        )
    )

    variants_by_type = {}
    variant_options = {}

    for variant in all_variants:
        variant_type = (
            variant.variant_type
            or "other"
        )

        variants_by_type.setdefault(
            variant_type,
            [],
        )

        variant_options.setdefault(
            variant_type,
            [],
        )

        variants_by_type[
            variant_type
        ].append(
            variant
        )

        if (
            variant.value
            not in variant_options[variant_type]
        ):
            variant_options[
                variant_type
            ].append(
                variant.value
            )

    size_variants = variants_by_type.get(
        "size",
        [],
    )

    color_variants = variants_by_type.get(
        "color",
        [],
    )

    variant_groups = []

    for (
        variant_type,
        variant_label,
    ) in ProductVariant.VARIANT_TYPES:
        options = variants_by_type.get(
            variant_type,
            [],
        )

        if options:
            variant_groups.append({
                "type": variant_type,
                "label": variant_label,
                "options": options,
            })

    # Never preselect a variant on initial page load.
    selected_variant = None
    selected_variant_id = None

    # Keep the initial page state on the main product gallery.
    # No variant is selected until the customer clicks one.
    default_variant = None
    first_variant = all_variants[0] if all_variants else None

    current_price = product.price
    current_compare_price = (
        product.compare_price
    )

    # ============================================================
    # Product and variant gallery JSON
    # ============================================================

    gallery_images = (
        build_product_gallery()
    )

    variant_data = {}

    for variant in all_variants:
        variant_price = (
            product.price
            + variant.price_adjustment
        )

        variant_compare_price = None

        if product.compare_price:
            variant_compare_price = (
                product.compare_price
                + variant.price_adjustment
            )

        converted_variant_price = convert_price(
            variant_price,
            base_currency,
            user_currency,
        )

        variant_images = (
            build_variant_gallery(
                variant
            )
        )

        variant_data[str(variant.pk)] = {
            "id": variant.pk,
            "name": variant.name,
            "value": variant.value,
            "variant_type": variant.variant_type,
            "price": float(
                converted_variant_price
                or variant_price
            ),
            "price_display": format_currency(
                variant_price,
                request,
            ),
            "price_raw": float(
                variant_price
            ),
            "compare_price_display": (
                format_currency(
                    variant_compare_price,
                    request,
                )
                if variant_compare_price
                else ""
            ),
            "sku": (
                variant.sku
                or (
                    f"{product.sku}-"
                    f"{str(variant.value or '')[:3]}"
                )
            ),
            "stock": variant.stock_quantity,
            "price_adjustment": float(
                variant.price_adjustment
            ),
            "price_adjustment_display": (
                format_currency(
                    variant.price_adjustment,
                    request,
                )
            ),
            "image": (
                variant_images[0]["src"]
                if variant_images
                else ""
            ),
            "images": variant_images,
            "gallery_images": variant_images,
            "variant_images": variant_images,
            "color_code": (
                variant.color_code
                or "#CCCCCC"
            ),
            "is_available": bool(
                variant.is_available
            ),
        }

    # ============================================================
    # Vendor offers
    # ============================================================

    approved_vendor_offers = list(
        product.vendor_offers
        .filter(
            is_active=True,
            approval_status=(
                VendorProductOffer
                .STATUS_APPROVED
            ),
        )
        .select_related(
            "vendor",
            "variant",
        )
        .order_by(
            "-is_preferred",
            "-is_featured",
            "price",
            "-created_at",
        )
    )

    default_vendor_offer = next(
        (
            offer
            for offer
            in approved_vendor_offers
            if offer.is_available
        ),
        (
            approved_vendor_offers[0]
            if approved_vendor_offers
            else None
        ),
    )

    # ============================================================
    # Reviews and review videos
    # ============================================================

    visible_reviews_queryset = (
        ProductReview.objects
        .filter(product=product)
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "review_videos",
                queryset=(
                    ReviewVideo.objects
                    .order_by(
                        "-is_main",
                        "-created_at",
                        "-id",
                    )
                ),
                to_attr="visible_review_videos",
            )
        )
        .order_by("-created_at")[:10]
    )

    visible_reviews = _attach_review_media(
        request,
        visible_reviews_queryset,
    )

    # ============================================================
    # Accessories and product videos
    # ============================================================

    accessories = getattr(
        product,
        "active_accessory_links",
        [],
    )

    videos = getattr(
        product,
        "active_videos",
        [],
    )

    # ============================================================
    # Editorial articles
    # ============================================================

    product_article_links = list(
        getattr(
            product,
            "active_article_links",
            [],
        )
    )

    product_article_links_hero = [
        link
        for link in product_article_links
        if link.placement == "hero"
    ]

    product_article_links_overview = [
        link
        for link in product_article_links
        if link.placement
        in {
            "overview",
            "description",
        }
    ]

    product_article_links_tab = [
        link
        for link in product_article_links
        if link.placement == "articles_tab"
    ]

    # ============================================================
    # Related products
    # ============================================================

    related_products = (
        Product.objects
        .filter(
            category=product.category,
            is_active=True,
            approval_status="approved",
        )
        .exclude(pk=product.pk)
        .select_related(
            "brand",
            "vendor",
            "vendor__vendor_profile",
        )
    )

    related_products = (
        order_storefront_products(
            related_products,
            "-is_featured",
            "-rating_avg",
            "-sales_count",
        )[:8]
    )

    top_rated = (
        Product.objects
        .filter(
            category=product.category,
            is_active=True,
            rating_avg__gt=0,
            approval_status="approved",
        )
        .exclude(pk=product.pk)
        .select_related(
            "vendor",
            "vendor__vendor_profile",
        )
    )

    top_rated = (
        order_storefront_products(
            top_rated,
            "-rating_avg",
            "-rating_count",
        )[:8]
    )

    bestsellers = (
        Product.objects
        .filter(
            category=product.category,
            is_active=True,
            approval_status="approved",
        )
        .exclude(pk=product.pk)
        .select_related(
            "vendor",
            "vendor__vendor_profile",
        )
    )

    bestsellers = (
        order_storefront_products(
            bestsellers,
            "-sales_count",
            "-rating_avg",
        )[:8]
    )

    frequently_bought_together = (
        Product.objects
        .filter(
            is_active=True,
            approval_status="approved",
        )
        .exclude(pk=product.pk)
        .select_related(
            "vendor",
            "vendor__vendor_profile",
        )
    )

    frequently_bought_together = (
        order_storefront_products(
            frequently_bought_together,
            "-sales_count",
            "-rating_avg",
        )[:8]
    )

    # ============================================================
    # Recently viewed
    # ============================================================

    recently_viewed = []

    if request.user.is_authenticated:
        recently_viewed = (
            RecentlyViewed.objects
            .filter(user=request.user)
            .exclude(product=product)
            .select_related("product")
            .order_by("-viewed_at")[:12]
        )

    # ============================================================
    # AI recommendations
    # ============================================================

    ai_recommendations = (
        Product.objects
        .filter(
            is_active=True,
            approval_status="approved",
        )
        .exclude(pk=product.pk)
        .select_related(
            "vendor",
            "vendor__vendor_profile",
        )
    )

    ai_recommendations = (
        order_storefront_products(
            ai_recommendations,
            "-views_count",
            "-rating_avg",
            "-sales_count",
        )[:8]
    )

    # ============================================================
    # Rating breakdown
    # ============================================================

    review_stats = calculate_product_review_stats(
        product.pk,
    )

    real_total_reviews = review_stats["count"]
    review_average = review_stats["average"]
    verified_review_count = review_stats["verified_count"]

    five_star_count = review_stats["five_star_count"]
    four_star_count = review_stats["four_star_count"]
    three_star_count = review_stats["three_star_count"]

    five_star_percent = review_stats["five_star_percent"]
    four_star_percent = review_stats["four_star_percent"]
    three_star_percent = review_stats["three_star_percent"]

    # Self-heal old or manually edited cached product values immediately.
    # This guarantees that this response, SEO schema, product cards, and the
    # Reviews tab all use the real ProductReview rows as their source of truth.
    cached_average = Decimal(
        str(product.rating_avg or 0)
    ).quantize(Decimal("0.01"))

    if (
        int(product.rating_count or 0) != real_total_reviews
        or cached_average != review_average
    ):
        Product.objects.filter(pk=product.pk).update(
            rating_count=real_total_reviews,
            rating_avg=review_average,
        )

        # Keep the already-loaded object correct for this same response.
        product.rating_count = real_total_reviews
        product.rating_avg = review_average

    question_count = (
        ProductQuestion.objects
        .filter(
            product=product,
            is_public=True,
        )
        .count()
    )

    # ============================================================
    # Explore categories
    # ============================================================

    all_categories = (
        Category.objects
        .filter(
            is_active=True,
            parent=None,
        )
        .annotate(
            approved_product_count=Count(
                "products",
                filter=Q(
                    products__is_active=True,
                    products__approval_status=(
                        "approved"
                    ),
                ),
            )
        )
        .order_by("name")[:12]
    )

    # ============================================================
    # Wishlist
    # ============================================================

    if request.user.is_authenticated:
        in_wishlist = (
            Wishlist.objects
            .filter(
                user=request.user,
                product=product,
            )
            .exists()
        )
    else:
        guest_wishlist = {
            str(product_id)
            for product_id
            in request.session.get(
                GUEST_WISHLIST_SESSION_KEY,
                [],
            )
        }

        in_wishlist = (
            str(product.pk)
            in guest_wishlist
        )

    # ============================================================
    # Vendor information
    # ============================================================

    vendor_profile = getattr(
        product.vendor,
        "vendor_profile",
        None,
    )

    try:
        manufacturer_warranty = (
            product.manufacturer_warranty
        )
    except ManufacturerWarranty.DoesNotExist:
        manufacturer_warranty = None

    vendor_contact_options = (
        _vendor_contact_options(
            vendor_profile,
            product=product,
            request=request,
        )
    )

    condition_value = (
        getattr(
            product,
            "condition",
            "",
        )
        or ""
    )

    default_condition_label = (
        getattr(
            product,
            "condition_label",
            "",
        )
        or condition_value
        .replace("_", " ")
        .title()
    )

    condition_label = translated_key(
        translation_key_for_condition(
            condition_value
        ),
        default_condition_label,
        request=request,
    )

    vendor_name = (
        getattr(
            product,
            "vendor_display_name",
            "",
        )
        or (
            getattr(
                vendor_profile,
                "store_name",
                "",
            )
            if vendor_profile
            else ""
        )
    )

    vendor_package = (
        getattr(
            product,
            "vendor_package_name",
            "",
        )
        or (
            getattr(
                vendor_profile,
                "active_plan_name",
                "",
            )
            if vendor_profile
            else ""
        )
    )

    if vendor_profile:
        vendor_package = translated_key(
            (
                "subscription.plan."
                f"{getattr(vendor_profile, 'subscription_tier', 'free')}"
            ),
            vendor_package,
            request=request,
        )

    location_label = (
        getattr(
            product,
            "location_label",
            "",
        )
        or ""
    )

    # ============================================================
    # Service-provider recommendations
    # ============================================================

    try:
        from installers.models import ServicePortfolio
        from installers.services import (
            suggested_categories_for_product,
            suggested_providers_for_product,
        )

        related_service_categories = (
            suggested_categories_for_product(
                product
            )
        )

        suggested_service_providers = list(
            suggested_providers_for_product(
                product
            )
        )

        real_projects_using_product = (
            ServicePortfolio.objects
            .public()
            .optimized()
            .filter(
                project_products__product=product
            )
            .distinct()[:6]
        )

    except Exception:
        related_service_categories = []
        suggested_service_providers = []
        real_projects_using_product = []

    # ============================================================
    # Template context
    # ============================================================

    context = {
        "product": product,

        "size_variants": size_variants,
        "color_variants": color_variants,
        "all_variants": all_variants,
        "variants_by_type": variants_by_type,
        "variant_options": variant_options,
        "variant_groups": variant_groups,

        "approved_vendor_offers": approved_vendor_offers,
        "default_vendor_offer": default_vendor_offer,
        "has_vendor_offers": bool(
            approved_vendor_offers
        ),

        "variant_data_json": json.dumps(
            variant_data
        ),
        "gallery_images": gallery_images,
        "gallery_images_json": json.dumps(
            gallery_images
        ),

        "selected_variant": selected_variant,
        "selected_variant_id": selected_variant_id,
        "default_variant": default_variant,
        "first_variant": first_variant,
        "has_variants": bool(all_variants),

        "current_price": current_price,
        "current_compare_price": (
            current_compare_price
        ),

        "vendor_chat_available": (
            vendor_contact_options.get(
                "can_chat",
                False,
            )
        ),
        "vendor_contact_options": (
            vendor_contact_options
        ),

        "vendor_name": vendor_name,
        "vendor_package": vendor_package,
        "location_label": location_label,
        "condition_label": condition_label,

        "manufacturer_warranty": (
            manufacturer_warranty
        ),

        "accessories": accessories,
        "product_accessories": accessories,

        "videos": videos,
        "product_videos": videos,

        # Both keys are provided for template compatibility.
        "visible_reviews": visible_reviews,
        "reviews": visible_reviews,
        "review_count": real_total_reviews,
        "review_average": review_average,
        "verified_review_count": verified_review_count,

        "product_article_links": (
            product_article_links
        ),
        "product_article_links_hero": (
            product_article_links_hero
        ),
        "product_article_links_overview": (
            product_article_links_overview
        ),
        "product_article_links_tab": (
            product_article_links_tab
        ),

        "related_products": related_products,
        "top_rated_similar": top_rated,
        "best_sellers": bestsellers,
        "frequently_bought_together": (
            frequently_bought_together
        ),
        "recently_viewed": recently_viewed,
        "ai_recommendations": (
            ai_recommendations
        ),

        "all_categories": all_categories,
        "in_wishlist": in_wishlist,

        "five_star_percent": (
            five_star_percent
        ),
        "four_star_percent": (
            four_star_percent
        ),
        "three_star_percent": (
            three_star_percent
        ),
        "question_count": question_count,

        "user_currency": user_currency,

        "product_detail_sections": (
            ProductDetailSection.objects
            .filter(
                is_enabled=True,
                web_enabled=True,
            )
            .order_by(
                "display_order",
                "title",
            )
        ),

        "product_detail_fields": (
            ProductDetailFieldConfig.objects
            .filter(is_enabled=True)
            .order_by(
                "display_order",
                "label",
            )
        ),

        "service_available": bool(
            related_service_categories
        ),
        "related_service_categories": (
            related_service_categories
        ),
        "suggested_service_providers": (
            suggested_service_providers
        ),
        "real_projects_using_product": (
            real_projects_using_product
        ),
    }

    return render(
        request,
        "products/detail.html",
        context,
    )


def _category_hero_image(category):
    """Return the nearest configured category hero without hardcoded media."""
    current = category
    while current:
        image = current.background_image or current.image
        if image:
            return image
        current = current.parent
    return None


def category_view(request, slug):
    """Display category view with all subcategories and dynamic background - APPROVED ONLY"""
    category = get_object_or_404(
        Category.objects.prefetch_related(
            Prefetch(
                'article_links',
                queryset=CategoryArticleLink.objects.filter(
                    is_active=True,
                    article__is_published=True,
                ).select_related('article').order_by('sort_order', '-article__published_at'),
                to_attr='active_article_links',
            )
        ),
        slug=slug,
        is_active=True,
    )
    
    # ====== Get All Subcategories ======
    category_ids = [category.id]
    subcategories = list(category.children.filter(is_active=True).order_by('order', 'name'))
    
    # Also collect products from subcategories
    for child in subcategories:
        category_ids.append(child.id)
        child.approved_product_count = _mobile_category_product_count(child)
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

    category_hero_image = _category_hero_image(category)
    
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

    category_article_links = list(getattr(category, 'active_article_links', []))
    category_article_links_overview = [link for link in category_article_links if link.placement == 'overview']
    category_article_links_cards = [link for link in category_article_links if link.placement in {'guide_card', 'articles_tab'}]

    return render(request, 'products/category_landing.html', {
        'category': category,
        'subcategories': subcategories,
        'products': products_page,
        'vendors_count': vendors_count,
        'current_sort': sort_param,
        'user_currency': user_currency,
        'breadcrumbs': breadcrumbs,
        'category_hero_image': category_hero_image,
        'category_article_links': category_article_links,
        'category_article_links_overview': category_article_links_overview,
        'category_article_links_cards': category_article_links_cards,
    })

def _mobile_authenticated_customer(request, payload=None):
    """
    Authenticate a mobile customer from either:

    - api_token in JSON/form payload; or
    - Authorization: Bearer <token>

    Keeps authentication behavior consistent across mobile endpoints.
    """

    if _auth_mobile_customer_from_request_data is None:
        raise ValueError(
            "Mobile customer app is not available."
        )

    auth_data = dict(payload or {})

    authorization = str(
        request.headers.get("Authorization")
        or ""
    ).strip()

    if (
        authorization.lower().startswith("bearer ")
        and not auth_data.get("api_token")
    ):
        auth_data["api_token"] = authorization.split(
            " ",
            1,
        )[1].strip()

    return _auth_mobile_customer_from_request_data(
        auth_data
    )
    
# ================================
# 🔥 REVIEW VIEWS
# ================================

@login_required
@require_http_methods(["POST"])
@transaction.atomic
def add_review(request, slug):
    """Add a web product review with optional validated video evidence."""
    product = get_object_or_404(
        Product,
        slug=slug,
        is_active=True,
        approval_status="approved",
    )

    if ProductReview.objects.filter(
        product=product,
        user=request.user,
    ).exists():
        messages.warning(request, "You have already reviewed this product.")
        return redirect("products:detail", slug=product.slug)

    try:
        rating = int(request.POST.get("rating", 3))
    except (TypeError, ValueError):
        messages.error(request, "Please select a valid rating between 1 and 5.")
        return redirect("products:detail", slug=product.slug)

    if rating not in {1, 2, 3, 4, 5}:
        messages.error(request, "Please select a valid rating between 1 and 5.")
        return redirect("products:detail", slug=product.slug)

    title = str(request.POST.get("title", "")).strip()
    review_text = str(request.POST.get("review", "")).strip()

    if not title or not review_text:
        messages.error(request, "Title and review are required.")
        return redirect("products:detail", slug=product.slug)

    if len(title) < 5:
        messages.error(request, "Title must be at least 5 characters.")
        return redirect("products:detail", slug=product.slug)

    if len(title) > 200:
        messages.error(request, "Review title cannot exceed 200 characters.")
        return redirect("products:detail", slug=product.slug)

    if len(review_text) < 20:
        messages.error(request, "Review must be at least 20 characters.")
        return redirect("products:detail", slug=product.slug)

    uploaded_video = request.FILES.get("video_review")

    review = ProductReview(
        product=product,
        user=request.user,
        rating=rating,
        title=title,
        review=review_text,
        verified_purchase=False,
    )

    if uploaded_video:
        review.video_review = uploaded_video

    try:
        review.full_clean()
        review.save()

    except ValidationError as error:
        messages.error(
            request,
            _first_validation_error(
                error,
                default="The review could not be submitted.",
            ),
        )

        return redirect(
            "products:detail",
            slug=product.slug,
        )

    except IntegrityError:
        messages.warning(request, "You have already reviewed this product.")
        transaction.set_rollback(True)
        return redirect("products:detail", slug=product.slug)

    _refresh_product_review_stats(product.id)

    messages.success(request, "Review added successfully!")
    return redirect("products:detail", slug=product.slug)


def _first_validation_error(
    error,
    default="The submitted information is invalid.",
):
    """
    Convert Django ValidationError structures into one safe user-facing
    message.

    Handles:
    - field_errors
    - message_dict
    - messages
    - plain ValidationError messages
    """

    if hasattr(error, "message_dict"):
        for field_name, field_errors in error.message_dict.items():
            if not field_errors:
                continue

            first_error = field_errors[0]

            if field_name in {
                "video_review",
                "video_file",
                "thumbnail",
            }:
                return str(first_error)

            label = str(field_name).replace("_", " ").title()

            return f"{label}: {first_error}"

    if getattr(error, "messages", None):
        return str(error.messages[0])

    return str(error) or default


def _review_file_url(request, file_field):
    """
    Return a protected Arolana /media/ URL for review media.

    The storage provider URL is not exposed directly. The request passes
    through Arolana's protected media route.
    """

    if not file_field:
        return ""

    file_name = str(
        getattr(
            file_field,
            "name",
            "",
        )
        or ""
    ).strip()

    if not file_name:
        return ""

    media_path = quote(
        file_name,
        safe="/",
    )

    return request.build_absolute_uri(
        f"/media/{media_path}"
    )


def _review_video_mime_type(file_name):
    """
    Return the browser MIME type for a review video.
    """

    name = str(file_name or "").lower()

    if name.endswith(".webm"):
        return "video/webm"

    if name.endswith(".ogg") or name.endswith(".ogv"):
        return "video/ogg"

    if name.endswith(".mov"):
        return "video/quicktime"

    if name.endswith(".m4v"):
        return "video/x-m4v"

    return "video/mp4"


def _review_video_payloads(request, review):
    """
    Return every video belonging to a product review.

    Supports both existing review-video systems:

    1. ProductReview.video_review
    2. ReviewVideo.video_file through review.review_videos

    Duplicate storage paths are removed so the same video is never displayed
    twice.
    """

    if not review:
        return []

    videos = []
    seen_file_names = set()

    def append_video(
        *,
        payload_id,
        title,
        video_file,
        thumbnail=None,
        is_main=False,
        source="review",
    ):
        if not video_file:
            return

        file_name = str(
            getattr(
                video_file,
                "name",
                "",
            )
            or ""
        ).strip()

        if not file_name:
            return

        if file_name in seen_file_names:
            return

        video_url = _review_file_url(
            request,
            video_file,
        )

        if not video_url:
            return

        seen_file_names.add(file_name)

        thumbnail_url = ""

        if thumbnail and getattr(
            thumbnail,
            "name",
            "",
        ):
            thumbnail_url = _review_file_url(
                request,
                thumbnail,
            )

        videos.append({
            "id": str(payload_id),
            "title": (
                str(title or "").strip()
                or "Customer review video"
            ),
            "url": video_url,
            "video_url": video_url,
            "mime_type": _review_video_mime_type(
                file_name
            ),
            "thumbnail_url": thumbnail_url,
            "poster_url": thumbnail_url,
            "is_main": bool(is_main),
            "source": source,
            "file_name": file_name.rsplit("/", 1)[-1],
        })

    # ProductReview.video_review
    direct_video = getattr(
        review,
        "video_review",
        None,
    )

    append_video(
        payload_id=f"review-main-{review.pk}",
        title=getattr(review, "title", ""),
        video_file=direct_video,
        is_main=True,
        source="product_review",
    )

    # ReviewVideo rows prefetched by the product-detail views.
    review_video_rows = getattr(
        review,
        "visible_review_videos",
        None,
    )

    if review_video_rows is None:
        try:
            review_video_rows = list(
                review.review_videos.all().order_by(
                    "-is_main",
                    "-created_at",
                    "-id",
                )
            )
        except Exception:
            review_video_rows = []

    for video in review_video_rows:
        append_video(
            payload_id=f"review-video-{video.pk}",
            title=(
                getattr(video, "title", "")
                or getattr(review, "title", "")
            ),
            video_file=getattr(
                video,
                "video_file",
                None,
            ),
            thumbnail=getattr(
                video,
                "thumbnail",
                None,
            ),
            is_main=getattr(
                video,
                "is_main",
                False,
            ),
            source="review_video",
        )

    videos.sort(
        key=lambda item: (
            not item.get("is_main", False),
            item.get("source") != "product_review",
            item.get("title", "").lower(),
        )
    )

    return videos


def _review_video_url(request, review):
    """
    Backward-compatible single review-video URL.

    New code should use _review_video_payloads() because one review may contain
    more than one video.
    """

    videos = _review_video_payloads(
        request,
        review,
    )

    return videos[0]["url"] if videos else ""


def _attach_review_media(request, reviews):
    """
    Attach template-ready video data to every review object.
    """

    prepared_reviews = list(reviews or [])

    for review in prepared_reviews:
        video_payloads = _review_video_payloads(
            request,
            review,
        )

        review.display_video_payloads = video_payloads
        review.has_display_video = bool(video_payloads)
        review.display_video_url = (
            video_payloads[0]["url"]
            if video_payloads
            else ""
        )

    return prepared_reviews


def _refresh_product_review_stats(product_id):
    """Backward-compatible wrapper around the shared review-stat service."""

    return refresh_product_review_stats(product_id)
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
    """Answer a product question as the product vendor or staff."""
    qna = get_object_or_404(
        ProductQuestion.objects.select_related(
            "product",
            "product__vendor",
        ),
        id=qna_id,
    )

    is_product_vendor = request.user_id == qna.product.vendor_id

    if not (is_product_vendor or request.user.is_staff):
        return JsonResponse(
            {
                "success": False,
                "error": "You do not have permission.",
            },
            status=403,
        )

    answer_text = str(request.POST.get("answer", "")).strip()

    if not answer_text:
        messages.error(request, "Please enter an answer.")
        return redirect("products:detail", slug=qna.product.slug)

    if len(answer_text) < 10:
        messages.error(request, "Answer must be at least 10 characters.")
        return redirect("products:detail", slug=qna.product.slug)

    qna.answer = answer_text
    qna.answered_by = request.user
    qna.answered_at = timezone.now()

    qna.save(
        update_fields=[
            "answer",
            "answered_by",
            "answered_at",
            "updated_at",
        ]
    )

    messages.success(request, "Answer posted successfully!")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "success": True,
                "answer": answer_text,
                "answered_by": (
                    request.user.get_full_name()
                    or request.user.username
                ),
                "answered_at": qna.answered_at.strftime(
                    "%b %d, %Y at %I:%M %p"
                ),
            }
        )

    return redirect("products:detail", slug=qna.product.slug)


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
    """Edit an answer as the product vendor or staff."""
    qna = get_object_or_404(
        ProductQuestion.objects.select_related(
            "product",
            "product__vendor",
        ),
        id=qna_id,
    )

    is_product_vendor = request.user_id == qna.product.vendor_id

    if not (is_product_vendor or request.user.is_staff):
        return JsonResponse(
            {
                "success": False,
                "error": "Permission denied.",
            },
            status=403,
        )

    answer_text = str(request.POST.get("answer", "")).strip()

    if not answer_text or len(answer_text) < 10:
        messages.error(request, "Answer must be at least 10 characters.")
        return redirect("products:detail", slug=qna.product.slug)

    qna.answer = answer_text
    qna.answered_by = request.user
    qna.answered_at = timezone.now()

    qna.save(
        update_fields=[
            "answer",
            "answered_by",
            "answered_at",
            "updated_at",
        ]
    )

    messages.success(request, "Answer updated successfully!")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "success": True,
                "answer": answer_text,
                "answered_by": (
                    request.user.get_full_name()
                    or request.user.username
                ),
                "answered_at": qna.answered_at.strftime(
                    "%b %d, %Y at %I:%M %p"
                ),
            }
        )

    return redirect("products:detail", slug=qna.product.slug)


# ================================
# 🔥 API VIEWS
# ================================

def get_variant_details(request, variant_id):
    """API: Get variant details with pricing and ALL variant images."""
    try:
        variant = (
            ProductVariant.objects
            .select_related(
                "product",
            )
            .prefetch_related(
                Prefetch(
                    "images",
                    queryset=(
                        ProductVariantImage.objects
                        .filter(
                            is_active=True,
                        )
                        .order_by(
                            "-is_main",
                            "order",
                            "id",
                        )
                    ),
                )
            )
            .get(
                id=variant_id,
                is_active=True,
                product__is_active=True,
                product__approval_status="approved",
            )
        )
        product = variant.product

        def safe_url(image_field):
            if not image_field:
                return None
            try:
                return image_field.url
            except Exception:
                return None

        def push_image(images, image_field, alt):
            if not image_field:
                return
            src = get_optimized_image_url(image_field, "product_gallery")
            original = safe_url(image_field)
            if not src:
                return
            if src not in {image['src'] for image in images}:
                images.append({
                    'src': src,
                    'original': original or src,
                    'alt': alt or product.name,
                })

        variant_images = []
        push_image(
            variant_images,
            variant.image,
            f"{product.name} - {variant.value}"
        )
        for image in variant.images.all():
            push_image(
                variant_images,
                image.image,
                image.alt_text or f"{product.name} - {variant.value}"
            )

        product_gallery = []
        push_image(product_gallery, product.main_image, product.name)
        for image in product.images.filter(is_active=True).order_by('-is_main', 'order', 'id'):
            push_image(product_gallery, image.image, image.alt_text or product.name)

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
                'main_image': get_optimized_image_url(product.main_image, "product_detail") if product.main_image else None,
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
        'image': get_optimized_image_url(product.main_image, "product_card") if product.main_image else None,
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
                'image': get_optimized_image_url(a.accessory.image, "accessory_thumb") if a.accessory.image else None,
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

    try:
        for item in cart.items.select_related('product', 'product__vendor', 'product__vendor__vendor_profile'):
            product = getattr(item, 'product', None)
            vendor_profile = getattr(getattr(product, 'vendor', None), 'vendor_profile', None)
            if vendor_profile:
                _create_vendor_lead(
                    request,
                    vendor_profile,
                    'checkout_started',
                    product=product,
                    payload={'source': 'web', 'quantity': item.quantity},
                    metadata={'cart_id': cart.id},
                )
    except Exception:
        pass
    
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


@staff_member_required
@require_GET
def debug_colors(request, product_id):
    """
    Internal staff-only product variant debugging page.
    """

    product = get_object_or_404(
        Product.objects.prefetch_related(
            "variants",
        ),
        id=product_id,
    )

    variants = product.variants.filter(
        is_active=True,
    ).order_by(
        "variant_type",
        "name",
        "value",
    )

    html = f"""
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <title>Debug Colors - {product.name}</title>
    </head>

    <body>
        <h1>Debug Colors for {product.name}</h1>

        <h2>Variants</h2>

        <ul>
    """

    for variant in variants:
        html += (
            "<li>"
            f"{variant.variant_type}: "
            f"{variant.name} = "
            f"{variant.value}"
            "</li>"
        )

    html += """
        </ul>
    </body>
    </html>
    """

    return HttpResponse(
        html
    )

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

    return _mobile_file_url(request, image, preset="product_card")


def parse_price_safe(value):
    try:
        return Decimal(str(value or "0").replace(",", ""))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _mobile_storage_file_is_openable(storage, name):
    if not storage or not name:
        return False
    try:
        media_file = storage.open(name, "rb")
        media_file.close()
        return True
    except Exception:
        return False


def _mobile_file_url(request, file_field, preset=None):
    if not file_field:
        return None

    try:
        if preset:
            optimized_name = optimized_name_for(getattr(file_field, "name", ""), preset)
            storage = getattr(file_field, "storage", None)
            if _mobile_storage_file_is_openable(storage, optimized_name):
                file_url = storage.url(optimized_name)
            else:
                file_url = file_field.url
        else:
            file_url = file_field.url
    except Exception:
        try:
            file_url = file_field.url
        except Exception:
            return None

    if file_url.startswith("http://") or file_url.startswith("https://"):
        return file_url

    return request.build_absolute_uri(file_url)


def _mobile_original_file_url(request, file_field):
    if not file_field:
        return None
    try:
        file_url = file_field.url
    except Exception:
        return None
    if file_url.startswith(("http://", "https://")):
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

    cache_key = f"mobile-category-product-count:{category.id}:{category.updated_at.timestamp() if getattr(category, 'updated_at', None) else '0'}"
    return local_get_or_set(
        cache_key,
        lambda: Product.objects.filter(
            category_id__in=_category_descendant_ids(category),
            is_active=True,
            approval_status="approved",
        ).count(),
        120,
    )


def _mobile_category_article_payload(request, article_link):
    if not article_link:
        return None
    article = getattr(article_link, "article", None)
    if not article:
        return None
    image = getattr(article, "display_image", None)
    return {
        "id": article_link.id,
        "article_id": article.id,
        "title": article_link.display_label,
        "teaser": strip_tags(article_link.display_teaser or "")[:220],
        "placement": article_link.placement,
        "open_behavior": article_link.open_behavior,
        "image": _mobile_file_url(request, image, preset="blog_card") if image else "",
        "thumbnail_url": _mobile_file_url(request, image, preset="blog_card") if image else "",
        "url": request.build_absolute_uri(article_link.article_url),
        "reading_time": getattr(article, "reading_time", None),
    }


def _mobile_category_payload(request, category, include_children=True):
    if not category:
        return None

    children = []
    if include_children:
        children = [
            _mobile_category_payload(request, child, include_children=False)
            for child in category.children.filter(is_active=True).order_by("order", "name")
        ]
        children = [child for child in children if child]

    product_count = _mobile_category_product_count(category)
    direct_product_count = Product.objects.filter(
        category=category,
        is_active=True,
        approval_status="approved",
    ).count()
    subcategory_count = category.children.filter(is_active=True).count()
    category_image = getattr(category, "image", None)
    category_background = getattr(category, "background_image", None)
    hero_image = _category_hero_image(category)

    fallback_image_url = request.build_absolute_uri(
        f"{settings.STATIC_URL.rstrip('/')}/products/images/category-default.svg"
    )
    hero_image_url = (
        _mobile_file_url(request, hero_image, preset="category_banner")
        if hero_image
        else fallback_image_url
    )

    return {
        "id": category.id,
        "name": translated_field(category, "name", request=request),
        "slug": category.slug,
        "description": strip_tags(
            translated_field(category, "description", request=request, default="") or ""
        )[:180],
        "image": _mobile_file_url(request, category_image, preset="category_card"),
        "thumbnail_url": _mobile_file_url(request, category_image, preset="category_card"),
        "background_image": hero_image_url,
        "image_url": hero_image_url,
        "hero_image_url": hero_image_url,
        "category_image_url": _mobile_file_url(request, category_image, preset="category_card"),
        "category_banner_url": hero_image_url,
        "category_icon": getattr(category, "icon", "") or "",
        "category_icon_url": "",
        "fallback_image_url": fallback_image_url,
        "original_url": _mobile_original_file_url(request, hero_image),
        "url": request.build_absolute_uri(reverse("products:category", args=[category.slug])),
        "hero_title": translated_field(category, "hero_title", request=request, default="") or "",
        "hero_subtitle": translated_field(category, "hero_subtitle", request=request, default="") or "",
        "show_hero_title": bool(getattr(category, "show_hero_title", True)),
        "show_hero_subtitle": bool(getattr(category, "show_hero_subtitle", True)),
        "show_hero_text": bool(getattr(category, "show_hero_title", True) or getattr(category, "show_hero_subtitle", True)),
        "hero_height_mobile": getattr(category, "hero_height_mobile", None) or 360,
        "hero_image_brightness": getattr(category, "hero_image_brightness", None) or 62,
        "hero_text_color": getattr(category, "hero_text_color", "") or "",
        "product_count": product_count,
        "direct_product_count": direct_product_count,
        "subcategory_count": subcategory_count,
        "children_count": subcategory_count,
        "children": children,
    }


def _digits_only(value):
    return re.sub(r"\D+", "", str(value or ""))


def _product_absolute_url(request, product):
    if not product:
        return ""
    if request is None:
        try:
            return product.get_absolute_url()
        except Exception:
            return ""
    try:
        return request.build_absolute_uri(product.get_absolute_url())
    except Exception:
        try:
            return request.build_absolute_uri(reverse("products:detail", args=[product.slug]))
        except Exception:
            return ""


def _product_whatsapp_message(product, product_url):
    product_name = getattr(product, "name", "") or "this product"
    product_price = ""
    if product is not None:
        try:
            product_price = format_currency(getattr(product, "price", ""))
        except Exception:
            product_price = str(getattr(product, "price", "") or "")
    return (
        "Hello, I saw this product on Arolana and I’m interested.\n\n"
        f"Product: {product_name}\n"
        f"Price: {product_price or 'Not provided'}\n"
        f"Link: {product_url or 'Not provided'}\n\n"
        "Please confirm availability. For safety, I prefer to complete payment and order tracking through Arolana."
    )


def _vendor_plan_limits(vendor_profile):
    try:
        return get_tier_limits(getattr(vendor_profile, "subscription_tier", "free"))
    except Exception:
        return {}


def _vendor_contact_options(vendor_profile, product=None, reveal_phone=False, request=None):
    if not vendor_profile:
        return {
            "can_chat": False,
            "can_request_callback": False,
            "can_show_phone": False,
            "can_show_whatsapp": False,
            "phone": "",
            "whatsapp": "",
            "direct_contact_badge": False,
            "lead_tracking_enabled": False,
            "hide_phone_until_click": True,
            "safety_note": "For your safety, keep payment and order confirmation inside Arolana.",
        }

    vendor_user = getattr(vendor_profile, "user", None)
    limits = _vendor_plan_limits(vendor_profile)
    eligible = bool(getattr(vendor_profile, "direct_contact_eligible", False))
    active_plan = bool(vendor_user and user_has_paid_subscription(vendor_user))
    phone_number = (getattr(vendor_profile, "business_phone", "") or getattr(vendor_profile, "support_phone", "") or "").strip()
    whatsapp_number = (getattr(vendor_profile, "whatsapp_number", "") or getattr(vendor_profile, "business_phone", "") or getattr(vendor_profile, "support_phone", "") or "").strip()
    hide_phone_until_click = bool(limits.get("hide_phone_until_click", True))

    can_chat = bool(vendor_user and limits.get("chat_enabled") and active_plan)
    can_request_callback = bool(
        eligible
        and active_plan
        and getattr(vendor_profile, "allow_callback_requests", False)
        and limits.get("can_receive_callback_requests", False)
    )
    can_show_phone = bool(
        eligible
        and active_plan
        and getattr(vendor_profile, "allow_phone_display", False)
        and limits.get("can_show_phone", False)
        and phone_number
    )
    can_show_whatsapp = bool(
        eligible
        and active_plan
        and getattr(vendor_profile, "allow_whatsapp_display", False)
        and limits.get("can_show_whatsapp", False)
        and whatsapp_number
    )

    phone_visible = can_show_phone and (reveal_phone or not hide_phone_until_click)
    whatsapp_visible = can_show_whatsapp
    product_url = _product_absolute_url(request, product)
    whatsapp_message = _product_whatsapp_message(product, product_url)
    return {
        "can_chat": can_chat,
        "can_request_callback": can_request_callback,
        "can_show_phone": can_show_phone,
        "can_show_whatsapp": can_show_whatsapp,
        "phone": phone_number if phone_visible else "",
        "phone_masked": bool(can_show_phone and not phone_visible),
        "whatsapp": whatsapp_number if whatsapp_visible else "",
        "whatsapp_url": f"https://wa.me/{_digits_only(whatsapp_number)}?text={quote(whatsapp_message)}" if whatsapp_visible and _digits_only(whatsapp_number) else "",
        "whatsapp_message": whatsapp_message if whatsapp_visible else "",
        "direct_contact_badge": bool(eligible and active_plan and limits.get("can_show_direct_contact_badge", False)),
        "lead_tracking_enabled": bool(active_plan and limits.get("lead_tracking_enabled", False)),
        "hide_phone_until_click": hide_phone_until_click,
        "safety_note": "For your safety, keep payment and order confirmation inside Arolana.",
        "product_id": getattr(product, "id", None),
    }


def _request_ip_address(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.META.get("HTTP_X_REAL_IP")
    if real_ip:
        return real_ip.strip()
    return request.META.get("REMOTE_ADDR")


def _request_country_code(request):
    for header in ("HTTP_CF_IPCOUNTRY", "HTTP_CLOUDFRONT_VIEWER_COUNTRY", "HTTP_X_COUNTRY_CODE", "HTTP_X_FORWARDED_COUNTRY", "HTTP_X_APPENGINE_COUNTRY", "HTTP_FLY_CLIENT_IP_COUNTRY"):
        country_code = (request.META.get(header) or "").strip().upper()
        if len(country_code) == 2 and country_code != "XX":
            return country_code
    return request.session.get("user_country_code", "")


def _request_page_url(request):
    try:
        return request.build_absolute_uri()
    except Exception:
        return request.META.get("HTTP_REFERER", "") or ""


def _create_vendor_lead(request, vendor_profile, action_type, product=None, customer=None, payload=None, metadata=None):
    if VendorLead is None or not vendor_profile:
        return None
    options = _vendor_contact_options(vendor_profile, product=product, request=request)
    if not options.get("lead_tracking_enabled"):
        return None
    payload = payload or {}
    customer_user = getattr(customer, "user", None)
    if customer_user is not None and not getattr(customer_user, "is_authenticated", True):
        customer_user = None
    if customer_user is None and getattr(request.user, "is_authenticated", False):
        customer_user = request.user
    if not request.session.session_key:
        request.session.save()
    product_url = payload.get("product_url") or ""
    if product and not product_url:
        product_url = _product_absolute_url(request, product)
    page_url = payload.get("page_url") or payload.get("current_url") or request.META.get("HTTP_REFERER") or _request_page_url(request)
    source = (payload.get("source") or payload.get("platform") or "web").strip()
    extra_data = {
        "payload": payload,
        "metadata": metadata or {},
    }
    return VendorLead.objects.create(
        vendor=vendor_profile,
        product=product,
        customer_user=customer_user,
        guest_session_key=request.session.session_key or "",
        action_type=action_type,
        customer_name=(payload.get("full_name") or payload.get("customer_name") or getattr(customer, "full_name", "") or "").strip(),
        customer_phone=(payload.get("phone_number") or payload.get("customer_phone") or getattr(customer, "phone_number", "") or "").strip(),
        customer_email=(payload.get("email") or payload.get("customer_email") or getattr(customer, "email", "") or "").strip(),
        source=source,
        page_url=page_url[:800],
        product_url=product_url[:800],
        ip_address=_request_ip_address(request),
        country=_request_country_code(request),
        currency=(payload.get("currency") or getattr(request, "user_currency", "") or request.session.get("user_currency", "") or "").upper()[:10],
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        metadata=metadata or {},
        extra_data=extra_data,
    )


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
    subscription_badge = getattr(vendor_profile, "active_plan_name", "") or getattr(vendor_profile, "badge_level", "") or getattr(vendor_profile, "subscription_plan_label", "")
    subscription_badge = translated_key(
        f"subscription.plan.{getattr(vendor_profile, 'subscription_tier', 'free')}",
        subscription_badge,
        request=request,
    )
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
        "address_line_1": getattr(vendor_profile, "address_line_1", ""),
        "city": getattr(vendor_profile, "city", ""),
        "state": getattr(vendor_profile, "state", ""),
        "location": getattr(vendor_profile, "location_label", ""),
        "location_label": getattr(vendor_profile, "location_label", ""),
        "logo": _mobile_file_url(request, getattr(vendor_profile, "store_logo", None), preset="logo"),
        "logo_url": _mobile_file_url(request, getattr(vendor_profile, "store_logo", None), preset="logo"),
        "banner": _mobile_file_url(request, getattr(vendor_profile, "store_banner", None), preset="vendor_banner"),
        "banner_url": _mobile_file_url(request, getattr(vendor_profile, "store_banner", None), preset="vendor_banner"),
        "description": translated_field(vendor_profile, "description", request=request),
        "verified": bool(getattr(vendor_profile, "is_verified", False)),
        "is_verified": bool(getattr(vendor_profile, "is_verified", False)),
        "manufacturer_verified": bool(vendor_type == "manufacturer" and getattr(vendor_profile, "manufacturer_verified", False)),
        "manufacturer_badge_label": getattr(vendor_profile, "manufacturer_badge_label", "") or "Verified Manufacturer",
        "badges": badges,
        "subscription_tier": getattr(vendor_profile, "subscription_tier", "free"),
        "vendor_package": subscription_badge,
        "vendor_package_name": subscription_badge,
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
        "business_phone": getattr(vendor_profile, "business_phone", ""),
        "whatsapp_number": getattr(vendor_profile, "whatsapp_number", ""),
        "website": getattr(vendor_profile, "website", ""),
        "store_slogan": translated_field(vendor_profile, "store_slogan", request=request),
        "business_hours": translated_field(vendor_profile, "business_hours", request=request),
        "return_policy": translated_field(vendor_profile, "return_policy", request=request),
        "warranty_note": translated_field(vendor_profile, "warranty_note", request=request),
        "delivery_note": translated_field(vendor_profile, "delivery_note", request=request),
        "storefront_accent_color": getattr(vendor_profile, "storefront_accent", "#FF7A00"),
        "store_video_url": getattr(vendor_profile, "store_video_url", ""),
        "featured_categories": getattr(vendor_profile, "featured_category_list", []),
        "store_gallery": getattr(vendor_profile, "store_gallery_list", []),
        "featured_products_note": getattr(vendor_profile, "featured_products_note", ""),
        "business_hours": getattr(vendor_profile, "business_hours", ""),
        "return_policy": getattr(vendor_profile, "return_policy", ""),
        "warranty_note": getattr(vendor_profile, "warranty_note", ""),
        "delivery_note": getattr(vendor_profile, "delivery_note", ""),
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
        "chat_available": _vendor_contact_options(vendor_profile, request=request).get("can_chat", False),
        "vendor_contact_options": _vendor_contact_options(vendor_profile, request=request),
        "url": request.build_absolute_uri(vendor_profile.get_absolute_url()) if hasattr(vendor_profile, "get_absolute_url") else "",
    }

    if include_products:
        payload["products"] = [_mobile_product_payload(request, product) for product in product_qs.select_related("category", "brand", "vendor", "vendor__vendor_profile")[:60]]

    return payload


def _mobile_ad_payload(request, ad, ad_type):
    linked_article = getattr(ad, "linked_article", None)

    def destination_payload(target_url):
        if linked_article:
            return {
                "destination_type": "article",
                "linked_article_id": linked_article.id,
                "linked_article_slug": linked_article.slug,
                "linked_article_title": translated_field(
                    linked_article,
                    "title",
                    request=request,
                ),
                "linked_article_url": request.build_absolute_uri(
                    linked_article.get_absolute_url()
                ),
            }

        raw_url = str(target_url or "").strip()
        path = urlparse(raw_url).path if raw_url else ""
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "products" and parts[1] not in {
            "category",
            "cart",
            "checkout",
        }:
            product_slug = parts[1]
            if Product.objects.filter(
                slug=product_slug,
                is_active=True,
                approval_status="approved",
            ).exists():
                return {
                    "destination_type": "product",
                    "product_slug": product_slug,
                }
            return {
                "destination_type": "search",
                "search_query": getattr(ad, "title", "") or product_slug.replace("-", " "),
            }
        if "/blog/" in path or "/articles/" in path:
            return {
                "destination_type": "article",
                "linked_article_slug": parts[-1] if parts else "",
            }
        return {"destination_type": "web"}

    if ad_type == "creative":
        image = _mobile_file_url(request, getattr(ad, "image_mobile", None) or getattr(ad, "image", None), preset="ad")
        destination = destination_payload(ad.clickthrough_url)
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
            "thumbnail_url": image,
            "creative_type": ad.creative_type,
            **destination,
        }

    if ad_type == "banner":
        image = _mobile_file_url(request, getattr(ad, "image_mobile", None) or getattr(ad, "image", None), preset="ad")
        placement = getattr(ad, "placement", None)
        destination = destination_payload(ad.target_url)
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
            "thumbnail_url": image,
            "video_url": ad.video_url,
            "mobile_height": ad.mobile_height_override or ad.height_override or (placement.height if placement else 220),
            "mobile_width": ad.mobile_width_override or ad.width_override or (placement.width if placement else 1200),
            "mobile_image_fit": ad.mobile_image_fit,
            "image_fit": ad.image_fit,
            **destination,
        }

    image = _mobile_file_url(request, getattr(ad, "image", None), preset="ad")
    destination = destination_payload(ad.target_url)
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
        "thumbnail_url": image,
        "is_featured": ad.is_featured,
        **destination,
    }


def _mobile_article_card_payload(request, article):
    image = getattr(article, "display_image", None)
    category = getattr(article, "category", None)
    return {
        "id": article.id,
        "slug": article.slug,
        "title": translated_field(article, "title", request=request),
        "excerpt": translated_field(article, "excerpt", request=request, default=""),
        "url": request.build_absolute_uri(article.get_absolute_url()),
        "image_url": _mobile_file_url(request, image, preset="blog_card") if image else "",
        "thumbnail_url": _mobile_file_url(request, image, preset="blog_card") if image else "",
        "category": (
            translated_field(category, "name", request=request)
            if category
            else ""
        ),
        "reading_time": article.reading_time,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "views": article.views,
    }


def _mobile_article_comment_payload(request, comment):
    user = comment.user
    avatar = getattr(user, "avatar", None)
    author_name = user.get_full_name() or getattr(user, "username", "") or "Arolana customer"
    return {
        "id": comment.id,
        "comment": comment.comment,
        "author": {
            "id": user.id,
            "name": author_name,
            "avatar_url": _mobile_file_url(request, avatar, preset="avatar") if avatar else "",
        },
        "likes": comment.likes,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "replies": [
            _mobile_article_comment_payload(request, reply)
            for reply in comment.replies.filter(is_approved=True).select_related("user")
        ],
    }


def _mobile_article_category_payload(category):
    return {
        "id": category.id,
        "name": category.name,
        "slug": category.slug,
        "color": category.color,
        "post_count": getattr(category, "post_count", 0),
    }


def _mobile_article_request_customer(request, payload=None):
    if _auth_mobile_customer_from_request_data is None:
        raise PermissionError("Customer authentication is unavailable.")
    auth_data = dict(payload or {})
    authorization = str(request.headers.get("Authorization") or "")
    if authorization.lower().startswith("bearer ") and not auth_data.get("api_token"):
        auth_data["api_token"] = authorization.split(" ", 1)[1].strip()
    return _auth_mobile_customer_from_request_data(auth_data)


def _mobile_product_article_payload(request, article_link):
    article = getattr(article_link, "article", None)
    if not article:
        return None
    image = getattr(article, "display_image", None)
    category = getattr(article, "category", None)
    article_payload = {
        "id": article.id,
        "slug": article.slug,
        "title": translated_field(article, "title", request=request),
        "excerpt": translated_field(article, "excerpt", request=request, default=""),
        "content": translated_field(article, "content", request=request, default=""),
        "url": request.build_absolute_uri(article.get_absolute_url()),
        "image_url": _mobile_file_url(request, image, preset="blog_detail") if image else "",
        "thumbnail_url": _mobile_file_url(request, image, preset="blog_card") if image else "",
        "original_url": _mobile_original_file_url(request, image) if image else "",
        "gallery_images": article.gallery_images or [],
        "video_url": article.video_url or "",
        "category": (
            translated_field(category, "name", request=request)
            if category
            else ""
        ),
        "author": (
            article.author.get_full_name()
            or getattr(article.author, "username", "")
            or "Arolana"
        ),
        "reading_time": article.reading_time,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "seo": {
            "title": article.meta_title or article.title,
            "description": article.meta_description or article.excerpt,
            "keywords": article.meta_keywords or "",
        },
    }
    return {
        "id": article_link.id,
        "placement": article_link.placement,
        "sort_order": article_link.sort_order,
        "open_behavior": article_link.open_behavior,
        "label": translated_field(
            article_link,
            "label",
            request=request,
            default="",
        ) or article_payload["title"],
        "teaser": translated_field(
            article_link,
            "teaser",
            request=request,
            default="",
        ) or article_payload["excerpt"],
        "article": article_payload,
        **article_payload,
    }


@require_GET
def mobile_article_detail_api(request, slug):
    if BlogPost is None:
        return JsonResponse({"detail": "Articles are unavailable."}, status=503)

    article = get_object_or_404(
        BlogPost.objects.select_related("category", "author").prefetch_related("tags"),
        slug=slug,
        is_published=True,
    )
    prime_translations(
        request,
        [item for item in (article, article.category) if item],
    )
    BlogPost.objects.filter(pk=article.pk).update(views=F("views") + 1)

    image = article.display_image
    related_queryset = (
        BlogPost.objects.filter(is_published=True)
        .exclude(pk=article.pk)
        .select_related("category", "author")
    )
    if article.category_id:
        related_queryset = related_queryset.filter(category_id=article.category_id)
    related_articles = list(related_queryset.order_by("-published_at")[:4])
    popular_articles = list(
        BlogPost.objects.filter(is_published=True)
        .exclude(pk=article.pk)
        .select_related("category", "author")
        .order_by("-views", "-published_at")[:5]
    )
    categories = list(
        BlogCategory.objects.filter(is_active=True)
        .annotate(
            post_count=Count(
                "posts",
                filter=Q(posts__is_published=True),
                distinct=True,
            )
        )
        .order_by("-post_count", "name")
    ) if BlogCategory is not None else []
    comments = list(
        article.comments.filter(is_approved=True, parent=None)
        .select_related("user")
        .prefetch_related("replies__user")
    ) if BlogComment is not None else []
    prime_translations(
        request,
        [
            item
            for related in related_articles
            for item in (related, related.category)
            if item
        ],
    )

    author_name = (
        article.author.get_full_name()
        or getattr(article.author, "username", "")
        or "Arolana"
    )
    author_avatar = getattr(article.author, "avatar", None)
    share_url = request.build_absolute_uri(article.get_absolute_url())
    return JsonResponse({
        "ok": True,
        "article": {
            "id": article.id,
            "slug": article.slug,
            "title": translated_field(article, "title", request=request),
            "excerpt": translated_field(article, "excerpt", request=request, default=""),
            "content": translated_field(article, "content", request=request, default=""),
            "url": share_url,
            "share_url": share_url,
            "image_url": _mobile_file_url(request, image, preset="blog_detail") if image else "",
            "thumbnail_url": _mobile_file_url(request, image, preset="blog_card") if image else "",
            "original_url": _mobile_original_file_url(request, image) if image else "",
            "category": (
                translated_field(article.category, "name", request=request)
                if article.category
                else ""
            ),
            "category_slug": article.category.slug if article.category else "",
            "author": author_name,
            "author_details": {
                "id": article.author_id,
                "name": author_name,
                "role": "Staff Writer at Arolana",
                "avatar_url": (
                    _mobile_file_url(request, author_avatar, preset="avatar")
                    if author_avatar
                    else ""
                ),
            },
            "reading_time": article.reading_time,
            "published_at": article.published_at.isoformat() if article.published_at else None,
            "updated_at": article.updated_at.isoformat() if article.updated_at else None,
            "video_url": article.video_url or "",
            "video_embed_url": article.get_video_embed_url() or "",
            "local_video_url": article.local_video_url or "",
            "gallery_images": article.gallery_images or [],
            "tags": [
                {"id": tag.id, "name": tag.name, "slug": tag.slug}
                for tag in article.tags.all()
            ],
        },
        "related_articles": [
            _mobile_article_card_payload(request, related)
            for related in related_articles
        ],
        "popular_posts": [
            _mobile_article_card_payload(request, popular)
            for popular in popular_articles
        ],
        "categories": [
            _mobile_article_category_payload(category)
            for category in categories
        ],
        "comments": [
            _mobile_article_comment_payload(request, comment)
            for comment in comments
        ],
        "comment_count": sum(
            1 + len(comment.replies.all())
            for comment in comments
        ),
        "share_url": share_url,
    })


@csrf_exempt
@require_http_methods(["GET", "POST"])
def mobile_article_comments_api(request, slug):
    if BlogPost is None or BlogComment is None:
        return JsonResponse({"detail": "Article comments are unavailable."}, status=503)
    article = get_object_or_404(BlogPost, slug=slug, is_published=True)

    if request.method == "POST":
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except Exception:
            return JsonResponse({"success": False, "message": "Invalid JSON payload."}, status=400)
        try:
            customer = _mobile_article_request_customer(request, payload)
        except Exception as error:
            return JsonResponse(
                {
                    "success": False,
                    "login_required": True,
                    "message": str(error) or "Sign in to comment.",
                },
                status=401,
            )
        comment_text = str(payload.get("comment") or "").strip()
        if not comment_text:
            return JsonResponse(
                {"success": False, "message": "Please enter a comment."},
                status=400,
            )
        if len(comment_text) > 5000:
            return JsonResponse(
                {"success": False, "message": "Comment is too long."},
                status=400,
            )
        comment = BlogComment.objects.create(
            post=article,
            user=customer.user,
            comment=comment_text,
            is_approved=True,
        )
        return JsonResponse(
            {
                "success": True,
                "message": "Comment added successfully.",
                "comment": _mobile_article_comment_payload(request, comment),
            },
            status=201,
        )

    comments = list(
        article.comments.filter(is_approved=True, parent=None)
        .select_related("user")
        .prefetch_related("replies__user")
    )
    return JsonResponse(
        {
            "success": True,
            "comments": [
                _mobile_article_comment_payload(request, comment)
                for comment in comments
            ],
            "comment_count": sum(1 + len(comment.replies.all()) for comment in comments),
        }
    )


@require_GET
def mobile_article_categories_api(request):
    if BlogCategory is None:
        return JsonResponse({"categories": []})
    categories = (
        BlogCategory.objects.filter(is_active=True)
        .annotate(
            post_count=Count(
                "posts",
                filter=Q(posts__is_published=True),
                distinct=True,
            )
        )
        .order_by("-post_count", "name")
    )
    return JsonResponse({
        "categories": [
            _mobile_article_category_payload(category)
            for category in categories
        ]
    })


@require_GET
def mobile_articles_api(request):
    if BlogPost is None:
        return JsonResponse({"articles": []})
    category_slug = str(request.GET.get("category") or "").strip()
    tag_slug = str(request.GET.get("tag") or "").strip()
    search_query = str(request.GET.get("q") or "").strip()
    queryset = (
        BlogPost.objects.filter(is_published=True)
        .select_related("category", "author")
        .order_by("-published_at")
    )
    if category_slug:
        queryset = queryset.filter(category__slug=category_slug)
    if tag_slug:
        queryset = queryset.filter(tags__slug=tag_slug)
    if search_query:
        queryset = queryset.filter(
            Q(title__icontains=search_query)
            | Q(excerpt__icontains=search_query)
            | Q(content__icontains=search_query)
        )
    articles = list(queryset.distinct()[:50])
    return JsonResponse({
        "articles": [
            _mobile_article_card_payload(request, article)
            for article in articles
        ],
        "filters": {
            "category": category_slug,
            "tag": tag_slug,
            "query": search_query,
        },
    })


@require_GET
def mobile_article_tags_api(request):
    if BlogTag is None:
        return JsonResponse({"tags": []})
    tags = (
        BlogTag.objects.annotate(
            post_count=Count(
                "posts",
                filter=Q(posts__is_published=True),
                distinct=True,
            )
        )
        .filter(post_count__gt=0)
        .order_by("-post_count", "name")
    )
    return JsonResponse({
        "tags": [
            {
                "id": tag.id,
                "name": tag.name,
                "slug": tag.slug,
                "post_count": tag.post_count,
            }
            for tag in tags
        ]
    })


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
                .select_related("placement", "creative", "campaign", "linked_article")
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
        simple_ads = simple_ads.select_related("linked_article")
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
        "poster_image": _mobile_file_url(request, video.poster_image, preset="video_thumb"),
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

    category_name = (
        translated_field(category, "name", request=request)
        if category and hasattr(category, "name")
        else "Arolana"
    )
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
    vendor_name = getattr(product, "vendor_display_name", "") or (getattr(vendor_profile, "store_name", "") if vendor_profile else "")
    vendor_package = getattr(product, "vendor_package_name", "") or (getattr(vendor_profile, "active_plan_name", "") if vendor_profile else "")
    if vendor_profile:
        vendor_package = translated_key(
            f"subscription.plan.{getattr(vendor_profile, 'subscription_tier', 'free')}",
            vendor_package,
            request=request,
        )
    condition_value = getattr(product, "condition", "") or ""
    default_condition_label = (
        getattr(product, "condition_label", "")
        or condition_value.replace("_", " ").title()
    )
    condition_label = translated_key(
        translation_key_for_condition(condition_value),
        default_condition_label,
        request=request,
    )
    location_label = getattr(product, "location_label", "") or ""

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

    primary_image = _mobile_get_value(
        product,
        "image",
        "main_image",
        "thumbnail",
        "featured_image",
        "product_image",
        "cover_image",
        default=None,
    )
    thumbnail_url = _mobile_file_url(request, primary_image, preset="product_card")
    image_url = _mobile_file_url(request, primary_image, preset="product_detail")
    original_url = _mobile_original_file_url(request, primary_image)

    approved_offers = _mobile_product_approved_offers(product)
    default_offer = _mobile_default_vendor_offer(approved_offers)
    default_offer_payload = _mobile_vendor_offer_payload(request, default_offer) if default_offer else None
    if default_offer:
        price = default_offer.final_price
        regular_price = default_offer.price

    return {
        "id": product.id,
        "name": translated_field(
            product,
            "name",
            request=request,
            default=_mobile_get_value(
                product,
                "name",
                "title",
                "product_name",
                default="Unnamed product",
            ),
        ),
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
        "condition": condition_label,
        "condition_label": condition_label,
        "condition_value": condition_value,
        "product_condition": condition_value,
        "sku": getattr(product, "sku", "") or "",
        "arolana_sku": getattr(product, "sku", "") or "",
        "stock_quantity": getattr(product, "stock_quantity", 0) or 0,
        "available_stock": default_offer.available_stock if default_offer else (getattr(product, "stock_quantity", 0) or 0),
        "in_stock": bool(default_offer.is_available if default_offer else (getattr(product, "stock_quantity", 0) or getattr(product, "is_in_stock", False))),
        "is_featured": bool(getattr(product, "is_featured", False)),
        "is_new": bool(getattr(product, "is_new", False)),
        "is_bestseller": bool(getattr(product, "is_bestseller", False)),
        "rating": str(rating or 0),
        "rating_count": getattr(product, "rating_count", 0) or 0,
        "image": thumbnail_url,
        "thumbnail_url": thumbnail_url,
        "image_url": image_url,
        "original_url": original_url,
        "url": request.build_absolute_uri(reverse("products:detail", args=[product.slug])),
        "vendor_id": getattr(vendor_profile, "id", None),
        "vendor_user_id": getattr(vendor_user, "id", None),
        "vendor_name": vendor_name,
        "vendor_package": vendor_package,
        "vendor_package_name": vendor_package,
        "vendor_type": vendor_type,
        "vendor_type_display": vendor_type_display,
        "vendor_verified": vendor_verified,
        "location": location_label,
        "location_label": location_label,
        "manufacturer_verified": manufacturer_verified,
        "subscription_tier": getattr(vendor_profile, "subscription_tier", "free") if vendor_profile else "free",
        "subscription_label": subscription_badge,
        "subscription_badge": subscription_badge,
        "badges": badges,
        "wholesale_available": bool(wholesale_price or bulk_price),
        "rfq_available": bool(vendor_profile),
        "vendor_offer_id": default_offer.id if default_offer else None,
        "default_vendor_offer": default_offer_payload,
        "vendor_offers": [
            _mobile_vendor_offer_payload(request, offer)
            for offer in approved_offers[:6]
        ],
    }


def _mobile_product_approved_offers(product):
    prefetched = getattr(product, "approved_mobile_vendor_offers", None)
    if prefetched is not None:
        return list(prefetched)
    try:
        return list(
            product.vendor_offers.filter(
                is_active=True,
                approval_status=VendorProductOffer.STATUS_APPROVED,
            )
            .select_related("vendor", "variant")
            .order_by("-is_preferred", "-is_featured", "sale_price", "price", "-created_at")[:12]
        )
    except Exception:
        return []


def _mobile_default_vendor_offer(offers):
    if not offers:
        return None
    available = [offer for offer in offers if offer.is_available]
    return (available or offers)[0]


def _mobile_vendor_offer_payload(request, offer):
    if not offer:
        return None
    vendor = getattr(offer, "vendor", None)
    variant = getattr(offer, "variant", None)
    return {
        "id": offer.id,
        "vendor_offer_id": offer.id,
        "product_id": offer.product_id,
        "variant_id": offer.variant_id,
        "variant_name": getattr(variant, "display_name", "") if variant else "",
        "seller_sku": offer.seller_sku,
        "price": str(offer.final_price),
        "base_price": str(offer.price),
        "sale_price": str(offer.sale_price or ""),
        "currency": offer.currency,
        "stock_quantity": offer.stock_quantity,
        "available_stock": offer.available_stock,
        "in_stock": offer.is_available,
        "condition": offer.get_condition_display(),
        "condition_value": offer.condition,
        "vendor_id": offer.vendor_id,
        "vendor_name": offer.vendor_display_name,
        "vendor_verified": bool(getattr(vendor, "is_verified", False)) if vendor else False,
        "vendor_package": getattr(vendor, "active_plan_name", "") if vendor else "",
        "seller_warranty": offer.seller_warranty,
        "return_policy": offer.return_policy,
        "delivery_note": offer.delivery_note,
        "lead_time_days": offer.lead_time_days,
        "fulfilment_method": offer.fulfilment_method,
        "fulfilment_label": offer.get_fulfilment_method_display(),
        "is_featured": offer.is_featured,
        "is_preferred": offer.is_preferred,
        "add_to_cart_payload": {
            "product_id": offer.product_id,
            "variant_id": offer.variant_id,
            "vendor_offer_id": offer.id,
        },
    }


def _mobile_variant_payload(request, variant, product=None):
    product = product or getattr(variant, "product", None)
    variant_image = _mobile_file_url(request, getattr(variant, "image", None), preset="product_gallery")
    hover_image = _mobile_file_url(request, getattr(variant, "hover_image", None), preset="product_gallery")
    variant_images = []
    if variant_image:
        variant_images.append(variant_image)
    for gallery_image in variant.images.filter(is_active=True):
        gallery_url = _mobile_file_url(request, getattr(gallery_image, "image", None), preset="product_gallery")
        if gallery_url and gallery_url not in variant_images:
            variant_images.append(gallery_url)
    offers = list(
        variant.vendor_offers.filter(
            is_active=True,
            approval_status=VendorProductOffer.STATUS_APPROVED,
        )
        .select_related("vendor")
        .order_by("-is_preferred", "-is_featured", "sale_price", "price", "-created_at")[:8]
    )
    return {
        "id": variant.id,
        "slug": getattr(variant, "slug", "") or "",
        "name": getattr(variant, "name", "") or "",
        "display_name": getattr(variant, "display_name", "") or str(variant),
        "value": getattr(variant, "value", "") or "",
        "variant_type": getattr(variant, "variant_type", "") or "",
        "variant_mode": getattr(variant, "variant_mode", ProductVariant.VARIANT_MODE_SIMPLE),
        "selector_type": getattr(variant, "selector_type", ProductVariant.SELECTOR_TEXT),
        "sku": getattr(variant, "sku", "") or "",
        "model_number": getattr(variant, "model_number", "") or "",
        "manufacturer_sku": getattr(variant, "manufacturer_sku", "") or "",
        "gtin": getattr(variant, "gtin", "") or "",
        "upc": getattr(variant, "upc", "") or "",
        "ean": getattr(variant, "ean", "") or "",
        "barcode": getattr(variant, "barcode", "") or "",
        "final_price": str(getattr(variant, "final_price", getattr(product, "price", ""))),
        "price_adjustment": str(getattr(variant, "price_adjustment", "0")),
        "stock_quantity": getattr(variant, "stock_quantity", 0) or 0,
        "color_code": getattr(variant, "color_code", "") or "",
        "short_description": getattr(variant, "short_description", "") or "",
        "description": getattr(variant, "description", "") or "",
        "specifications": getattr(variant, "specifications", "") or "",
        "key_features": getattr(variant, "key_features", []) or [],
        "compatibility_notes": getattr(variant, "compatibility_notes", "") or "",
        "included_accessories": getattr(variant, "included_accessories", "") or "",
        "recommended_use": getattr(variant, "recommended_use", "") or "",
        "warranty_years": getattr(variant, "warranty_years", 0) or 0,
        "warranty_description": getattr(variant, "warranty_description", "") or "",
        "extended_warranty_available": bool(getattr(variant, "extended_warranty_available", False)),
        "is_default": bool(getattr(variant, "is_default", False)),
        "display_order": getattr(variant, "display_order", 0) or 0,
        "image": variant_image,
        "image_url": variant_image,
        "hover_image_url": hover_image,
        "thumbnail_url": variant_image,
        "original_url": _mobile_original_file_url(request, getattr(variant, "image", None)),
        "images": variant_images,
        "structured_specs": [
            {
                "group": spec.group,
                "name": spec.name,
                "value": spec.value,
                "unit": spec.unit,
                "is_highlight": spec.is_highlight,
                "display_order": spec.display_order,
            }
            for spec in variant.structured_specs.filter(is_active=True).order_by("display_order", "group", "name")
        ],
        "vendor_offers": [_mobile_vendor_offer_payload(request, offer) for offer in offers],
        "default_vendor_offer": _mobile_vendor_offer_payload(request, _mobile_default_vendor_offer(offers)) if offers else None,
    }


@require_GET
def mobile_home_api(request):
    from installers.models import ServiceMarketplaceHomepageSection, ServicePortfolio
    from installers.serializers import ServicePortfolioSerializer

    product_queryset = Product.objects.filter(
        is_active=True,
        approval_status="approved",
    ).select_related(
        "category",
        "brand",
        "vendor",
        "vendor__vendor_profile",
    )
    product_queryset = list(
        order_storefront_products(
            product_queryset,
            "-is_featured",
            "-sales_count",
            "-created_at",
        )[:48]
    )
    prime_translations(
        request,
        [
            item
            for product in product_queryset
            for item in (product, getattr(product, "category", None))
            if item
        ],
    )

    hero_banner_payloads = []
    if HeroBanner:
        hero_banners = (
            HeroBanner.objects.filter(is_active=True)
            .select_related("linked_article")
            .order_by("display_order", "-created_at")[:8]
        )
        for banner in hero_banners:
            linked_article = banner.linked_article
            linked_article_url = (
                request.build_absolute_uri(linked_article.get_absolute_url())
                if linked_article
                else ""
            )
            hero_banner_payloads.append({
                "id": banner.id,
                "title": translated_field(banner, "title", request=request),
                "subtitle": translated_field(banner, "subtitle", request=request),
                "description": translated_field(banner, "description", request=request),
                "show_content": banner.show_content,
                "show_title": banner.show_title,
                "show_subtitle": banner.show_subtitle,
                "show_description": banner.show_description,
                "show_button": banner.show_buttons,
                "button_text": translated_field(banner, "button1_text", request=request),
                "button_url": banner.button1_url,
                "button1_text": translated_field(banner, "button1_text", request=request),
                "button1_url": banner.button1_url,
                "button2_text": translated_field(banner, "button2_text", request=request),
                "button2_url": banner.button2_url,
                "button3_text": translated_field(banner, "button3_text", request=request),
                "button3_url": banner.button3_url,
                "effective_slide_link_url": banner.effective_slide_link_url,
                "slide_link_url": banner.slide_link_url,
                "enable_slide_link": banner.enable_slide_link,
                "linked_article_id": linked_article.id if linked_article else None,
                "linked_article_slug": linked_article.slug if linked_article else "",
                "linked_article_title": (
                    translated_field(linked_article, "title", request=request)
                    if linked_article
                    else ""
                ),
                "linked_article_url": linked_article_url,
                "article_url": linked_article_url,
                "article_button_text": translated_field(
                    banner,
                    "article_button_text",
                    request=request,
                ),
                "article_open_behavior": banner.article_open_behavior,
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
                "image_mobile": _mobile_file_url(request, banner.image_mobile, preset="hero_banner"),
                "image_tablet": _mobile_file_url(request, banner.image_tablet, preset="hero_banner"),
                "image_desktop": _mobile_file_url(request, banner.image_desktop, preset="hero_banner"),
                "image": _mobile_file_url(
                    request,
                    banner.image_mobile or banner.image_tablet or banner.image_desktop,
                    preset="hero_banner",
                ),
                "hero_title": translated_field(banner, "title", request=request),
                "hero_subtitle": translated_field(banner, "subtitle", request=request),
                "hero_cta_text": translated_field(banner, "button1_text", request=request),
                "hero_cta_url": banner.button1_url,
                "hero_mobile_image_url": _mobile_file_url(request, banner.image_mobile, preset="hero_banner"),
                "hero_image_url": _mobile_file_url(
                    request,
                    banner.image_desktop or banner.image_tablet or banner.image_mobile,
                    preset="hero_banner",
                ),
                "hero_background_url": _mobile_file_url(
                    request,
                    banner.image_mobile or banner.image_desktop or banner.image_tablet,
                    preset="hero_banner",
                ),
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
                "title": translated_field(banner, "title", request=request),
                "subtitle": translated_field(banner, "subtitle", request=request),
                "button_text": translated_field(banner, "button_text", request=request),
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
                "image": _mobile_file_url(request, image.image, preset="ad_card") if image else None,
                "background_image": _mobile_file_url(request, background.image, preset="hero_banner") if background else None,
                "center_image_upload": _mobile_file_url(request, center.image, preset="hero") if center else None,
                "left_image_upload": _mobile_file_url(request, left.image, preset="category_card") if left else None,
                "right_image_upload": _mobile_file_url(request, right.image, preset="category_card") if right else None,
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
            "desktop_background_image": _mobile_file_url(request, appearance.desktop_background_image, preset="background_desktop"),
            "mobile_background_image": _mobile_file_url(request, appearance.mobile_background_image, preset="background_mobile"),
            "image": _mobile_file_url(
                request,
                appearance.mobile_background_image or appearance.desktop_background_image,
                preset="background_mobile" if appearance.mobile_background_image else "background_desktop",
            ),
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
            .order_by("display_order", "id")[:80]
        )
        category_payloads = [
            _mobile_category_payload(request, item.category)
            for item in homepage_categories
            if item.category
        ]

    if not category_payloads:
        roots = Category.objects.filter(is_active=True, parent=None).order_by("name")[:80]
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
    project_home_section = ServiceMarketplaceHomepageSection.objects.filter(
        is_active=True,
        projects_enabled=True,
    ).first()
    mobile_projects = []
    if project_home_section:
        project_queryset = (
            ServicePortfolio.objects.public()
            .optimized()
            .order_by("-is_featured", "-published_at")[: max(1, min(project_home_section.projects_limit, 16))]
        )
        mobile_projects = ServicePortfolioSerializer(
            project_queryset,
            many=True,
            context={"request": request},
        ).data

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
        "projects_section": {
            "enabled": bool(project_home_section),
            "eyebrow": project_home_section.projects_eyebrow if project_home_section else "",
            "title": project_home_section.projects_title if project_home_section else "",
            "subtitle": project_home_section.projects_subtitle if project_home_section else "",
            "button_text": project_home_section.projects_button_text if project_home_section else "",
            "projects": mobile_projects,
        },
        "featured_projects": mobile_projects,
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
    category_articles = [
        _mobile_category_article_payload(request, link)
        for link in CategoryArticleLink.objects.filter(
            category=category,
            is_active=True,
            article__is_published=True,
        ).select_related("article").order_by("sort_order", "-article__published_at")[:12]
    ]
    category_articles = [item for item in category_articles if item]

    return JsonResponse({
        "success": True,
        "category": category_payload,
        "breadcrumbs": [
            {
                "name": translated_field(ancestor, "name", request=request),
                "slug": ancestor.slug,
            }
            for ancestor in category.get_ancestors()
        ] + [{
            "name": translated_field(category, "name", request=request),
            "slug": category.slug,
        }],
        "subcategories": category_payload.get("children", []),
        "articles": category_articles,
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

    product_items = list(products[:120])
    prime_translations(
        request,
        [
            item
            for product in product_items
            for item in (product, getattr(product, "category", None))
            if item
        ],
    )
    data = [_mobile_product_payload(request, product) for product in product_items]

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
    """
    Create or update a mobile customer product review.

    Supports JSON for text reviews and multipart/form-data for optional
    video_review uploads.
    """
    if _auth_mobile_customer_from_request_data is None:
        return JsonResponse(
            {
                "success": False,
                "message": "Mobile customer app is not available.",
            },
            status=500,
        )

    content_type = str(request.content_type or "").lower()

    if content_type.startswith("multipart/form-data"):
        payload = request.POST.dict()
    else:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse(
                {
                    "success": False,
                    "message": "Invalid JSON payload.",
                },
                status=400,
            )

        if not isinstance(payload, dict):
            return JsonResponse(
                {
                    "success": False,
                    "message": "Invalid request payload.",
                },
                status=400,
            )

    try:
        customer = _mobile_authenticated_customer(
            request,
            payload,
        )

    except PermissionError as error:
        return JsonResponse(
            {
                "success": False,
                "message": str(error),
            },
            status=403,
        )

    except ValueError as error:
        return JsonResponse(
            {
                "success": False,
                "message": str(error),
            },
            status=400,
        )

    product = get_object_or_404(
        Product,
        slug=slug,
        is_active=True,
        approval_status="approved",
    )

    user = getattr(customer, "user", None)

    if not user:
        return JsonResponse(
            {
                "success": False,
                "message": "Customer account is not linked to a user yet.",
            },
            status=400,
        )

    try:
        rating = int(payload.get("rating") or 5)
    except (TypeError, ValueError):
        return JsonResponse(
            {
                "success": False,
                "message": "Rating must be between 1 and 5.",
            },
            status=400,
        )

    if rating not in {1, 2, 3, 4, 5}:
        return JsonResponse(
            {
                "success": False,
                "message": "Rating must be between 1 and 5.",
            },
            status=400,
        )

    title = str(payload.get("title") or "").strip()
    review_text = str(
        payload.get("review")
        or payload.get("message")
        or ""
    ).strip()

    if len(title) < 3:
        return JsonResponse(
            {
                "success": False,
                "message": "Please add a short review title.",
            },
            status=400,
        )

    if len(title) > 200:
        return JsonResponse(
            {
                "success": False,
                "message": "Review title cannot exceed 200 characters.",
            },
            status=400,
        )

    if len(review_text) < 10:
        return JsonResponse(
            {
                "success": False,
                "message": "Please write a little more about the product.",
            },
            status=400,
        )

    uploaded_video = request.FILES.get("video_review")

    review = (
        ProductReview.objects
        .select_for_update()
        .filter(
            product=product,
            user=user,
        )
        .first()
    )

    created = review is None

    if review is None:
        review = ProductReview(
            product=product,
            user=user,
            verified_purchase=False,
        )

    review.rating = rating
    review.title = title
    review.review = review_text

    if uploaded_video:
        if review.pk and review.video_review:
            return JsonResponse(
                {
                    "success": False,
                    "message": (
                        "The original review video cannot be replaced. "
                        "Please contact Arolana support if the original "
                        "upload was incorrect."
                    ),
                },
                status=400,
            )

        review.video_review = uploaded_video

    try:
        review.full_clean()
        review.save()

    except ValidationError as error:
        return JsonResponse(
            {
                "success": False,
                "message": _first_validation_error(
                    error,
                    default="The review could not be saved.",
                ),
            },
            status=400,
        )

    except IntegrityError:
        transaction.set_rollback(True)

        return JsonResponse(
            {
                "success": False,
                "message": (
                    "A review for this product already exists. "
                    "Refresh the product page and try again."
                ),
            },
            status=409,
        )

    _refresh_product_review_stats(product.id)

    review_video_payloads = _review_video_payloads(
        request,
        review,
    )

    return JsonResponse(
        {
            "success": True,
            "created": created,
            "message": (
                "Review submitted successfully."
                if created
                else "Review updated successfully."
            ),
            "review": {
                "id": review.pk,
                "rating": review.rating,
                "title": review.title,
                "review": review.review,

                "customer_name": (
                    getattr(
                        customer,
                        "full_name",
                        "",
                    )
                    or user.get_full_name()
                    or user.username
                    or user.email
                    or "Arolana customer"
                ),

                "verified_purchase": bool(
                    review.verified_purchase
                ),

                "helpful_count": int(
                    review.helpful_count
                    or 0
                ),

                "unhelpful_count": int(
                    review.unhelpful_count
                    or 0
                ),

                "has_video": bool(
                    review_video_payloads
                ),

                "video_url": (
                    review_video_payloads[0]["url"]
                    if review_video_payloads
                    else ""
                ),

                "videos": review_video_payloads,
                "review_videos": (
                    review_video_payloads
                ),

                "created_at": (
                    review.created_at.isoformat()
                    if review.created_at
                    else ""
                ),

                "updated_at": (
                    review.updated_at.isoformat()
                    if review.updated_at
                    else ""
                ),
            },
        },
        status=201 if created else 200,
    )


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
        customer = _mobile_authenticated_customer(
            request,
            payload,
        )
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

    qna = ProductQuestion(
        product=product,
        user=user,
        question=question_text,
        is_public=True,
    )

    qna.full_clean()
    qna.save()

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
        Product.objects.select_related(
            "category",
            "brand",
            "vendor",
            "vendor__vendor_profile",
            "manufacturer_warranty",
            "shipping_info",
                ).prefetch_related(
                    "images",
                    "variants",
                    "variants__images",
                    "variants__structured_specs",
                    "variants__vendor_offers",
                    "vendor_offers",
        
                    Prefetch(
                        "reviews",
                        queryset=(
                            ProductReview.objects
                            .select_related("user")
                            .prefetch_related(
                                Prefetch(
                                    "review_videos",
                                    queryset=(
                                        ReviewVideo.objects
                                        .order_by(
                                            "-is_main",
                                            "-created_at",
                                            "-id",
                                        )
                                    ),
                                    to_attr="visible_review_videos",
                                )
                            )
                            .order_by("-created_at")
                        ),
                        to_attr="mobile_visible_reviews",
                    ),
        
                    "questions__user",
                    "additional_videos",
                    "wholesale_tiers",
                    "product_accessories__accessory",
        
                    Prefetch(
                        "article_links",
                        queryset=ProductArticleLink.objects.filter(
                            is_active=True,
                            article__is_published=True,
                        ).select_related(
                            "article",
                            "article__category",
                            "article__author",
                        ),
                        to_attr="mobile_article_links",
                    ),
                ),
        slug=slug,
        is_active=True,
        approval_status="approved",
    )

    def safe_url(file_field, preset=None):
        return _mobile_file_url(request, file_field, preset=preset)

    images = []
    gallery = []

    main_image = safe_url(getattr(product, "main_image", None), "product_detail")
    main_thumbnail = safe_url(getattr(product, "main_image", None), "product_card")
    main_gallery_image = safe_url(getattr(product, "main_image", None), "product_gallery")
    main_original = _mobile_original_file_url(request, getattr(product, "main_image", None))
    if main_image:
        images.append(main_image)
        gallery.append({
            "image_url": main_gallery_image or main_image,
            "thumbnail_url": main_gallery_image or main_thumbnail or main_image,
            "detail_url": main_image,
            "original_url": main_original,
            "is_main": True,
        })

    for image in product.images.all():
        image_url = safe_url(getattr(image, "image", None), "product_gallery")
        if image_url and image_url not in images:
            images.append(image_url)
            gallery.append({
                "id": image.id,
                "image_url": image_url,
                "thumbnail_url": image_url,
                "original_url": _mobile_original_file_url(request, getattr(image, "image", None)),
                "is_main": bool(getattr(image, "is_main", False)),
            })

    variants = [
        _mobile_variant_payload(request, variant, product=product)
        for variant in product.variants.filter(is_active=True).order_by("display_order", "variant_type", "name", "value")
    ]

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
            mobile_customer = _mobile_authenticated_customer(
                request,
                request.GET,
            )
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

    mobile_visible_reviews = list(
        getattr(
            product,
            "mobile_visible_reviews",
            [],
        )
    )[:8]

    for review in mobile_visible_reviews:
        user = getattr(
            review,
            "user",
            None,
        )

        review_videos = (
            _review_video_payloads(
                request,
                review,
            )
        )

        customer_name = (
            user.get_full_name()
            if user
            else ""
        )

        if not customer_name and user:
            customer_name = (
                getattr(
                    user,
                    "username",
                    "",
                )
                or getattr(
                    user,
                    "email",
                    "",
                )
            )

        reviews.append({
            "id": review.pk,

            "rating": int(
                getattr(
                    review,
                    "rating",
                    0,
                )
                or 0
            ),

            "title": (
                getattr(
                    review,
                    "title",
                    "",
                )
                or ""
            ),

            "review": (
                getattr(
                    review,
                    "review",
                    "",
                )
                or ""
            ),

            "customer_name": (
                customer_name
                or "Arolana customer"
            ),

            "verified_purchase": bool(
                getattr(
                    review,
                    "verified_purchase",
                    False,
                )
            ),

            "helpful_count": int(
                getattr(
                    review,
                    "helpful_count",
                    0,
                )
                or 0
            ),

            "unhelpful_count": int(
                getattr(
                    review,
                    "unhelpful_count",
                    0,
                )
                or 0
            ),

            "has_video": bool(
                review_videos
            ),

            # Backward compatibility for the current app.
            "video_url": (
                review_videos[0]["url"]
                if review_videos
                else ""
            ),

            # Complete new video collection.
            "videos": review_videos,
            "review_videos": review_videos,

            "created_at": (
                review.created_at.isoformat()
                if getattr(
                    review,
                    "created_at",
                    None,
                )
                else ""
            ),

            "updated_at": (
                review.updated_at.isoformat()
                if getattr(
                    review,
                    "updated_at",
                    None,
                )
                else ""
            ),
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
    try:
        manufacturer_warranty = product.manufacturer_warranty
    except ManufacturerWarranty.DoesNotExist:
        manufacturer_warranty = None
    warranty_info = {
        "years": getattr(product, "warranty_years", 0) or 0,
        "description": getattr(product, "warranty_description", "") or "",
        "extended_available": bool(getattr(product, "extended_warranty_available", False)),
        "extended_price": str(getattr(product, "extended_warranty_price", "") or ""),
        "provider": getattr(manufacturer_warranty, "provider", "") if manufacturer_warranty else "",
        "duration": manufacturer_warranty.duration_text() if manufacturer_warranty else (
            f"{product.warranty_years} year{'s' if product.warranty_years != 1 else ''}"
            if getattr(product, "warranty_years", 0)
            else ""
        ),
        "coverage": getattr(manufacturer_warranty, "coverage_details", "") if manufacturer_warranty else (
            getattr(product, "warranty_description", "") or ""
        ),
        "exclusions": getattr(manufacturer_warranty, "exclusions", "") if manufacturer_warranty else "",
        "terms_url": getattr(manufacturer_warranty, "terms_url", "") if manufacturer_warranty else "",
        "registration_required": bool(getattr(manufacturer_warranty, "registration_required", False)) if manufacturer_warranty else False,
        "registration_url": getattr(manufacturer_warranty, "registration_url", "") if manufacturer_warranty else "",
        "support_phone": getattr(manufacturer_warranty, "customer_support_phone", "") if manufacturer_warranty else "",
        "support_email": getattr(manufacturer_warranty, "customer_support_email", "") if manufacturer_warranty else "",
        "vendor_note": getattr(vendor_profile, "warranty_note", "") if vendor_profile else "",
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
            "image": safe_url(getattr(accessory, "image", None), "product_card"),
            "thumbnail_url": safe_url(getattr(accessory, "image", None), "product_card"),
            "image_url": safe_url(getattr(accessory, "image", None), "product_detail"),
            "original_url": _mobile_original_file_url(request, getattr(accessory, "image", None)),
            "required": accessory_link.required,
            "discount_when_bought_together": str(accessory_link.discount_when_bought_together),
        })

    product_articles = [
        payload
        for payload in (
            _mobile_product_article_payload(request, article_link)
            for article_link in getattr(product, "mobile_article_links", [])
        )
        if payload
    ]
    product_article = product_articles[0] if product_articles else None

    vendor_url = ""
    if vendor_profile:
        try:
            vendor_url = request.build_absolute_uri(vendor_profile.get_absolute_url())
        except Exception:
            vendor_url = ""
    vendor_contact_options = _vendor_contact_options(vendor_profile, product=product, request=request)
    condition_value = getattr(product, "condition", "") or ""
    default_condition_label = (
        getattr(product, "condition_label", "")
        or condition_value.replace("_", " ").title()
    )
    condition_label = translated_key(
        translation_key_for_condition(condition_value),
        default_condition_label,
        request=request,
    )
    vendor_name = getattr(product, "vendor_display_name", "") or (getattr(vendor_profile, "store_name", "") if vendor_profile else "")
    vendor_package = getattr(product, "vendor_package_name", "") or (getattr(vendor_profile, "active_plan_name", "") if vendor_profile else "")
    if vendor_profile:
        vendor_package = translated_key(
            f"subscription.plan.{getattr(vendor_profile, 'subscription_tier', 'free')}",
            vendor_package,
            request=request,
        )
    location_label = getattr(product, "location_label", "") or ""
    # Description images remain inside description_html in their authored
    # positions. Gallery images are returned only by the gallery/images fields.
    description_images = []

    chat_url = ""
    if vendor:
        try:
            chat_url = request.build_absolute_uri(reverse("chat:start_vendor_product", args=[vendor.id, product.id]))
        except Exception:
            chat_url = ""

    approved_offers = _mobile_product_approved_offers(product)
    default_offer = _mobile_default_vendor_offer(approved_offers)
    default_offer_payload = _mobile_vendor_offer_payload(request, default_offer) if default_offer else None

    try:
        from installers.serializers import ServiceCategorySerializer, ServiceProviderListSerializer
        from installers.services import suggested_categories_for_product, suggested_providers_for_product

        related_service_categories = suggested_categories_for_product(product)
        suggested_service_providers = list(suggested_providers_for_product(product))
        related_service_category_data = ServiceCategorySerializer(
            related_service_categories,
            many=True,
            context={"request": request},
        ).data
        suggested_service_provider_data = ServiceProviderListSerializer(
            suggested_service_providers,
            many=True,
            context={"request": request},
        ).data
    except Exception:
        related_service_category_data = []
        suggested_service_provider_data = []

    return JsonResponse({
        "id": product.id,
        "name": translated_field(product, "name", request=request),
        "slug": product.slug,
        "sku": product.sku,
        "arolana_sku": product.sku,
        "manufacturer_sku": getattr(product, "manufacturer_sku", ""),
        "condition": condition_label,
        "condition_label": condition_label,
        "condition_value": condition_value,
        "product_condition": condition_value,
        "price": str(product.price),
        "offer_price": str(default_offer.final_price) if default_offer else str(product.price),
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
        "product_article": product_article,
        "product_articles": product_articles,
        "rfq_available": bool(vendor_profile),
        "badges": _mobile_product_payload(request, product).get("badges", []),
        "description": translated_field(product, "description", request=request, default="") or "",
        "description_html": translated_field(product, "description", request=request, default="") or "",
        "description_images": description_images,
        "overview_gallery": description_images,
        "short_description": translated_field(product, "short_description", request=request, default="") or "",
        "specifications": translated_field(product, "specifications", request=request, default="") or "",
        "specifications_text": strip_tags(
            translated_field(product, "specifications", request=request, default="") or ""
        ),
        "category_name": translated_field(category, "name", request=request) if category else "Arolana",
        "brand_name": brand.name if brand else "",
        "vendor_name": vendor_name,
        "vendor_verified": getattr(product, "vendor_verified", False),
        "vendor_package": vendor_package,
        "vendor_package_name": vendor_package,
        "location": location_label,
        "location_label": location_label,
        "stock_quantity": getattr(product, "stock_quantity", 0),
        "available_stock": default_offer.available_stock if default_offer else getattr(product, "stock_quantity", 0),
        "vendor_offer_id": default_offer.id if default_offer else None,
        "default_vendor_offer": default_offer_payload,
        "vendor_offers": [
            _mobile_vendor_offer_payload(request, offer)
            for offer in approved_offers
        ],
        "rating_avg": str(getattr(product, "rating_avg", "0") or "0"),
        "rating_count": getattr(product, "rating_count", 0),
        "manual_pdf": safe_url(getattr(product, "manual_pdf", None)),
        "delivery_info": delivery_info,
        "warranty": warranty_info,
        "warranty_info": warranty_info,
        "vendor": {
            **(_mobile_vendor_payload(request, vendor_profile) or {
                "id": vendor.id if vendor else None,
                "name": getattr(vendor, "get_full_name", lambda: "")() or getattr(vendor, "email", "Arolana vendor"),
            }),
            "chat_available": vendor_contact_options.get("can_chat", vendor_chat_available),
            "vendor_contact_options": vendor_contact_options,
            "chat_url": chat_url,
            "url": vendor_url,
        },
        "vendor_contact_options": vendor_contact_options,
        "image": main_image,
        "main_image_url": main_image,
        "thumbnail_url": main_thumbnail,
        "image_url": main_image,
        "original_url": main_original,
        "images": images,
        "gallery": gallery,
        "variants": variants,
        "videos": videos,
        "reviews": reviews,
        "questions": questions,
        "recommended_products": [product_card(item) for item in recommended],
        "frequently_bought": [product_card(item) for item in frequently_bought],
        "supplier_products": [product_card(item) for item in supplier_products],
        "recently_viewed": [product_card(item) for item in recently_viewed],
        "service_available": bool(related_service_category_data),
        "related_service_categories": related_service_category_data,
        "suggested_service_providers": suggested_service_provider_data,
        "request_service_quote_endpoint": request.build_absolute_uri("/api/installers/quote-request/"),
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


def _mobile_customer_from_payload(request, payload=None):
    """
    Backward-compatible request-aware mobile authentication wrapper.

    Bearer authentication is preferred. The legacy api_token payload bridge
    remains available while older app builds are being phased out.
    """
    return _mobile_authenticated_customer(
        request,
        payload,
    )


def _get_vendor_and_product_from_payload(payload):
    vendor_profile = None
    product = None
    product_id = payload.get("product_id")
    vendor_id = payload.get("vendor_id")
    if product_id:
        product = Product.objects.select_related("vendor", "vendor__vendor_profile").filter(id=product_id, is_active=True).first()
        if product and getattr(product, "vendor", None):
            vendor_profile = getattr(product.vendor, "vendor_profile", None)
    if not vendor_profile and vendor_id and VendorProfile is not None:
        vendor_profile = VendorProfile.objects.select_related("user").filter(id=vendor_id).first()
    return vendor_profile, product


def _provided(value):
    value = str(value or "").strip()
    return value or "Not provided"


def _notify_vendor_callback_request(request, callback, vendor_profile, product, payload):
    if Notification is None or not vendor_profile:
        return
    product_name = getattr(product, "name", "") or "Not provided"
    product_url = _product_absolute_url(request, product) or "Not provided"
    customer_name = _provided(callback.customer_name)
    customer_phone = _provided(callback.customer_phone)
    customer_email = _provided(callback.customer_email)
    customer_message = _provided(callback.message)
    created_at = callback.created_at.strftime("%d %b %Y %I:%M %p") if getattr(callback, "created_at", None) else "Not provided"

    vendor_message = (
        "A customer requested a callback for one of your products on Arolana.\n\n"
        f"Product: {product_name}\n"
        f"Product Link: {product_url}\n"
        f"Customer Name: {customer_name}\n"
        f"Customer Phone: {customer_phone}\n"
        f"Customer Email: {customer_email}\n"
        f"Message: {customer_message}\n\n"
        "Please contact the customer professionally and encourage them to complete payment and order tracking through Arolana for safety.\n\n"
        "For trust and fraud prevention, this contact request has also been logged for Arolana admin review."
    )
    Notification.send(
        user=vendor_profile.user,
        notification_type="vendor",
        title="New Callback Request",
        message=vendor_message,
        link=product_url if product_url != "Not provided" else "",
        metadata={
            "callback_request_id": callback.id,
            "vendor_id": vendor_profile.id,
            "product_id": getattr(product, "id", None),
            "product_url": product_url,
            "action_type": "callback_request",
            "source": payload.get("source") or "web",
        },
        priority=3,
    )

    admin_message = (
        "A customer requested a callback from a vendor.\n\n"
        f"Vendor: {vendor_profile.store_name}\n"
        f"Product: {product_name}\n"
        f"Product Link: {product_url}\n"
        f"Customer: {customer_name}\n"
        f"Customer Phone: {customer_phone}\n"
        "Action Type: Callback Request\n"
        f"Date/Time: {created_at}\n\n"
        "This request has been logged for platform safety, fraud prevention, and dispute investigation if needed."
    )
    admin_users = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True), is_active=True).distinct()[:30]
    for admin_user in admin_users:
        Notification.send(
            user=admin_user,
            notification_type="security",
            title="Vendor Callback Request Logged",
            message=admin_message,
            link=product_url if product_url != "Not provided" else "",
            metadata={
                "callback_request_id": callback.id,
                "vendor_id": vendor_profile.id,
                "product_id": getattr(product, "id", None),
                "product_url": product_url,
                "action_type": "callback_request",
                "source": payload.get("source") or "web",
            },
            priority=3,
        )


@csrf_exempt
@require_http_methods(["POST"])
def mobile_vendor_request_callback_api(request):
    if VendorProfile is None or VendorCallbackRequest is None:
        return JsonResponse({"success": False, "message": "Vendor contact system is not available."}, status=500)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON payload."}, status=400)

    customer = None
    if _auth_mobile_customer_from_request_data is not None:
        try:
            customer = _mobile_customer_from_payload(request, payload)
        except Exception:
            customer = None

    vendor_profile, product = _get_vendor_and_product_from_payload(payload)
    if not vendor_profile:
        return JsonResponse({"success": False, "message": "Choose a valid supplier before requesting a callback."}, status=400)

    options = _vendor_contact_options(vendor_profile, product=product, request=request)
    if not options.get("can_request_callback"):
        return JsonResponse({"success": False, "message": "This supplier is not enabled for callback requests. Please use Arolana Chat."}, status=403)

    customer_phone = (payload.get("phone_number") or payload.get("customer_phone") or getattr(customer, "phone_number", "") or "").strip()
    customer_email = (payload.get("email") or payload.get("customer_email") or getattr(customer, "email", "") or "").strip()
    customer_name = (payload.get("full_name") or payload.get("customer_name") or getattr(customer, "full_name", "") or "").strip()
    request_user = getattr(request, "user", None)
    if request_user is not None and getattr(request_user, "is_authenticated", False):
        customer_name = customer_name or request_user.get_full_name() or request_user.username
        customer_email = customer_email or getattr(request_user, "email", "")
    if not customer_phone and not customer_email:
        return JsonResponse({"success": False, "message": "Add a phone number or email so the supplier can respond."}, status=400)

    customer_user = getattr(customer, "user", None)
    if not customer_user and request_user is not None and getattr(request_user, "is_authenticated", False):
        customer_user = request_user
    callback = VendorCallbackRequest.objects.create(
        vendor=vendor_profile,
        product=product,
        customer_user=customer_user,
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_email=customer_email,
        message=(payload.get("message") or "").strip(),
        urgency=payload.get("urgency") if payload.get("urgency") in {"normal", "high", "urgent"} else "normal",
    )
    _create_vendor_lead(
        request,
        vendor_profile,
        "callback_request",
        product=product,
        customer=customer,
        payload=payload,
        metadata={"callback_request_id": callback.id},
    )
    _notify_vendor_callback_request(request, callback, vendor_profile, product, payload)
    return JsonResponse({
        "success": True,
        "message": "Your callback request has been sent successfully. The vendor has received your request and product details. For your safety, please complete payment and order tracking through Arolana.",
        "callback_request_id": callback.id,
    })


@csrf_exempt
@require_http_methods(["POST"])
def mobile_vendor_reveal_phone_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON payload."}, status=400)

    vendor_profile, product = _get_vendor_and_product_from_payload(payload)
    if not vendor_profile:
        return JsonResponse({"success": False, "message": "Supplier not found."}, status=404)

    options = _vendor_contact_options(vendor_profile, product=product, reveal_phone=True, request=request)
    if not options.get("can_show_phone") or not options.get("phone"):
        return JsonResponse({"success": False, "message": "This supplier phone is not available. Please use Arolana Chat."}, status=403)

    customer = None
    if _auth_mobile_customer_from_request_data is not None:
        try:
            customer = _mobile_customer_from_payload(request, payload)
        except Exception:
            customer = None
    _create_vendor_lead(request, vendor_profile, "phone_reveal", product=product, customer=customer, payload=payload)
    return JsonResponse({"success": True, "vendor_contact_options": options})


@csrf_exempt
@require_http_methods(["POST"])
def mobile_vendor_track_contact_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON payload."}, status=400)

    action_type = payload.get("action_type")
    allowed_actions = {
        "phone_call",
        "call_click",
        "whatsapp_click",
        "product_link_shared_to_whatsapp",
        "chat_click",
        "chat_started",
        "chat_message_sent",
        "add_to_cart",
        "buy_now_click",
        "checkout_started",
        "order_created",
    }
    if action_type not in allowed_actions:
        return JsonResponse({"success": False, "message": "Invalid contact action."}, status=400)

    vendor_profile, product = _get_vendor_and_product_from_payload(payload)
    if not vendor_profile:
        return JsonResponse({"success": False, "message": "Supplier not found."}, status=404)

    options = _vendor_contact_options(vendor_profile, product=product, request=request)
    if action_type in {"phone_call", "call_click"} and not options.get("can_show_phone"):
        return JsonResponse({"success": False, "message": "Phone contact is not enabled for this supplier."}, status=403)
    if action_type in {"whatsapp_click", "product_link_shared_to_whatsapp"} and not options.get("can_show_whatsapp"):
        return JsonResponse({"success": False, "message": "WhatsApp contact is not enabled for this supplier."}, status=403)

    customer = None
    if _auth_mobile_customer_from_request_data is not None:
        try:
            customer = _mobile_customer_from_payload(request, payload)
        except Exception:
            customer = None
    _create_vendor_lead(request, vendor_profile, action_type, product=product, customer=customer, payload=payload)
    return JsonResponse({"success": True})


def _mobile_vendor_chat_message_payload(message, user):
    return {
        "id": message.id,
        "message": message.message,
        "sender_id": message.sender_id,
        "sender_name": message.sender.get_full_name() or message.sender.username or message.sender.email,
        "is_mine": message.sender_id == user.id,
        "timestamp": message.created_at.strftime("%H:%M"),
        "created_at": message.created_at.isoformat(),
    }


def _mobile_vendor_chat_room_payload(request, room, customer_user):
    messages = room.messages.select_related("sender").order_by("created_at")[:80]
    product = room.product
    return {
        "id": room.id,
        "vendor_id": room.vendor_id,
        "product_id": getattr(product, "id", None),
        "product_name": getattr(product, "name", ""),
        "product_url": _product_absolute_url(request, product) if product else "",
        "messages": [_mobile_vendor_chat_message_payload(message, customer_user) for message in messages],
    }


@csrf_exempt
@require_http_methods(["POST"])
def mobile_vendor_chat_context_api(request):
    if VendorChatRoom is None or VendorChatMessage is None:
        return JsonResponse({"success": False, "message": "Vendor chat is not available."}, status=500)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON payload."}, status=400)

    try:
        customer = _mobile_customer_from_payload(request, payload)
    except Exception:
        return JsonResponse({"success": False, "message": "Login is required before chatting with a vendor."}, status=401)

    vendor_profile, product = _get_vendor_and_product_from_payload(payload)
    if not vendor_profile or not getattr(vendor_profile, "user", None):
        return JsonResponse({"success": False, "message": "Supplier not found."}, status=404)

    vendor_user = vendor_profile.user
    if not user_has_paid_subscription(vendor_user):
        return JsonResponse({
            "success": False,
            "message": "This supplier chat is not active. You can request a callback or contact Arolana support.",
        }, status=403)

    room, created = VendorChatRoom.objects.get_or_create(
        vendor=vendor_user,
        customer=customer.user,
        product=product,
        defaults={},
    )
    if created:
        _create_vendor_lead(
            request,
            vendor_profile,
            "chat_started",
            product=product,
            customer=customer,
            payload=payload,
            metadata={"room_id": room.id, "source": "mobile_vendor_chat"},
        )
    else:
        _create_vendor_lead(
            request,
            vendor_profile,
            "chat_click",
            product=product,
            customer=customer,
            payload=payload,
            metadata={"room_id": room.id, "source": "mobile_vendor_chat"},
        )

    room.messages.filter(is_read=False).exclude(sender=customer.user).update(is_read=True, read_at=timezone.now())
    room.customer_unread = 0
    room.save(update_fields=["customer_unread", "updated_at"])

    return JsonResponse({
        "success": True,
        "room": _mobile_vendor_chat_room_payload(request, room, customer.user),
        "vendor": _mobile_vendor_payload(request, vendor_profile),
    })


@csrf_exempt
@require_http_methods(["POST"])
def mobile_vendor_chat_send_api(request, room_id):
    if VendorChatRoom is None or VendorChatMessage is None:
        return JsonResponse({"success": False, "message": "Vendor chat is not available."}, status=500)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON payload."}, status=400)

    try:
        customer = _mobile_customer_from_payload(request, payload)
    except Exception:
        return JsonResponse({"success": False, "message": "Login is required before sending a message."}, status=401)

    room = get_object_or_404(
        VendorChatRoom.objects.select_related("vendor", "vendor__vendor_profile", "customer", "product"),
        id=room_id,
        customer=customer.user,
        is_active=True,
    )
    vendor_profile = getattr(room.vendor, "vendor_profile", None)
    if not user_has_paid_subscription(room.vendor):
        return JsonResponse({"success": False, "message": "This supplier chat is not active."}, status=403)

    message_text = str(payload.get("message") or "").strip()
    if not message_text:
        return JsonResponse({"success": False, "message": "Type a message before sending."}, status=400)

    message = VendorChatMessage.objects.create(
        room=room,
        sender=customer.user,
        message=message_text[:4000],
    )
    room.last_message = message.message
    room.last_message_time = timezone.now()
    room.vendor_unread += 1
    room.save(update_fields=["last_message", "last_message_time", "vendor_unread", "updated_at"])

    if vendor_profile:
        _create_vendor_lead(
            request,
            vendor_profile,
            "chat_message_sent",
            product=room.product,
            customer=customer,
            payload=payload,
            metadata={"room_id": room.id, "message_id": message.id, "source": "mobile_vendor_chat"},
        )
    try:
        if Notification:
            Notification.send(
                user=room.vendor,
                notification_type="message",
                title=f"New product chat from {customer.full_name or customer.phone_number}",
                message=(message.message[:140] + "...") if len(message.message) > 140 else message.message,
                link=reverse("chat:vendor_room", args=[room.id]),
                metadata={"room_type": "vendor_customer", "room_id": room.id, "product_id": getattr(room.product, "id", None)},
                priority=3,
            )
    except Exception:
        pass

    return JsonResponse({
        "success": True,
        "message": _mobile_vendor_chat_message_payload(message, customer.user),
        "room": {
            "id": room.id,
            "vendor_unread": room.vendor_unread,
        },
    })


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
        customer = _mobile_customer_from_payload(request, payload)
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
        customer = _mobile_customer_from_payload(request, payload)
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
        customer = _mobile_customer_from_payload(request, request.GET)
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
        customer = _mobile_customer_from_payload(request, payload)
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
        customer = _mobile_customer_from_payload(request, request.GET)
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
        customer = _mobile_customer_from_payload(request, payload)
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
