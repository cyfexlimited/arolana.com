import re

from django.contrib.auth import get_user_model
from django.db.models import Q

from notifications.models import Notification

from .models import ServiceCategory, ServiceProviderProfile


def _product_category_ids(product):
    category = getattr(product, "category", None)
    ids = set()
    while category:
        ids.add(category.id)
        category = getattr(category, "parent", None)
    return ids


def _product_search_text(product):
    values = [
        getattr(product, "name", ""),
        getattr(product, "description", ""),
        getattr(product, "specifications", ""),
        getattr(product, "meta_keywords", ""),
        getattr(getattr(product, "category", None), "name", ""),
        getattr(getattr(product, "brand", None), "name", ""),
    ]
    return re.sub(r"<[^>]+>", " ", " ".join(str(value or "") for value in values)).lower()


def suggested_categories_for_product(product, limit=6):
    active = ServiceCategory.objects.filter(is_active=True).prefetch_related("product_categories")
    category_ids = _product_category_ids(product)
    explicit = list(active.filter(product_categories__id__in=category_ids).distinct())
    if len(explicit) >= limit:
        return explicit[:limit]

    text = _product_search_text(product)
    matched_ids = {item.id for item in explicit}
    keyword_matches = []
    for category in active.exclude(id__in=matched_ids):
        if any(keyword in text for keyword in category.keywords):
            keyword_matches.append(category)
            if len(explicit) + len(keyword_matches) >= limit:
                break
    return (explicit + keyword_matches)[:limit]


def suggested_providers_for_product(product, limit=6):
    categories = suggested_categories_for_product(product)
    if not categories:
        return ServiceProviderProfile.objects.none()
    return (
        ServiceProviderProfile.objects.public()
        .filter(services__is_active=True, services__category__in=categories)
        .select_related("user")
        .prefetch_related("services__category")
        .distinct()
        .order_by("-average_rating", "-total_completed_jobs")[:limit]
    )


def filter_public_providers(params):
    queryset = (
        ServiceProviderProfile.objects.public()
        .select_related("user")
        .prefetch_related("services__category")
        .distinct()
    )
    filters = {
        "country": "country__iexact",
        "state": "state__iexact",
        "city": "city__iexact",
        "provider_type": "provider_type",
    }
    for parameter, lookup in filters.items():
        value = str(params.get(parameter, "")).strip()
        if value:
            queryset = queryset.filter(**{lookup: value})
    category = str(params.get("category", "")).strip()
    if category:
        queryset = queryset.filter(services__category__slug=category, services__is_active=True)
    rating = str(params.get("rating", "")).strip()
    if rating:
        try:
            queryset = queryset.filter(average_rating__gte=float(rating))
        except ValueError:
            pass
    query = str(params.get("q", "")).strip()
    if query:
        queryset = queryset.filter(
            Q(business_name__icontains=query)
            | Q(description__icontains=query)
            | Q(city__icontains=query)
            | Q(state__icontains=query)
            | Q(services__service_name__icontains=query)
            | Q(services__category__name__icontains=query)
        )
    return queryset.distinct()


def notify_staff_provider_registration(provider):
    staff = get_user_model().objects.filter(is_active=True).filter(Q(is_staff=True) | Q(is_superuser=True)).distinct()
    Notification.bulk_create(
        staff,
        "system",
        "Service provider registration pending",
        f"{provider.business_name} submitted a {provider.get_provider_type_display()} profile for verification.",
        link="/admin/installers/serviceproviderprofile/",
        metadata={"service_provider_id": provider.id},
    )


def notify_staff_service_quote(quote):
    staff = get_user_model().objects.filter(is_active=True).filter(Q(is_staff=True) | Q(is_superuser=True)).distinct()
    Notification.bulk_create(
        staff,
        "message",
        "New service quote request",
        f"{quote.name} requested {quote.service_needed} in {quote.city}, {quote.state}.",
        link="/admin/installers/servicequoterequest/",
        metadata={"service_quote_request_id": quote.id, "product_id": quote.product_id},
    )
