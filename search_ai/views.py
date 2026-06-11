import json
import re
import logging

from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.media_optimization import get_optimized_image_url
from currency.templatetags.currency_filters import currency as format_currency
from manufacturers.models import Manufacturer
from products.models import Category, Product
from products.ranking import order_storefront_products
from vendors.models import VendorProfile

from .models import SearchHistory

logger = logging.getLogger(__name__)


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _clean_query(value):
    return re.sub(r'\s+', ' ', (value or '').strip())


SEARCH_STOP_WORDS = {
    'a', 'an', 'and', 'any', 'are', 'available', 'bring', 'buy', 'can', 'carry',
    'could', 'do', 'does', 'find', 'for', 'from', 'get', 'give', 'got', 'have',
    'help', 'i', 'in', 'is', 'it', 'me', 'need', 'of', 'on', 'please', 'price',
    'product', 'products', 'search', 'sell', 'show', 'shop', 'stock', 'that',
    'the', 'there', 'this', 'to', 'want', 'with', 'you', 'your', 'cheap',
    'affordable', 'best', 'good'
}

SEARCH_ALIASES = {
    'google': ('google', 'pixel'),
    'pixel': ('pixel', 'google'),
    'phone': ('phone', 'phones', 'smartphone', 'mobile'),
    'phones': ('phone', 'phones', 'smartphone', 'mobile'),
    'tv': ('tv', 'television'),
    'television': ('tv', 'television'),
}


def _query_terms(query, limit=10):
    """Extract product-bearing words from natural search sentences."""
    clean = _clean_query(query).lower()
    words = [
        word for word in re.findall(r"[a-z0-9][a-z0-9+.-]*", clean)
        if len(word) > 1 and word not in SEARCH_STOP_WORDS
    ]

    terms = []
    for word in words:
        if word not in terms:
            terms.append(word)

    return terms[:limit]


def _icontains_any(fields, query, terms=None):
    terms = terms if terms is not None else _query_terms(query)
    search_q = Q()

    if query:
        for field in fields:
            search_q |= Q(**{f'{field}__icontains': query})

    for term in terms:
        for field in fields:
            search_q |= Q(**{f'{field}__icontains': term})

    return search_q


def _product_search_q(query, terms=None):
    fields = ['name', 'description', 'manufacturer_sku', 'sku', 'category__name', 'brand__name']
    terms = terms if terms is not None else _query_terms(query)
    if not terms:
        return _icontains_any(fields, query, terms)

    search_q = Q()
    for term in terms:
        term_q = Q()
        for value in SEARCH_ALIASES.get(term, (term,)):
            for field in fields:
                term_q |= Q(**{f'{field}__icontains': value})
        search_q &= term_q
    return search_q


def _product_relevance_case(query, terms=None):
    terms = terms if terms is not None else _query_terms(query)
    whens = [
        When(name__iexact=query, then=Value(120)),
        When(name__istartswith=query, then=Value(110)),
        When(name__icontains=query, then=Value(100)),
        When(brand__name__istartswith=query, then=Value(92)),
        When(category__name__istartswith=query, then=Value(88)),
        When(sku__icontains=query, then=Value(86)),
        When(manufacturer_sku__icontains=query, then=Value(86)),
    ]

    for index, term in enumerate(terms[:8]):
        score = max(62, 84 - index)
        whens.extend([
            When(name__icontains=term, then=Value(score)),
            When(brand__name__icontains=term, then=Value(score - 4)),
            When(category__name__icontains=term, then=Value(score - 6)),
            When(sku__icontains=term, then=Value(score - 8)),
            When(manufacturer_sku__icontains=term, then=Value(score - 8)),
        ])

    return Case(*whens, default=Value(50), output_field=IntegerField())


def _search_suggestions(query, categories, products):
    words = [word for word in re.split(r'\W+', query.lower()) if len(word) > 1]
    suggestions = []
    for category in categories[:4]:
        suggestions.append(category.name)
    for product in products[:4]:
        if product.brand:
            suggestions.append(product.brand.name)
        suggestions.append(product.name)
    if words:
        base = ' '.join(words)
        suggestions.extend([f'{base} deals', f'best {base}', f'{base} accessories'])

    seen = set()
    clean = []
    for suggestion in suggestions:
        key = suggestion.lower()
        if key != query.lower() and key not in seen:
            seen.add(key)
            clean.append(suggestion)
    return clean[:8]


def ai_search(request):
    """AI-powered search across products, categories, vendors, and manufacturers."""
    query = _clean_query(request.GET.get('q', ''))
    if len(query) < 2:
        return JsonResponse({'results': [], 'suggestions': []})

    try:
        terms = _query_terms(query)
        product_matches = (
            Product.objects
            .filter(_product_search_q(query, terms), is_active=True, approval_status='approved')
            .select_related('category', 'brand', 'vendor', 'vendor__vendor_profile')
            .annotate(relevance=_product_relevance_case(query, terms))
            .distinct()
        )
        product_matches = order_storefront_products(
            product_matches,
            '-relevance',
            '-rating_avg',
            '-sales_count',
        )[:8]
    except Exception:
        terms = _query_terms(query)
        product_matches = (
            Product.objects
            .filter(_product_search_q(query, terms), is_active=True, approval_status='approved')
            .select_related('category', 'brand', 'vendor', 'vendor__vendor_profile')
            .annotate(relevance=_product_relevance_case(query, terms))
            .distinct()
        )
        product_matches = order_storefront_products(
            product_matches,
            '-relevance',
            '-rating_avg',
            '-sales_count',
        )[:8]

    categories = (
        Category.objects
        .filter(_icontains_any(['name', 'description'], query), is_active=True)
        .annotate(
            product_total=Count(
                'products',
                filter=Q(products__is_active=True, products__approval_status='approved'),
            )
        )
        .order_by('-product_total', 'name')[:4]
    )

    vendors = (
        VendorProfile.objects
        .filter(_icontains_any(['store_name', 'description', 'user__email'], query), is_active=True)
        .select_related('user')
        .order_by('-is_verified', '-rating_avg', '-total_sales')[:4]
    )

    manufacturers = (
        Manufacturer.objects
        .filter(_icontains_any(['name', 'description'], query), is_active=True)
        .order_by('-is_featured', '-rating_avg', '-total_sales')[:4]
    )

    results_data = []
    for product in product_matches:
        results_data.append({
            'id': f'product-{product.id}',
            'type': 'product',
            'label': 'Product',
            'name': product.name,
            'price': str(product.price),
            'price_display': format_currency(product.price, request),
            'image': get_optimized_image_url(product.main_image, 'product_card') if product.main_image else '',
            'url': product.get_absolute_url(),
            'category': product.category.name if product.category else '',
            'brand': product.brand.name if product.brand else '',
            'rating': float(product.rating_avg),
            'relevance_score': product.relevance,
        })

    for category in categories:
        results_data.append({
            'id': f'category-{category.id}',
            'type': 'category',
            'label': 'Category',
            'name': category.name,
            'price': '',
            'price_display': f'{category.product_total} products',
            'image': get_optimized_image_url(category.image, 'category_card') if getattr(category, 'image', None) else '',
            'url': category.get_absolute_url() if hasattr(category, 'get_absolute_url') else f'/products/category/{category.slug}/',
            'category': 'Category',
            'brand': '',
            'rating': 0,
            'relevance_score': 74,
        })

    for vendor in vendors:
        results_data.append({
            'id': f'vendor-{vendor.id}',
            'type': 'vendor',
            'label': 'Vendor',
            'name': vendor.store_name,
            'price': '',
            'price_display': 'Verified seller' if vendor.is_verified else 'Seller',
            'image': get_optimized_image_url(vendor.store_logo, 'avatar') if vendor.store_logo else '',
            'url': vendor.get_absolute_url() if hasattr(vendor, 'get_absolute_url') else f'/vendors/{vendor.store_slug}/',
            'category': 'Vendor',
            'brand': '',
            'rating': float(vendor.rating_avg or 0),
            'relevance_score': 70,
        })

    for manufacturer in manufacturers:
        results_data.append({
            'id': f'manufacturer-{manufacturer.id}',
            'type': 'manufacturer',
            'label': 'Manufacturer',
            'name': manufacturer.name,
            'price': '',
            'price_display': 'Manufacturer',
            'image': get_optimized_image_url(manufacturer.logo, 'avatar') if manufacturer.logo else '',
            'url': manufacturer.get_absolute_url() if hasattr(manufacturer, 'get_absolute_url') else f'/manufacturers/{manufacturer.slug}/',
            'category': 'Manufacturer',
            'brand': '',
            'rating': float(manufacturer.rating_avg or 0),
            'relevance_score': 68,
        })

    results_data = sorted(results_data, key=lambda item: item['relevance_score'], reverse=True)[:12]
    suggestions = _search_suggestions(query, list(categories), list(product_matches))

    try:
        SearchHistory.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_id=request.session.session_key or '',
            query=query,
            results_count=len(results_data),
            ip_address=_client_ip(request),
        )
    except Exception:
        pass

    return JsonResponse({
        'results': results_data,
        'suggestions': suggestions,
        'total': len(results_data),
        'query': query,
    })


@csrf_exempt
@require_http_methods(["POST"])
def track_click(request):
    """Track when a user clicks a search result."""
    try:
        data = json.loads(request.body)
        return JsonResponse({'success': True, 'tracked': data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


def advanced_search(request):
    """Advanced search page with filters."""
    products = Product.objects.filter(
        is_active=True,
        approval_status='approved',
    ).select_related('category', 'brand', 'vendor', 'vendor__vendor_profile')

    query = _clean_query(request.GET.get('q', ''))
    category = request.GET.get('category')
    condition = request.GET.get('condition')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    rating = request.GET.get('rating')
    sort = request.GET.get('sort') or ('-relevance' if query else '-created_at')

    if query:
        terms = _query_terms(query)
        products = products.filter(_product_search_q(query, terms)).annotate(
            relevance=_product_relevance_case(query, terms)
        ).distinct()

    if category:
        products = products.filter(category__slug=category)

    if condition:
        products = products.filter(condition=condition)

    if min_price:
        try:
            products = products.filter(price__gte=float(min_price))
        except:
            pass

    if max_price:
        try:
            products = products.filter(price__lte=float(max_price))
        except:
            pass

    if rating:
        try:
            products = products.filter(rating_avg__gte=float(rating))
        except:
            pass

    allowed_sorts = {'-created_at', 'created_at', 'price', '-price', '-rating_avg', '-sales_count', 'name', '-relevance'}
    if sort == '-relevance' and not query:
        sort = '-created_at'
    if sort not in allowed_sorts:
        sort = '-created_at'
    products = order_storefront_products(products, sort)

    also_search_products = Product.objects.filter(
        is_active=True,
        approval_status='approved',
    ).select_related('category', 'brand', 'vendor', 'vendor__vendor_profile')

    if query:
        also_terms = _query_terms(query)
        also_search_products = also_search_products.filter(_product_search_q(query, also_terms))
    else:
        search_terms_q = Q()
        for item in SearchHistory.objects.values('query').annotate(count=Count('id')).order_by('-count')[:16]:
            term_query = _clean_query(item.get('query'))
            if term_query:
                search_terms_q |= _product_search_q(term_query, _query_terms(term_query, limit=5))
        if search_terms_q:
            also_search_products = also_search_products.filter(search_terms_q)

    also_search_products = order_storefront_products(
        also_search_products.distinct(),
        '-sales_count',
        '-rating_avg',
        '-created_at',
    )[:10]

    paginator = Paginator(products, 24)
    page_obj = paginator.get_page(request.GET.get('page'))
    pagination_params = request.GET.copy()
    pagination_params.pop('page', None)

    context = {
        'products': page_obj,
        'page_obj': page_obj,
        'result_count': paginator.count,
        'categories': Category.objects.filter(is_active=True, parent=None),
        'query': query,
        'selected_category': category,
        'selected_condition': condition,
        'condition_choices': Product.PRODUCT_CONDITION_CHOICES,
        'min_price': min_price,
        'max_price': max_price,
        'selected_rating': rating,
        'sort': sort,
        'also_search_products': also_search_products,
        'pagination_query': pagination_params.urlencode(),
    }

    return render(request, 'search_ai/advanced_search.html', context)


def image_search(request):
    """Image search page."""
    return render(request, 'search_ai/image_search.html')


@csrf_exempt
@require_http_methods(["POST"])
def upload_search_image(request):
    """Handle image upload for visual search."""
    try:
        uploaded_file = request.FILES.get('image')
        if uploaded_file:
            return JsonResponse({
                'success': True,
                'message': 'Image uploaded successfully',
                'suggested_keywords': ['electronics', 'gadgets', 'tech'],
            })
        return JsonResponse({'success': False, 'error': 'No image provided'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@csrf_exempt
@require_http_methods(["POST"])
def voice_search(request):
    """Handle voice search requests with AI-powered intent recognition"""
    try:
        data = json.loads(request.body)
        voice_text = _clean_query(data.get('voice_text', ''))

        if not voice_text:
            return JsonResponse({'success': False, 'error': 'No voice input detected'}, status=400)

        terms = _query_terms(voice_text)
        products = Product.objects.filter(
            is_active=True,
            approval_status='approved',
        ).select_related('category', 'brand')

        products = products.filter(_product_search_q(voice_text, terms)).annotate(
            relevance=_product_relevance_case(voice_text, terms)
        ).distinct().order_by('-relevance', '-rating_avg', '-sales_count')[:12]

        result_count = products.count()

        if request.user.is_authenticated:
            SearchHistory.objects.create(
                user=request.user,
                session_id=request.session.session_key or '',
                query=f"[Voice] {voice_text}",
                results_count=result_count,
                ip_address=_client_ip(request),
            )

        results_data = []
        for product in products:
            results_data.append({
                'id': product.id,
                'name': product.name,
                'price': str(product.price),
                'price_display': format_currency(product.price, request),
                'image': get_optimized_image_url(product.main_image, 'product_card') if product.main_image else '',
                'url': product.get_absolute_url(),
                'category': product.category.name if product.category else '',
                'brand': product.brand.name if product.brand else '',
                'rating': float(product.rating_avg),
                'relevance_score': product.relevance,
            })

        if result_count == 0:
            ai_message = f"I couldn't find any products matching '{voice_text}'. Try a different search term!"
        elif result_count == 1:
            ai_message = f"I found exactly what you're looking for! Here's the perfect match for '{voice_text}'."
        elif result_count < 5:
            ai_message = f"I found {result_count} great products for '{voice_text}'. Check them out below!"
        else:
            ai_message = f"I discovered {result_count} amazing products matching '{voice_text}'. Here are the best ones!"

        return JsonResponse({
            'success': True,
            'query': voice_text,
            'terms': terms,
            'results': results_data,
            'count': result_count,
            'ai_message': ai_message,
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def voice_search_page(request):
    """Render the voice search page with Web Speech API support"""
    return render(request, 'search_ai/voice_search_modal.html')


# ---------------------------------------------------------------------
# Mobile AI Search API helpers
# ---------------------------------------------------------------------

MOBILE_INTENT_KEYWORDS = {
    'phone': ['phone', 'smartphone', 'iphone', 'android', 'pixel', 'samsung', 'mobile'],
    'laptop': ['laptop', 'macbook', 'notebook', 'computer', 'pc'],
    'gaming': ['gaming', 'game', 'console', 'playstation', 'xbox', 'nintendo', 'controller'],
    'watch': ['watch', 'smartwatch', 'wearable', 'fitness'],
    'audio': ['audio', 'speaker', 'headphone', 'earbud', 'airpod', 'sound'],
    'power': ['power', 'charger', 'adapter', 'cable', 'battery', 'powerbank'],
    'case': ['case', 'cover', 'protector', 'screen guard', 'armor'],
    'monitor': ['monitor', 'display', 'screen', 'ultragear'],
    'budget': ['cheap', 'affordable', 'budget', 'low price', 'lowest', 'low budget'],
}


def _mobile_expand_terms(query):
    clean = _clean_query(query).lower()
    terms = _query_terms(clean, limit=14)
    expanded = set(terms)

    if clean:
        expanded.add(clean)

    intent = 'general'

    for group, words in MOBILE_INTENT_KEYWORDS.items():
        if group in clean or any(word in clean for word in words):
            intent = group
            expanded.add(group)
            expanded.update(words)

    return list(expanded), intent


def _mobile_product_image(request, product):
    image = getattr(product, 'main_image', None)

    if image:
        try:
            return request.build_absolute_uri(get_optimized_image_url(image, 'product_card'))
        except Exception:
            try:
                return request.build_absolute_uri(image.url)
            except Exception:
                return str(image)

    for field_name in ['image', 'thumbnail', 'photo', 'featured_image', 'product_image']:
        image = getattr(product, field_name, None)
        if image:
            try:
                return request.build_absolute_uri(image.url)
            except Exception:
                return str(image)

    try:
        first_image = product.images.first()
        if first_image:
            for attr in ['image', 'file', 'photo']:
                img = getattr(first_image, attr, None)
                if img:
                    try:
                        return request.build_absolute_uri(img.url)
                    except Exception:
                        return str(img)
    except Exception:
        pass

    return ''


def _mobile_product_payload(request, product, score=0):
    category_name = product.category.name if getattr(product, 'category', None) else ''
    brand_name = product.brand.name if getattr(product, 'brand', None) else ''

    return {
        'id': product.id,
        'name': product.name,
        'title': product.name,
        'slug': getattr(product, 'slug', ''),
        'price': str(getattr(product, 'price', '') or ''),
        'price_display': format_currency(product.price, request) if getattr(product, 'price', None) is not None else '',
        'image': _mobile_product_image(request, product),
        'main_image': _mobile_product_image(request, product),
        'thumbnail': _mobile_product_image(request, product),
        'category': category_name,
        'category_name': category_name,
        'brand': brand_name,
        'description': getattr(product, 'description', '') or '',
        'rating': float(getattr(product, 'rating_avg', 0) or 0),
        'sales_count': int(getattr(product, 'sales_count', 0) or 0),
        'relevance_score': int(score or getattr(product, 'relevance', 0) or 0),
    }


def _mobile_base_products():
    products = Product.objects.all().select_related(
        'category',
        'brand',
        'vendor',
        'vendor__vendor_profile',
    )

    field_names = {field.name for field in Product._meta.fields}

    if 'is_active' in field_names:
        products = products.filter(is_active=True)

    if 'approval_status' in field_names:
        products = products.filter(approval_status='approved')

    if 'status' in field_names:
        products = products.filter(status__in=['active', 'published', 'approved'])

    if 'is_published' in field_names:
        products = products.filter(is_published=True)

    return products


def _mobile_suggestions(query, products):
    suggestions = []

    categories = []
    brands = []

    for product in products[:20]:
        if getattr(product, 'category', None) and product.category.name not in categories:
            categories.append(product.category.name)

        if getattr(product, 'brand', None) and product.brand.name not in brands:
            brands.append(product.brand.name)

    suggestions.extend(categories[:4])
    suggestions.extend(brands[:3])

    terms = _query_terms(query, limit=3)

    if terms:
        base = ' '.join(terms)
        suggestions.extend([
            base,
            f'cheap {base}',
            f'best {base}',
            f'{base} accessories',
        ])

    if not suggestions:
        suggestions = ['smartphones', 'gaming', 'chargers', 'laptops', 'accessories']

    clean = []
    seen = set()

    for suggestion in suggestions:
        suggestion = _clean_query(suggestion)
        key = suggestion.lower()

        if suggestion and key not in seen:
            seen.add(key)
            clean.append(suggestion)

    return clean[:8]


def _mobile_ai_rank_products(query, category='', limit=60):
    query = _clean_query(query)
    category = _clean_query(category)

    terms, intent = _mobile_expand_terms(f'{query} {category}')

    products = _mobile_base_products()

    if query or category:
        search_q = _product_search_q(query or category, terms)

        if category:
            search_q |= Q(category__name__icontains=category)

        products = (
            products
            .filter(search_q)
            .annotate(relevance=_product_relevance_case(query or category, terms))
            .distinct()
        )
        products = order_storefront_products(
            products,
            '-relevance',
            '-rating_avg',
            '-sales_count',
            '-created_at',
        )[:limit]
    else:
        products = order_storefront_products(
            products,
            '-sales_count',
            '-rating_avg',
            '-created_at',
        )[:limit]

    return list(products), intent


@csrf_exempt
@require_http_methods(["POST"])
def mobile_ai_search_api(request):
    """Mobile AI product search endpoint for the React Native app."""
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'success': False, 'message': 'Invalid JSON payload.'}, status=400)

    query = _clean_query(data.get('query', ''))
    category = _clean_query(data.get('category', ''))
    session_id = _clean_query(data.get('session_id', ''))
    limit = int(data.get('limit') or 60)

    products, intent = _mobile_ai_rank_products(query=query, category=category, limit=limit)

    results = [
        _mobile_product_payload(request, product, getattr(product, 'relevance', 0))
        for product in products
    ]

    try:
        SearchHistory.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_id=session_id or (request.session.session_key or ''),
            query=query or category or 'browse',
            results_count=len(results),
            ip_address=_client_ip(request),
            **{
                key: value
                for key, value in {
                    'intent': intent,
                    'category': category,
                    'user_agent': request.META.get('HTTP_USER_AGENT', '')[:1000],
                }.items()
                if key in {field.name for field in SearchHistory._meta.fields}
            }
        )
    except Exception:
        logger.exception('Could not save mobile search history')

    return JsonResponse({
        'success': True,
        'query': query,
        'category': category,
        'intent': intent,
        'ai_message': (
            f'AI found {len(results)} result(s) for "{query or category}".'
            if (query or category)
            else 'AI is ready. Search by product, category, budget or need.'
        ),
        'suggestions': _mobile_suggestions(query or category, products),
        'products': results,
        'results_count': len(results),
    })


@csrf_exempt
@require_http_methods(["POST"])
def mobile_voice_search_api(request):
    """Mobile voice-search endpoint.

    Expo Go uses iPhone keyboard dictation for voice input. The app sends the
    transcript here so Django can log and return AI-ranked product results.
    """
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'success': False, 'message': 'Invalid JSON payload.'}, status=400)

    transcript = _clean_query(data.get('transcript') or data.get('voice_text') or data.get('query') or '')
    session_id = _clean_query(data.get('session_id', ''))

    if not transcript:
        return JsonResponse({'success': False, 'message': 'Voice transcript is required.'}, status=400)

    products, intent = _mobile_ai_rank_products(query=transcript, category='', limit=60)

    results = [
        _mobile_product_payload(request, product, getattr(product, 'relevance', 0))
        for product in products
    ]

    if len(results) == 0:
        ai_reply = f'I could not find a strong match for "{transcript}". Try a broader phrase.'
    elif len(results) == 1:
        ai_reply = f'I found 1 product for "{transcript}".'
    else:
        ai_reply = f'I found {len(results)} products for "{transcript}".'

    try:
        from .models import VoiceSearchLog

        VoiceSearchLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_id=session_id or (request.session.session_key or ''),
            transcript=transcript,
            ai_reply=ai_reply,
            results_count=len(results),
            ip_address=_client_ip(request),
        )
    except Exception:
        logger.exception('Could not save voice search log')

    try:
        SearchHistory.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_id=session_id or (request.session.session_key or ''),
            query=f'[Voice] {transcript}',
            results_count=len(results),
            ip_address=_client_ip(request),
            **{
                key: value
                for key, value in {
                    'intent': intent,
                    'category': '',
                    'user_agent': request.META.get('HTTP_USER_AGENT', '')[:1000],
                }.items()
                if key in {field.name for field in SearchHistory._meta.fields}
            }
        )
    except Exception:
        pass

    return JsonResponse({
        'success': True,
        'transcript': transcript,
        'query': transcript,
        'intent': intent,
        'ai_reply': ai_reply,
        'ai_message': ai_reply,
        'suggestions': _mobile_suggestions(transcript, products),
        'products': results,
        'results_count': len(results),
    })
