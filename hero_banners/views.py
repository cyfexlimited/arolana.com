from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db.models import Q
from django.utils import timezone

import json

from .models import HeroBanner, HeroBannerAnalytics


# ============================================================
# Active banner selector
# ============================================================


def get_active_banners(
    request=None,
    *,
    placement=HeroBanner.PLACEMENT_HOME,
    brand=None,
):
    """
    Return active banners for the requested placement.

    Handles:
    - active/inactive status
    - start/end scheduling
    - homepage banners
    - brand directory banners
    - individual brand-detail banners
    """

    now = timezone.now()

    banners = (
        HeroBanner.objects
        .filter(
            is_active=True,
            placement=placement,
        )
        .filter(
            Q(start_date__isnull=True)
            | Q(start_date__lte=now),
            Q(end_date__isnull=True)
            | Q(end_date__gte=now),
        )
    )

    # --------------------------------------------------------
    # Brand-detail banners must belong to a specific brand.
    # --------------------------------------------------------

    if placement == HeroBanner.PLACEMENT_BRAND_DETAIL:
        if brand is None:
            return banners.none()

        banners = banners.filter(
            brand=brand,
        )

    # --------------------------------------------------------
    # Homepage and brand-directory banners must not be
    # accidentally targeted at an individual brand.
    # --------------------------------------------------------

    else:
        banners = banners.filter(
            brand__isnull=True,
        )

    return banners.order_by(
        "display_order",
        "-created_at",
    )


# ============================================================
# Banner view tracking
# ============================================================


@csrf_exempt
@require_POST
def track_banner_view(request):
    """Track banner views."""

    try:
        data = json.loads(request.body)

        banner_id = data.get("banner_id")

        banner = HeroBanner.objects.get(
            id=banner_id,
        )

        banner.increment_view()

        HeroBannerAnalytics.objects.create(
            banner=banner,
            session_id=request.session.session_key,
            user=(
                request.user
                if request.user.is_authenticated
                else None
            ),
            action="view",
        )

        return JsonResponse(
            {
                "success": True,
            }
        )

    except Exception as exc:
        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            }
        )


# ============================================================
# Banner click tracking
# ============================================================


@csrf_exempt
@require_POST
def track_banner_click(request):
    """Track banner clicks."""

    try:
        data = json.loads(request.body)

        banner_id = data.get("banner_id")

        banner = HeroBanner.objects.get(
            id=banner_id,
        )

        banner.increment_click()

        HeroBannerAnalytics.objects.create(
            banner=banner,
            session_id=request.session.session_key,
            user=(
                request.user
                if request.user.is_authenticated
                else None
            ),
            action="click",
        )

        return JsonResponse(
            {
                "success": True,
            }
        )

    except Exception as exc:
        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            }
        )