from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import AdBanner, AdPlacement
import json

def ad_click(request, banner_id):
    """Track ad clicks and redirect to destination URL"""
    banner = get_object_or_404(AdBanner, id=banner_id, is_active=True)
    # Increment click count
    banner.clicks += 1
    banner.save()
    
    # Use cta_url or fallback to button_url or default
    destination_url = getattr(banner, 'cta_url', None)
    if not destination_url:
        destination_url = getattr(banner, 'button_url', '/products/')
    
    return redirect(destination_url)

@csrf_exempt
@require_POST
def track_click_api(request, banner_id):
    """Track ad clicks via AJAX API"""
    try:
        banner = AdBanner.objects.get(id=banner_id)
        banner.clicks += 1
        banner.save()
        return JsonResponse({'success': True, 'clicks': banner.clicks})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_POST
def track_view(request):
    """Track ad views (impressions)"""
    try:
        # View tracking is handled in the template tag
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def test_page(request):
    """Test page to debug ad display"""
    # Get all placements
    placements = AdPlacement.objects.filter(is_active=True)
    
    # Get banners for each placement
    ad_data = []
    for placement in placements:
        banner = AdBanner.objects.filter(
            placement=placement,
            is_active=True,
            campaign__is_active=True
        ).first()
        
        ad_data.append({
            'placement': placement,
            'banner': banner,
            'has_image': bool(banner and banner.image),
            'image_url': banner.image.url if banner and banner.image else None
        })
    
    # Get all banners for debugging
    all_banners = AdBanner.objects.filter(is_active=True)
    
    context = {
        'ad_data': ad_data,
        'all_banners': all_banners,
        'total_banners': all_banners.count(),
    }
    return render(request, 'ads/test.html', context)
