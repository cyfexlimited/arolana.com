from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone
from django.core.paginator import Paginator
from .models import AdBanner, AdPlacement, AdImpression, AdClick, AdCampaign, ExternalAdvertisingAccount
from .management import (
    AdvertiserAccessError,
    AdvertiserValidationError,
    connected_account_shells,
    create_campaign,
    create_creative,
    creative_queryset,
    current_advertiser_identity,
    owned_asset_options,
    overview_metrics,
    campaign_queryset,
    serialize_campaign,
)
from django.conf import settings
from decimal import Decimal
import json
import os
import logging

logger = logging.getLogger(__name__)


def _dashboard_enabled():
    return bool(getattr(settings, "ADS_ADVERTISER_DASHBOARD_ENABLED", False))


def _dashboard_context(request, section):
    if not _dashboard_enabled():
        return {
            "dashboard_enabled": False,
            "section": section,
        }
    try:
        identity = current_advertiser_identity(
            request.user,
            advertiser_id=request.GET.get("advertiser_id"),
        )
    except AdvertiserAccessError:
        return {
            "dashboard_enabled": True,
            "access_denied": True,
            "section": section,
        }
    return {
        "dashboard_enabled": True,
        "advertiser": identity,
        "section": section,
        "nav_items": [
            ("overview", "Overview", "ads:marketing_overview"),
            ("campaigns", "Campaigns", "ads:marketing_campaigns"),
            ("create", "Create Campaign", "ads:marketing_create_campaign"),
            ("assets", "Promoted Assets", "ads:marketing_assets"),
            ("creatives", "Creative Library", "ads:marketing_creatives"),
            ("placements", "Placements", "ads:marketing_placements"),
            ("connected", "Connected Accounts", "ads:marketing_connected_accounts"),
            ("analytics", "Analytics", "ads:marketing_analytics"),
            ("billing", "Billing / Funding", "ads:marketing_billing"),
            ("settings", "Settings", "ads:marketing_settings"),
        ],
    }


def _render_dashboard(request, template, section, extra=None):
    context = _dashboard_context(request, section)
    if context.get("dashboard_enabled") and not context.get("access_denied") and extra:
        context.update(extra(context["advertiser"]) if callable(extra) else extra)
    return render(request, template, context)


@login_required
def marketing_overview(request):
    return _render_dashboard(
        request,
        "ads/marketing/overview.html",
        "overview",
        lambda advertiser: {
            "metrics": overview_metrics(advertiser),
            "campaigns": [serialize_campaign(campaign) for campaign in campaign_queryset(advertiser)[:6]],
        },
    )


@login_required
def marketing_campaigns(request):
    return _render_dashboard(
        request,
        "ads/marketing/campaigns.html",
        "campaigns",
        lambda advertiser: {
            "campaigns": [serialize_campaign(campaign) for campaign in campaign_queryset(advertiser)],
        },
    )


@login_required
def marketing_create_campaign(request):
    context = _dashboard_context(request, "create")
    if not context.get("dashboard_enabled") or context.get("access_denied"):
        return render(request, "ads/marketing/create_campaign.html", context)
    advertiser = context["advertiser"]
    if request.method == "POST":
        try:
            campaign, _asset = create_campaign(advertiser, request.POST, submit=request.POST.get("submit") == "1")
            return redirect("ads:marketing_campaign_detail", campaign_id=campaign.pk)
        except (AdvertiserAccessError, AdvertiserValidationError) as exc:
            context["form_error"] = str(exc)
    context.update(
        {
            "asset_options": owned_asset_options(advertiser),
            "placements": AdPlacement.objects.filter(is_active=True).order_by("priority", "name"),
            "objectives": AdCampaign.OBJECTIVE_CHOICES,
            "campaign_statuses": AdCampaign.STATUS_CHOICES,
        }
    )
    return render(request, "ads/marketing/create_campaign.html", context)


@login_required
def marketing_campaign_detail(request, campaign_id):
    return _render_dashboard(
        request,
        "ads/marketing/campaign_detail.html",
        "campaigns",
        lambda advertiser: {
            "campaign": serialize_campaign(get_object_or_404(campaign_queryset(advertiser), pk=campaign_id)),
        },
    )


@login_required
def marketing_assets(request):
    return _render_dashboard(
        request,
        "ads/marketing/assets.html",
        "assets",
        lambda advertiser: {"asset_options": owned_asset_options(advertiser)},
    )


@login_required
def marketing_creatives(request):
    context = _dashboard_context(request, "creatives")
    if not context.get("dashboard_enabled") or context.get("access_denied"):
        return render(request, "ads/marketing/creatives.html", context)
    advertiser = context["advertiser"]
    if request.method == "POST":
        try:
            create_creative(advertiser, request.POST)
            return redirect("ads:marketing_creatives")
        except (AdvertiserAccessError, AdvertiserValidationError) as exc:
            context["form_error"] = str(exc)
    context.update(
        {
            "creatives": creative_queryset(advertiser),
            "campaigns": campaign_queryset(advertiser),
        }
    )
    return render(request, "ads/marketing/creatives.html", context)


@login_required
def marketing_placements(request):
    return _render_dashboard(
        request,
        "ads/marketing/placements.html",
        "placements",
        {"placements": AdPlacement.objects.filter(is_active=True).order_by("priority", "name")},
    )


@login_required
def marketing_connected_accounts(request):
    return _render_dashboard(
        request,
        "ads/marketing/connected_accounts.html",
        "connected",
        lambda advertiser: {"accounts": connected_account_shells(advertiser)},
    )


@login_required
def marketing_connected_account_select(request, provider):
    context = _dashboard_context(request, "connected")
    if not context.get("dashboard_enabled") or context.get("access_denied"):
        return render(request, "ads/marketing/connected_account_select.html", context)
    pending = request.session.get("ads_pending_account_selection") or {}
    if pending.get("provider") != provider:
        context["selection_error"] = "No pending account connection was found. Start the connection again."
        return render(request, "ads/marketing/connected_account_select.html", context, status=400)
    try:
        account = ExternalAdvertisingAccount.objects.get(
            pk=int(pending.get("connection_id")),
            advertiser_identity=context["advertiser"],
            channel=provider,
            status=ExternalAdvertisingAccount.STATUS_PENDING,
        )
    except (TypeError, ValueError, ExternalAdvertisingAccount.DoesNotExist):
        context["selection_error"] = "The pending account connection is unavailable or no longer valid."
        return render(request, "ads/marketing/connected_account_select.html", context, status=400)
    context.update({
        "provider": provider,
        "connection_id": account.pk,
        "discovered_accounts": (account.metadata or {}).get("discovered_accounts", []),
    })
    return render(request, "ads/marketing/connected_account_select.html", context)


@login_required
def marketing_analytics(request):
    return _render_dashboard(
        request,
        "ads/marketing/analytics.html",
        "analytics",
        lambda advertiser: {
            "metrics": overview_metrics(advertiser),
            "campaigns": [serialize_campaign(campaign) for campaign in campaign_queryset(advertiser)],
        },
    )


@login_required
def marketing_billing(request):
    return _render_dashboard(request, "ads/marketing/billing.html", "billing")


@login_required
def marketing_settings(request):
    return _render_dashboard(request, "ads/marketing/settings.html", "settings")


def _json_tracking_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        return {}


def _tracking_ad(data):
    ad_id = data.get('ad_id')

    try:
        ad_id = int(ad_id)
    except (TypeError, ValueError):
        return None

    if ad_id <= 0:
        return None

    return AdBanner.objects.select_related('campaign').filter(id=ad_id).first()


def _ignored_tracking_response(message='Tracking ping ignored'):
    return JsonResponse({
        'success': True,
        'ignored': True,
        'message': message,
    })


def _legacy_click_cost(campaign):
    if campaign.campaign_type == 'cpc':
        return campaign.max_bid or Decimal("0")
    return Decimal("0")


def _legacy_impression_cost(campaign):
    # The current model has no CPM price field. Do not invent spend for views.
    return Decimal("0")


def test_ads(request):
    """Test page for ads"""
    banners = AdBanner.objects.filter(is_active=True).select_related('campaign', 'placement')
    placements = AdPlacement.objects.filter(is_active=True)
    
    # Get statistics
    total_impressions = AdImpression.objects.count()
    total_clicks = AdClick.objects.count()
    ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
    
    context = {
        'banners': banners,
        'placements': placements,
        'media_url': settings.MEDIA_URL,
        'media_root': settings.MEDIA_ROOT,
        'total_banners': banners.count(),
        'total_placements': placements.count(),
        'total_impressions': total_impressions,
        'total_clicks': total_clicks,
        'ctr': round(ctr, 2),
    }
    return render(request, 'ads/test.html', context)

@csrf_exempt
@require_POST
def track_click(request):
    """Track ad clicks"""
    try:
        data = _json_tracking_body(request)
        ad = _tracking_ad(data)
        if not ad:
            return _ignored_tracking_response('Ad click ignored: missing or invalid ad')

        campaign = ad.campaign
        
        # Create click record
        AdClick.objects.create(
            banner=ad,
            campaign=campaign,
            user=request.user if request.user.is_authenticated else None,
            session_id=request.session.session_key or '',
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
        )
        
        # Update click counts
        ad.clicks += 1
        ad.save()
        
        campaign.clicks += 1
        campaign.spent += _legacy_click_cost(campaign)
        campaign.save()
        
        logger.info(f"Ad click tracked: {ad.title} - Campaign: {campaign.name}")
        
        return JsonResponse({'success': True, 'message': 'Click tracked'})
    except Exception as e:
        logger.error(f"Error tracking ad click: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@csrf_exempt
@require_POST
def track_view(request):
    """Track ad views (impressions)"""
    try:
        data = _json_tracking_body(request)
        ad = _tracking_ad(data)
        if not ad:
            return _ignored_tracking_response('Ad impression ignored: missing or invalid ad')

        campaign = ad.campaign
        
        # Check if already tracked for this session (avoid duplicates)
        session_id = request.session.session_key or ''
        if session_id:
            existing = AdImpression.objects.filter(
                banner=ad,
                session_id=session_id,
                timestamp__date=timezone.now().date()
            ).exists()
            
            if existing:
                return JsonResponse({'success': True, 'message': 'Already tracked'})
        
        # Create impression record
        AdImpression.objects.create(
            banner=ad,
            campaign=campaign,
            user=request.user if request.user.is_authenticated else None,
            session_id=session_id,
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
        )
        
        # Update impression counts
        ad.impressions += 1
        ad.save()
        
        campaign.impressions += 1
        campaign.spent += _legacy_impression_cost(campaign)
        campaign.save()
        
        logger.info(f"Ad impression tracked: {ad.title}")
        
        return JsonResponse({'success': True, 'message': 'Impression tracked'})
    except Exception as e:
        logger.error(f"Error tracking ad impression: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@require_GET
def ad_stats(request, ad_id):
    """Get statistics for a specific ad"""
    try:
        ad = AdBanner.objects.select_related('campaign', 'placement').get(id=ad_id)
        
        # Get daily stats for the last 30 days
        from django.db.models import Count, Sum
        from datetime import timedelta
        
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=30)
        
        impressions_by_day = AdImpression.objects.filter(
            banner=ad,
            timestamp__date__gte=start_date
        ).extra({'date': "date(timestamp)"}).values('date').annotate(
            count=Count('id')
        ).order_by('date')
        
        clicks_by_day = AdClick.objects.filter(
            banner=ad,
            timestamp__date__gte=start_date
        ).extra({'date': "date(timestamp)"}).values('date').annotate(
            count=Count('id')
        ).order_by('date')
        
        stats = {
            'success': True,
            'ad_id': ad.id,
            'title': ad.title,
            'campaign': ad.campaign.name,
            'placement': ad.placement.name if ad.placement else None,
            'total_impressions': ad.impressions,
            'total_clicks': ad.clicks,
            'ctr': round((ad.clicks / ad.impressions * 100) if ad.impressions > 0 else 0, 2),
            'daily_impressions': list(impressions_by_day),
            'daily_clicks': list(clicks_by_day),
        }
        
        return JsonResponse(stats)
    except AdBanner.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Ad not found'}, status=404)

@require_GET
def ad_performance(request):
    """Get overall ad performance dashboard"""
    from django.db.models import Sum, Avg, Q
    
    # Get all active ads
    active_ads = AdBanner.objects.filter(is_active=True)
    
    # Calculate totals
    total_impressions = active_ads.aggregate(total=Sum('impressions'))['total'] or 0
    total_clicks = active_ads.aggregate(total=Sum('clicks'))['total'] or 0
    avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
    
    # Get top performing ads
    top_ads = active_ads.order_by('-clicks')[:10]
    top_ctr_ads = sorted(active_ads, key=lambda x: x.ctr, reverse=True)[:10]
    
    # Get totals by placement
    placement_stats = []
    for placement in AdPlacement.objects.filter(is_active=True):
        ads_in_placement = active_ads.filter(placement=placement)
        imp = ads_in_placement.aggregate(total=Sum('impressions'))['total'] or 0
        clk = ads_in_placement.aggregate(total=Sum('clicks'))['total'] or 0
        placement_stats.append({
            'name': placement.name,
            'impressions': imp,
            'clicks': clk,
            'ctr': round((clk / imp * 100) if imp > 0 else 0, 2)
        })
    
    data = {
        'success': True,
        'total_ads': active_ads.count(),
        'total_impressions': total_impressions,
        'total_clicks': total_clicks,
        'avg_ctr': round(avg_ctr, 2),
        'top_ads': [{'id': ad.id, 'title': ad.title, 'clicks': ad.clicks, 'ctr': ad.ctr} for ad in top_ads],
        'top_ctr_ads': [{'id': ad.id, 'title': ad.title, 'clicks': ad.clicks, 'ctr': round(ad.ctr, 2)} for ad in top_ctr_ads if ad.ctr > 0],
        'placement_stats': placement_stats,
    }
    
    return JsonResponse(data)

def force_create_images(request):
    """Force create images for all banners"""
    from django.core.files.base import ContentFile
    from PIL import Image, ImageDraw, ImageFont
    from io import BytesIO
    import os
    
    # Ensure media directory exists
    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
    os.makedirs(os.path.join(settings.MEDIA_ROOT, 'ads', 'banners'), exist_ok=True)
    
    banners = AdBanner.objects.filter(is_active=True)
    created = 0
    
    for banner in banners:
        width = banner.placement.width if banner.placement else 300
        height = banner.placement.height if banner.placement else 250
        
        # Create gradient background
        img = Image.new('RGB', (width, height))
        pixels = img.load()
        
        # Generate gradient
        for y in range(height):
            ratio = y / height
            r = int(59 * (1 - ratio) + 37 * ratio)
            g = int(130 * (1 - ratio) + 99 * ratio)
            b = int(246 * (1 - ratio) + 235 * ratio)
            for x in range(width):
                pixels[x, y] = (r, g, b)
        
        draw = ImageDraw.Draw(img)
        
        # Try to use a font, fallback to default
        try:
            font_title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
            font_text = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
        except:
            font_title = ImageFont.load_default()
            font_text = ImageFont.load_default()
        
        # Draw title
        title = banner.title[:20]
        bbox = draw.textbbox((0, 0), title, font=font_title)
        text_width = bbox[2] - bbox[0]
        draw.text(((width - text_width) // 2, height // 4), title, fill=(255, 255, 255), font=font_title)
        
        # Draw description
        desc = banner.description[:40] if banner.description else "Special Offer Just for You"
        bbox = draw.textbbox((0, 0), desc, font=font_text)
        text_width = bbox[2] - bbox[0]
        draw.text(((width - text_width) // 2, height // 2 - 20), desc, fill=(255, 255, 255), font=font_text)
        
        # Draw button
        button_text = banner.cta_text[:15]
        bbox = draw.textbbox((0, 0), button_text, font=font_text)
        text_width = bbox[2] - bbox[0]
        button_width = text_width + 40
        button_height = 40
        button_x = (width - button_width) // 2
        button_y = int(height * 0.7)
        
        # Draw button background
        draw.rectangle([button_x, button_y, button_x + button_width, button_y + button_height], 
                       fill=(255, 255, 255))
        
        # Draw button text
        draw.text(((width - text_width) // 2, button_y + 12), button_text, fill=(59, 130, 246), font=font_text)
        
        # Save to buffer
        buffer = BytesIO()
        img.save(buffer, format='JPEG', quality=85)
        buffer.seek(0)
        
        # Save to banner
        filename = f"banner_{banner.id}.jpg"
        if banner.image:
            banner.image.delete(save=False)
        banner.image.save(filename, ContentFile(buffer.read()), save=True)
        created += 1
        print(f"✅ Created image for {banner.title}")
    
    return JsonResponse({'created': created, 'message': f'Created {created} images'})

@csrf_exempt
@require_POST
def ajax_get_ad(request):
    """Get ad via AJAX for dynamic loading"""
    try:
        data = json.loads(request.body)
        placement_slug = data.get('placement', 'sidebar')
        count = data.get('count', 1)
        
        from .templatetags.ad_tags import render_ad
        from django.template import Template, Context
        from django.template.loader import get_template
        
        # Get ads for placement
        placement = AdPlacement.objects.get(slug=placement_slug, is_active=True)
        now = timezone.now()
        
        banners = AdBanner.objects.filter(
            placement=placement,
            is_active=True,
            campaign__status='active',
            campaign__approved=True,
            campaign__start_date__lte=now
        ).exclude(
            campaign__end_date__isnull=False,
            campaign__end_date__lt=now
        ).select_related('campaign', 'placement')[:count]
        
        # Render each ad
        import random
        banners = list(banners)
        random.shuffle(banners)
        
        ads_html = []
        for ad in banners:
            template = get_template('ads/banner.html')
            html = template.render({'ads': [ad], 'request': request})
            ads_html.append(html)
        
        return JsonResponse({
            'success': True,
            'ads': ads_html,
            'count': len(ads_html)
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def force_create_images_view(request):
    """Wrapper for force_create_images"""
    return force_create_images(request)

# Export views
__all__ = [
    'test_ads', 'track_click', 'track_view', 'ad_stats', 
    'ad_performance', 'force_create_images', 'ajax_get_ad',
    'force_create_images_view'
]
