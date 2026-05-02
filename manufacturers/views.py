from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from .models import Manufacturer, ManufacturerCategory

def manufacturer_list(request):
    """List all manufacturers"""
    manufacturers = Manufacturer.objects.filter(is_active=True)
    
    # Filter by category
    category_slug = request.GET.get('category')
    if category_slug:
        # This would need a category relationship - simplified for now
        pass
    
    # Sort options
    sort_by = request.GET.get('sort', 'name')
    if sort_by == 'top_rated':
        manufacturers = manufacturers.order_by('-rating_avg')
    elif sort_by == 'popular':
        manufacturers = manufacturers.order_by('-total_sales')
    elif sort_by == 'featured':
        manufacturers = manufacturers.filter(is_featured=True)
    else:
        manufacturers = manufacturers.order_by('display_order', 'name')
    
    paginator = Paginator(manufacturers, 12)
    page = request.GET.get('page', 1)
    manufacturers_page = paginator.get_page(page)
    
    # Get categories for filter
    categories = ManufacturerCategory.objects.filter(is_active=True)
    
    context = {
        'manufacturers': manufacturers_page,
        'categories': categories,
        'current_sort': sort_by,
        'total_manufacturers': Manufacturer.objects.filter(is_active=True).count(),
    }
    return render(request, 'manufacturers/list.html', context)

def manufacturer_detail(request, slug):
    """Manufacturer detail page"""
    manufacturer = get_object_or_404(Manufacturer, slug=slug, is_active=True)
    products = manufacturer.products.filter(is_active=True)[:20]
    
    context = {
        'manufacturer': manufacturer,
        'products': products,
        'product_count': manufacturer.total_products,
    }
    return render(request, 'manufacturers/detail.html', context)

def manufacturer_home(request):
    """Homepage manufacturers section"""
    featured_manufacturers = Manufacturer.objects.filter(is_featured=True, is_active=True)[:8]
    top_manufacturers = Manufacturer.objects.filter(is_active=True).order_by('-total_sales')[:8]
    
    context = {
        'featured_manufacturers': featured_manufacturers,
        'top_manufacturers': top_manufacturers,
    }
    return render(request, 'manufacturers/home_section.html', context)
