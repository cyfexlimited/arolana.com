from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from .models import VendorProfile, VendorFollow
from products.models import Product
import random

def vendor_list(request):
    """List all vendors with sorting options"""
    # Get all verified and active vendors
    all_vendors = list(VendorProfile.objects.filter(is_verified=True, is_active=True))
    
    # Shuffle for all vendors
    vendors_shuffled = all_vendors.copy()
    random.shuffle(vendors_shuffled)
    
    # Top rated vendors (sorted by rating)
    top_rated_vendors = sorted(all_vendors, key=lambda x: x.rating_avg, reverse=True)[:4]
    
    # Trending vendors (sorted by sales)
    trending_vendors = sorted(all_vendors, key=lambda x: x.total_sales, reverse=True)[:4]
    
    # Pagination
    paginator = Paginator(vendors_shuffled, 12)
    page = request.GET.get('page', 1)
    vendors_page = paginator.get_page(page)
    
    context = {
        'vendors_shuffled': vendors_page,
        'top_rated_vendors': top_rated_vendors,
        'trending_vendors': trending_vendors,
        'total_vendors': len(all_vendors),
    }
    return render(request, 'vendors/list.html', context)

def vendor_detail(request, slug):
    """Display individual vendor shop page"""
    vendor = get_object_or_404(VendorProfile, store_slug=slug, is_active=True)
    products = Product.objects.filter(vendor=vendor.user, is_active=True)
    
    context = {
        'vendor': vendor,
        'products': products,
        'product_count': products.count(),
    }
    return render(request, 'vendors/detail.html', context)

@login_required
def become_vendor(request):
    """Allow user to become a vendor"""
    if hasattr(request.user, 'vendor_profile'):
        messages.info(request, 'You are already a vendor!')
        return redirect('vendors:detail', slug=request.user.vendor_profile.store_slug)
    
    if request.method == 'POST':
        store_name = request.POST.get('store_name')
        store_slug = request.POST.get('store_slug')
        description = request.POST.get('description')
        
        if not store_name or not store_slug or not description:
            messages.error(request, 'Please fill in all fields')
            return render(request, 'vendors/become.html')
        
        if VendorProfile.objects.filter(store_slug=store_slug).exists():
            messages.error(request, 'This store URL is already taken.')
            return render(request, 'vendors/become.html')
        
        vendor = VendorProfile.objects.create(
            user=request.user,
            store_name=store_name,
            store_slug=store_slug,
            description=description,
            is_verified=True,
            is_active=True
        )
        
        request.user.user_type = 'vendor'
        request.user.save()
        
        messages.success(request, f'Congratulations! Your vendor account has been created.')
        return redirect('vendors:detail', slug=vendor.store_slug)
    
    return render(request, 'vendors/become.html')

@login_required
def follow_vendor(request, vendor_id):
    """Toggle follow/unfollow for a vendor"""
    vendor = get_object_or_404(VendorProfile, id=vendor_id, is_active=True)
    
    follow, created = VendorFollow.objects.get_or_create(
        user=request.user,
        vendor=vendor
    )
    
    if not created:
        follow.delete()
        followed = False
        messages.success(request, f'You unfollowed {vendor.store_name}')
    else:
        followed = True
        messages.success(request, f'You are now following {vendor.store_name}')
    
    vendor.followers_count = vendor.followers.count()
    vendor.save()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'followed': followed,
            'followers_count': vendor.followers_count
        })
    
    return redirect('vendors:detail', slug=vendor.store_slug)