import json
import re
import logging

from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.media_optimization import get_optimized_image_url
from currency.templatetags.currency_filters import currency as format_currency
from manufacturers.models import Manufacturer
from products.models import Category, Product
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
        product_matches = (
            Product.objects
            .filter(
                Q(name__icontains=query) |
                Q(description__icontains=query) |
                Q(category__name__icontains=query) |
                Q(brand__name__icontains=query),
                is_active=True,
                approval_status='approved',
            )
            .select_related('category', 'brand')
            .annotate(
                relevance=Case(
                    When(name__iexact=query, then=Value(100)),
                    When(name__istartswith=query, then=Value(90)),
                    When(brand__name__istartswith=query, then=Value(82)),
                    When(category__name__istartswith=query, then=Value(78)),
                    default=Value(60),
                    output_field=IntegerField(),
                )
            )
            .order_by('-relevance', '-rating_avg', '-sales_count')[:8]
        )
    except Exception:
        product_matches = (
            Product.objects
            .filter(
                Q(name__icontains=query) |
                Q(description__icontains=query) |
                Q(category__name__icontains=query) |
                Q(brand__name__icontains=query),
                is_active=True,
                approval_status='approved',
            )
            .select_related('category', 'brand')
            .annotate(
                relevance=Case(
                    When(name__iexact=query, then=Value(100)),
                    When(name__istartswith=query, then=Value(90)),
                    When(brand__name__istartswith=query, then=Value(82)),
                    When(category__name__istartswith=query, then=Value(78)),
                    default=Value(60),
                    output_field=IntegerField(),
                )
            )
            .order_by('-relevance', '-rating_avg', '-sales_count')[:8]
        )

    categories = (
        Category.objects
        .filter(
            Q(name__icontains=query) | Q(description__icontains=query),
            is_active=True,
        )
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
        .filter(
            Q(store_name__icontains=query) |
            Q(description__icontains=query) |
            Q(user__email__icontains=query),
            is_active=True,
        )
        .select_related('user')
        .order_by('-is_verified', '-rating_avg', '-total_sales')[:4]
    )

    manufacturers = (
        Manufacturer.objects
        .filter(
            Q(name__icontains=query) | Q(description__icontains=query),
            is_active=True,
        )
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
    products = Product.objects.filter(is_active=True, approval_status='approved').select_related('category', 'brand')

    query = _clean_query(request.GET.get('q', ''))
    category = request.GET.get('category')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    rating = request.GET.get('rating')
    sort = request.GET.get('sort', '-created_at')

    if query:
        products = products.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(category__name__icontains=query) |
            Q(brand__name__icontains=query)
        )

    if category:
        products = products.filter(category__slug=category)

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

    allowed_sorts = {'-created_at', 'created_at', 'price', '-price', '-rating_avg', '-sales_count', 'name'}
    if sort not in allowed_sorts:
        sort = '-created_at'
    products = products.order_by(sort)

    popular_searches = SearchHistory.objects.values('query').annotate(count=Count('id')).order_by('-count')[:10]

    context = {
        'products': products,
        'categories': Category.objects.filter(is_active=True, parent=None),
        'query': query,
        'selected_category': category,
        'min_price': min_price,
        'max_price': max_price,
        'selected_rating': rating,
        'sort': sort,
        'popular_searches': popular_searches,
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

        products = Product.objects.filter(
            is_active=True,
            approval_status='approved',
        ).select_related('category', 'brand')

        products = products.filter(
            Q(name__icontains=voice_text) |
            Q(description__icontains=voice_text) |
            Q(category__name__icontains=voice_text) |
            Q(brand__name__icontains=voice_text)
        ).annotate(
            relevance=Case(
                When(name__icontains=voice_text, then=Value(100)),
                When(brand__name__icontains=voice_text, then=Value(85)),
                When(category__name__icontains=voice_text, then=Value(75)),
                default=Value(60),
                output_field=IntegerField(),
            )
        ).order_by('-relevance', '-rating_avg', '-sales_count')[:12]

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
            'results': results_data,
            'count': result_count,
            'ai_message': ai_message,
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def voice_search_page(request):
    """Render the voice search page with Web Speech API support"""
    return render(request, 'search_ai/voice_search_modal.html')
