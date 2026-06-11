from django.db.models import Case, F, IntegerField, Q, Value, When
from django.utils import timezone


SORT_ORDERS = {
    "newest": ("-created_at", "-id"),
    "best_selling": ("-sales_count", "-rating_avg", "-id"),
    "trending": ("-views_count", "-sales_count", "-rating_avg", "-id"),
    "top_rated": ("-rating_avg", "-rating_count", "-sales_count", "-id"),
    "featured": ("-is_featured", "-rating_avg", "-created_at", "-id"),
    "price_low": ("price", "-rating_avg", "-id"),
    "price_high": ("-price", "-rating_avg", "-id"),
}

SECTION_SORTS = {
    "featured": "featured",
    "new": "newest",
    "bestsellers": "best_selling",
    "trending": "trending",
    "custom": "featured",
}


def with_vendor_visibility_priority(queryset, homepage=False):
    """Annotate products with priority from a currently active vendor plan."""
    now = timezone.now()
    active_plan = Q(vendor__vendor_profile__subscription_active=True) & (
        Q(vendor__vendor_profile__subscription_expires_at__gt=now)
        | Q(
            vendor__vendor_profile__subscription_expires_at__isnull=True,
            vendor__vendor_profile__subscription_expiry__gt=now,
        )
    )
    if homepage:
        active_plan &= Q(vendor__vendor_profile__can_show_on_homepage=True)

    return queryset.annotate(
        vendor_visibility_priority=Case(
            When(
                active_plan,
                then=F("vendor__vendor_profile__priority_score"),
            ),
            default=Value(0),
            output_field=IntegerField(),
        )
    )


def order_products_for_visibility(
    queryset,
    sort_mode="automatic",
    section_type="",
    use_subscription_priority=True,
    homepage=False,
    relevance_first=False,
):
    """Apply deterministic storefront ordering with an active-plan boost."""
    resolved_sort = sort_mode
    if resolved_sort in {"", "automatic"}:
        resolved_sort = SECTION_SORTS.get(section_type, "featured")

    ordering = list(SORT_ORDERS.get(resolved_sort, SORT_ORDERS["featured"]))
    if use_subscription_priority:
        queryset = with_vendor_visibility_priority(queryset, homepage=homepage)
        ordering.insert(1 if relevance_first else 0, "-vendor_visibility_priority")

    return queryset.order_by(*ordering)


def order_storefront_products(
    queryset,
    *ordering,
    homepage=False,
    priority_position=1,
):
    """Add active-plan priority to an existing storefront sort order."""
    queryset = with_vendor_visibility_priority(queryset, homepage=homepage)
    resolved = list(ordering or ("-created_at", "-id"))
    insert_at = min(max(priority_position, 0), len(resolved))
    resolved.insert(insert_at, "-vendor_visibility_priority")
    if "-id" not in resolved and "id" not in resolved:
        resolved.append("-id")
    return queryset.order_by(*resolved)
