from products.models import Product, RecentlyViewed


GUEST_RECENTLY_VIEWED_KEY = "guest_recently_viewed_products"


class RecommendationEngine:
    """Central rule-based product recommendation service."""

    @staticmethod
    def _guest_recent_ids(request):
        values = request.session.get(
            GUEST_RECENTLY_VIEWED_KEY,
            [],
        )

        cleaned = []

        for value in values:
            try:
                product_id = int(value)
            except (TypeError, ValueError):
                continue

            if product_id not in cleaned:
                cleaned.append(product_id)

        return cleaned


    @classmethod
    def recent_product_ids(cls, request, limit=40):
        if request.user.is_authenticated:
            return list(
                RecentlyViewed.objects
                .filter(user=request.user)
                .values_list(
                    "product_id",
                    flat=True,
                )[:limit]
            )

        return cls._guest_recent_ids(request)[:limit]


    @classmethod
    def recent_products(cls, request, limit=40):
        product_ids = cls.recent_product_ids(
            request,
            limit=limit,
        )

        if not product_ids:
            return []

        products = (
            Product.objects
            .filter(
                id__in=product_ids,
                is_active=True,
                approval_status="approved",
            )
            .select_related(
                "category",
                "brand",
                "vendor",
            )
            .in_bulk()
        )

        return [
            products[product_id]
            for product_id in product_ids
            if product_id in products
        ]


    @classmethod
    def for_user(
        cls,
        request,
        limit=10,
        exclude_ids=None,
    ):
        limit = min(
            max(int(limit or 10), 1),
            40,
        )

        recent_products = cls.recent_products(
            request,
            limit=40,
        )

        recent_ids = {
            product.id
            for product in recent_products
        }

        excluded = set(exclude_ids or [])
        excluded.update(recent_ids)

        category_ids = {
            product.category_id
            for product in recent_products
            if product.category_id
        }

        brand_ids = {
            product.brand_id
            for product in recent_products
            if product.brand_id
        }

        base_queryset = (
            Product.objects
            .filter(
                is_active=True,
                approval_status="approved",
            )
            .exclude(
                id__in=excluded,
            )
            .select_related(
                "category",
                "brand",
                "vendor",
            )
        )

        personalized = base_queryset.none()

        if category_ids:
            personalized = base_queryset.filter(
                category_id__in=category_ids,
            )

        elif brand_ids:
            personalized = base_queryset.filter(
                brand_id__in=brand_ids,
            )

        recommendations = list(
            personalized.order_by(
                "-is_featured",
                "-sales_count",
                "-rating_avg",
                "-rating_count",
                "-created_at",
            )[:limit]
        )

        if len(recommendations) >= limit:
            return recommendations

        used_ids = excluded.union(
            product.id
            for product in recommendations
        )

        fallback = (
            Product.objects
            .filter(
                is_active=True,
                approval_status="approved",
            )
            .exclude(
                id__in=used_ids,
            )
            .select_related(
                "category",
                "brand",
                "vendor",
            )
            .order_by(
                "-is_featured",
                "-sales_count",
                "-rating_avg",
                "-rating_count",
                "-created_at",
            )[
                :limit - len(recommendations)
            ]
        )

        recommendations.extend(fallback)

        return recommendations