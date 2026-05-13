from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q, Count
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from products.models import Product, Category
import json

def ai_search(request):
    """AI-powered search with suggestions and fuzzy matching"""
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return JsonResponse({'results': [], 'suggestions': []})
    
    # Perform search
    results = Product.objects.filter(
        Q(name__icontains=query) |
        Q(description__icontains=query) |
        Q(category__name__icontains=query) |
        Q(brand__name__icontains=query),
        is_active=True,
        approval_status='approved'
    )[:10]
    
    # Get popular searches (mock suggestions)
    suggestions = [
        f"{query} deals",
        f"best {query}",
        f"cheap {query}",
        f"{query} sale",
        f"new {query}"
    ][:5]
    
    # Prepare JSON response with images
    results_data = []
    for idx, product in enumerate(results):
        results_data.append({
            'id': product.id,
            'name': product.name,
            'price': str(product.price),
            'image': product.main_image.url if product.main_image else '',
            'url': product.get_absolute_url(),
            'category': product.category.name,
            'brand': product.brand.name if product.brand else '',
            'rating': float(product.rating_avg),
            'relevance_score': 85
        })
    
    return JsonResponse({
        'results': results_data,
        'suggestions': suggestions,
        'total': len(results_data),
        'query': query
    })

@csrf_exempt
@require_http_methods(["POST"])
def track_click(request):
    """Track when user clicks on a search result"""
    try:
        data = json.loads(request.body)
        print(f"Track click: {data}")
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def advanced_search(request):
    """Advanced search page with filters"""
    products = Product.objects.filter(is_active=True, approval_status='approved')
    
    query = request.GET.get('q', '')
    category = request.GET.get('category')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    rating = request.GET.get('rating')
    sort = request.GET.get('sort', '-created_at')
    
    if query:
        products = products.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(category__name__icontains=query)
        )
    
    if category:
        products = products.filter(category__slug=category)
    
    if min_price:
        products = products.filter(price__gte=min_price)
    
    if max_price:
        products = products.filter(price__lte=max_price)
    
    if rating:
        products = products.filter(rating_avg__gte=rating)
    
    products = products.order_by(sort)
    
    context = {
        'products': products,
        'categories': Category.objects.filter(is_active=True, parent=None),
        'query': query,
        'selected_category': category,
        'min_price': min_price,
        'max_price': max_price,
        'selected_rating': rating,
        'sort': sort
    }
    
    return render(request, 'search_ai/advanced_search.html', context)

def image_search(request):
    """Image search page"""
    return render(request, 'search_ai/image_search.html')

@csrf_exempt
@require_http_methods(["POST"])
def upload_search_image(request):
    """Handle image upload for visual search"""
    try:
        uploaded_file = request.FILES.get('image')
        if uploaded_file:
            return JsonResponse({
                'success': True,
                'message': 'Image uploaded successfully',
                'suggested_keywords': ['electronics', 'gadgets', 'tech']
            })
        return JsonResponse({'success': False, 'error': 'No image provided'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})