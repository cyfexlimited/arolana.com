"""Shared video-commerce feed selection and serialization.

This module is the single business-logic layer used by product-detail web
pages and mobile clients.  It deliberately normalizes existing moderated
marketplace sources instead of copying videos into a new feed table.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from django.db.models import Count, Q
from django.utils import timezone

from .models import ProductVideo


def _file_url(field):
    try:
        return field.url if field else ""
    except Exception:
        return ""


def _absolute(request, value):
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    return request.build_absolute_uri(value) if request else value


def _youtube_id(value):
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        parsed = urlparse(value if "://" in value else f"https://youtu.be/{value}")
    except ValueError:
        return ""
    host = parsed.netloc.lower().replace("www.", "")
    parts = [part for part in parsed.path.split("/") if part]
    candidate = ""
    if host == "youtu.be" and parts:
        candidate = parts[0]
    elif "youtube.com" in host:
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        if not candidate and len(parts) > 1 and parts[0] in {"embed", "shorts", "live"}:
            candidate = parts[1]
    return candidate if candidate and all(char.isalnum() or char in "-_" for char in candidate) else ""


def _video_source_payload(request, source, url, thumbnail=""):
    source = str(source or "").lower()
    url = str(url or "").strip()
    youtube_id = _youtube_id(url) if source == "youtube" or "youtu" in url.lower() else ""
    if youtube_id:
        return {
            "video_type": "youtube",
            "video_url": f"https://www.youtube.com/watch?v={youtube_id}",
            "embed_url": f"https://www.youtube.com/embed/{youtube_id}?playsinline=1&rel=0&modestbranding=1&enablejsapi=1",
            "poster_url": _absolute(request, thumbnail) or f"https://img.youtube.com/vi/{youtube_id}/hqdefault.jpg",
        }
    if source in {"vimeo", "external"} and "vimeo.com" in url.lower():
        video_id = next((part for part in reversed(urlparse(url).path.split("/")) if part.isdigit()), "")
        return {
            "video_type": "vimeo",
            "video_url": url,
            "embed_url": f"https://player.vimeo.com/video/{video_id}?playsinline=1" if video_id else "",
            "poster_url": _absolute(request, thumbnail),
        }
    return {
        "video_type": "local" if url else source or "local",
        "video_url": _absolute(request, url),
        "embed_url": "",
        "poster_url": _absolute(request, thumbnail),
    }


def _vendor_for_video(video):
    if video.vendor_id:
        return video.vendor
    user = getattr(video.product, "vendor", None)
    return getattr(user, "vendor_profile", None) if user else None


def _vendor_owner(profile):
    if not profile:
        return {
            "id": None,
            "name": "Arolana Seller",
            "owner_type": "vendor",
            "verified": False,
            "location": "",
        }
    location = getattr(profile, "location_label", "") or ", ".join(
        value for value in [getattr(profile, "city", ""), getattr(profile, "state", "")] if value
    )
    owner_type = "manufacturer" if getattr(profile, "vendor_type", "") == "manufacturer" else "vendor"
    return {
        "id": profile.pk,
        "name": getattr(profile, "store_name", "") or getattr(profile, "company_name", "") or "Arolana Seller",
        "owner_type": owner_type,
        "verified": bool(getattr(profile, "is_verified", False) or getattr(profile, "manufacturer_verified", False)),
        "location": location,
    }


def _product_card(request, video, context_product_id=None, context_category_id=None):
    product = video.product
    owner = _vendor_owner(_vendor_for_video(video))
    media = _video_source_payload(
        request,
        video.source,
        video.youtube_url or video.vimeo_url or _file_url(video.local_video),
        _file_url(video.thumbnail) or _file_url(product.main_image),
    )
    compare_price = getattr(product, "compare_price", None) or getattr(product, "old_price", None)
    rating = getattr(product, "rating_avg", None) or getattr(product, "average_rating", None) or 0
    category_id = getattr(product, "category_id", None)
    relevance = 60 if context_category_id and category_id == context_category_id else 0
    if context_product_id and product.pk == context_product_id:
        relevance += 35
    return {
        "id": f"product:{video.pk}",
        "source_id": video.pk,
        "product_video_id": video.pk,
        "content_type": "product",
        **media,
        "title": video.title or product.name,
        "description": video.description or getattr(product, "short_description", "") or "",
        "price": str(product.price) if product.price is not None else "",
        "compare_price": str(compare_price) if compare_price else "",
        "currency": getattr(product, "currency", "") or "NGN",
        "owner": owner,
        "rating": float(rating or 0),
        "rating_count": int(getattr(product, "rating_count", 0) or 0),
        "video_rating": float(video.average_rating or 0),
        "video_rating_count": int(video.rating_count or 0),
        "comment_count": int(getattr(video, "comment_count", 0) or 0),
        "sold_count": int(getattr(product, "sold_count", 0) or getattr(product, "total_sold", 0) or 0),
        "cta": {
            "label": "View Product",
            "url": _absolute(request, product.get_absolute_url()),
        },
        "product": {
            "id": product.pk,
            "name": product.name,
            "slug": product.slug,
        },
        "service": None,
        "sponsored": False,
        "created_at": video.created_at.isoformat() if getattr(video, "created_at", None) else "",
        "_owner_key": f"{owner['owner_type']}:{owner['id'] or 'arolana'}",
        "_content_key": f"product:{product.pk}",
        "_score": 100 + relevance + (20 if owner["verified"] else 0) + min(int(video.views_count or 0), 1000) / 100,
    }


def _provider_type_label(value):
    labels = {
        "installer": "Installer",
        "repair_engineer": "Repair Engineer",
        "maintenance_technician": "Maintenance Technician",
        "av_engineer": "Setup/Configuration Specialist",
        "cctv_security_installer": "Installer",
        "network_engineer": "Setup/Configuration Specialist",
        "smart_home_installer": "Installer",
        "projector_technician": "Repair Engineer",
        "trainer": "Trainer",
        "consultant": "Consultant",
    }
    return labels.get(value, str(value or "Service Professional").replace("_", " ").title())


def _service_media_cards(request, context_category_id=None):
    from installers.models import ServiceProjectMedia

    queryset = (
        ServiceProjectMedia.objects.filter(
            media_type=ServiceProjectMedia.TYPE_VIDEO,
            approval_status=ServiceProjectMedia.STATUS_APPROVED,
            is_active=True,
            project__approval_status="approved",
            project__is_active=True,
            project__provider__verification_status__in=["verified", "approved"],
        )
        .select_related("project", "project__provider", "project__service_category")
        .order_by("-is_featured", "-created_at")[:48]
    )
    cards = []
    for media_item in queryset:
        project = media_item.project
        provider = project.provider
        playable = media_item.playable_video
        source_url = _file_url(playable) or media_item.external_video_url
        source = "local" if playable else ("youtube" if "youtu" in source_url.lower() else "vimeo" if "vimeo" in source_url.lower() else "external")
        media = _video_source_payload(
            request,
            source,
            source_url,
            _file_url(media_item.thumbnail) or _file_url(project.video_thumbnail) or _file_url(project.image),
        )
        if not media["video_url"] and not media["embed_url"]:
            continue
        location = project.location_display or ", ".join(
            value for value in [project.city, project.state, project.country] if value
        )
        provider_type = _provider_type_label(provider.provider_type)
        verified = provider.verification_status in {"verified", "approved"}
        owner = {
            "id": provider.pk,
            "name": provider.business_name,
            "owner_type": "provider",
            "provider_type": provider_type,
            "verified": verified,
            "location": location,
        }
        price = project.project_value_min if project.show_project_value else None
        category_id = project.service_category_id
        relevance = 30 if context_category_id and category_id == context_category_id else 0
        cards.append({
            "id": f"service:{media_item.pk}",
            "source_id": media_item.pk,
            "service_media_id": media_item.pk,
            "content_type": "service",
            **media,
            "title": media_item.caption or project.title,
            "description": project.short_summary or project.description,
            "price": str(price) if price is not None else "",
            "compare_price": "",
            "currency": project.project_value_currency or "NGN",
            "price_label": "Starting from" if price is not None else "Quote required",
            "owner": owner,
            "rating": float(provider.average_rating or 0),
            "rating_count": int(getattr(provider, "total_reviews", 0) or 0),
            "video_rating": 0,
            "video_rating_count": 0,
            "comment_count": 0,
            "sold_count": 0,
            "cta": {
                "label": "View Service",
                "url": _absolute(request, project.get_absolute_url()),
            },
            "product": None,
            "service": {
                "id": project.pk,
                "slug": project.slug,
                "provider_type": provider_type,
            },
            "sponsored": False,
            "created_at": media_item.created_at.isoformat(),
            "_owner_key": f"provider:{provider.pk}",
            "_content_key": f"service:{project.pk}",
            "_score": 85 + relevance + (25 if verified else 0) + float(provider.average_rating or 0) * 2,
        })
    return cards


def _campaign_matches_request(campaign, request):
    user = getattr(request, "user", None)
    authenticated = bool(user and getattr(user, "is_authenticated", False))
    targeting = str(campaign.targeting or "all")
    if targeting == "logged_in" and not authenticated:
        return False
    if targeting == "new" and authenticated:
        return False

    user_agent = str(getattr(request, "META", {}).get("HTTP_USER_AGENT", "") or "").lower()
    device = "tablet" if "ipad" in user_agent or "tablet" in user_agent else (
        "mobile" if any(marker in user_agent for marker in ("mobile", "android", "iphone")) else "desktop"
    )
    devices = [str(item).lower() for item in (campaign.device_targeting or [])]
    if devices and device not in devices:
        return False

    country = str(
        getattr(request, "META", {}).get("HTTP_CF_IPCOUNTRY", "")
        or getattr(request, "META", {}).get("HTTP_X_COUNTRY_CODE", "")
    ).upper()
    countries = [str(item).upper() for item in (campaign.geo_targeting or [])]
    if countries and country and country not in countries:
        return False
    return campaign.spent < campaign.total_budget


def _sponsored_cards(request):
    from ads.models import AdCreative

    now = timezone.now()
    queryset = (
        AdCreative.objects.filter(
            is_active=True,
            creative_type="video",
            campaign__is_active=True,
            campaign__approved=True,
            campaign__status="active",
            campaign__start_date__lte=now,
        )
        .filter(Q(campaign__end_date__isnull=True) | Q(campaign__end_date__gte=now))
        .filter(Q(campaign__campaign_type__in=["video", "sponsored"]) | Q(banners__placement__placement_type="video"))
        .exclude(video_url="")
        .select_related("campaign")
        .distinct()
        .order_by("-ab_weight", "-created_at")[:24]
    )
    cards = []
    for creative in queryset:
        if not _campaign_matches_request(creative.campaign, request):
            continue
        media = _video_source_payload(
            request,
            "youtube" if "youtu" in creative.video_url.lower() else "vimeo" if "vimeo" in creative.video_url.lower() else "local",
            creative.video_url,
            _file_url(creative.image) or _file_url(creative.image_mobile),
        )
        cards.append({
            "id": f"sponsored:{creative.pk}",
            "source_id": creative.pk,
            "ad_creative_id": creative.pk,
            "content_type": "sponsored",
            **media,
            "title": creative.headline or creative.name,
            "description": creative.description,
            "price": "",
            "compare_price": "",
            "currency": "NGN",
            "owner": {
                "id": creative.campaign_id,
                "name": creative.campaign.name,
                "owner_type": "sponsor",
                "verified": True,
                "location": "",
            },
            "rating": 0,
            "rating_count": 0,
            "video_rating": 0,
            "video_rating_count": 0,
            "comment_count": 0,
            "sold_count": 0,
            "cta": {
                "label": creative.cta_text or "Learn More",
                "url": creative.clickthrough_url,
            },
            "product": None,
            "service": None,
            "sponsored": True,
            "created_at": creative.created_at.isoformat(),
            "_owner_key": f"sponsor:{creative.campaign_id}",
            "_content_key": f"sponsored:{creative.pk}",
            "_score": 92 + min(int(creative.ab_weight or 0), 100) / 10,
        })
    return cards


def _diverse_order(candidates):
    """Rank candidates while avoiding repeated owners/products in each row."""
    remaining = sorted(candidates, key=lambda item: (-item["_score"], item["id"]))
    selected = []
    used_content = set()
    while remaining:
        row_owners = {item["_owner_key"] for item in selected[-2:]}
        index = next(
            (
                idx
                for idx, item in enumerate(remaining)
                if item["_content_key"] not in used_content and item["_owner_key"] not in row_owners
            ),
            None,
        )
        if index is None:
            index = next(
                (idx for idx, item in enumerate(remaining) if item["_content_key"] not in used_content),
                None,
            )
        if index is None:
            break
        item = remaining.pop(index)
        used_content.add(item["_content_key"])
        selected.append(item)
    return selected


def build_video_commerce_feed(
    request,
    *,
    product=None,
    category=None,
    include_services=True,
    include_sponsored=True,
    limit=12,
    offset=0,
):
    """Return normalized, public, moderated and owner-diverse feed cards."""
    product_id = getattr(product, "pk", None)
    category_id = getattr(category, "pk", None) or getattr(product, "category_id", None)
    product_queryset = (
        ProductVideo.objects.filter(
            is_active=True,
            moderation_status="approved",
            product__is_active=True,
            product__approval_status="approved",
        )
        .select_related("product", "product__vendor", "product__vendor__vendor_profile", "vendor")
        .annotate(
            comment_count=Count(
                "comments",
                filter=Q(comments__is_visible=True),
                distinct=True,
            )
        )
        .order_by("-created_at")[:60]
    )
    candidates = [
        _product_card(request, video, context_product_id=product_id, context_category_id=category_id)
        for video in product_queryset
    ]
    candidates = [item for item in candidates if item["video_url"] or item["embed_url"]]
    if include_services:
        candidates.extend(_service_media_cards(request, context_category_id=category_id))
    if include_sponsored:
        candidates.extend(_sponsored_cards(request))

    ordered = _diverse_order(candidates)
    page = ordered[max(0, offset):max(0, offset) + max(1, min(limit, 24))]
    for item in page:
        item.pop("_owner_key", None)
        item.pop("_content_key", None)
        item.pop("_score", None)
    return {
        "results": page,
        "count": len(ordered),
        "next_cursor": str(offset + len(page)) if offset + len(page) < len(ordered) else None,
    }
