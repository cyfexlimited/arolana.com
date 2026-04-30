from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db.models import Q
from .models import HeroBanner, HeroBannerAnalytics
import json
from django.utils import timezone

def get_active_banners(request):
    """Get all active banners for display"""
    banners = HeroBanner.objects.filter(is_active=True).order_by('display_order')
    
    # Filter by date
    now = timezone.now()
    banners = banners.filter(
        Q(start_date__isnull=True) | Q(start_date__lte=now),
        Q(end_date__isnull=True) | Q(end_date__gte=now),
    )
    
    return banners

@csrf_exempt
@require_POST
def track_banner_view(request):
    """Track banner views"""
    try:
        data = json.loads(request.body)
        banner_id = data.get('banner_id')
        banner = HeroBanner.objects.get(id=banner_id)
        banner.increment_view()
        
        HeroBannerAnalytics.objects.create(
            banner=banner,
            session_id=request.session.session_key,
            user=request.user if request.user.is_authenticated else None,
            action='view',
        )
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_POST
def track_banner_click(request):
    """Track banner clicks"""
    try:
        data = json.loads(request.body)
        banner_id = data.get('banner_id')
        banner = HeroBanner.objects.get(id=banner_id)
        banner.increment_click()
        
        HeroBannerAnalytics.objects.create(
            banner=banner,
            session_id=request.session.session_key,
            user=request.user if request.user.is_authenticated else None,
            action='click',
        )
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})