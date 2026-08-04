from decimal import Decimal, InvalidOperation

from products.models import Product, RecentlyViewed


GUEST_RECENTLY_VIEWED_KEY = "guest_recently_viewed_products"


class RecommendationEngine:
    """Central rule-based product recommendation service."""

    CATEGORY_WEIGHT = 50
    BRAND_WEIGHT = 30
    VENDOR_WEIGHT = 10
    FEATURED_WEIGHT = 15
    PRICE_SIMILARITY_WEIGHT = 25
    IN_STOCK_WEIGHT = 12
    NEW_PRODUCT_WEIGHT = 6

    MAX_RECENT_ITEMS = 40
    MAX_CANDIDATES = 200
    MAX_RESULTS = 40

    @staticmethod
    def _safe_decimal(value):
        try:
            return Decimal(str(value or 0))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

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
    def _normalize_limit(
        cls,
        limit,
        default=10,
    ):
        try:
            value = int(limit or default)
        except (TypeError, ValueError):
            value = default

        return min(
            max(value, 1),
            cls.MAX_RESULTS,
        )

    @classmethod
    def _base_queryset(cls):
        return (
            Product.objects
            .filter(
                is_active=True,
                approval_status="approved",
            )
            .select_related(
                "category",
                "brand",
                "vendor",
            )
        )

    @classmethod
    def recent_product_ids(
        cls,
        request,
        limit=40,
    ):
        limit = cls._normalize_limit(
            limit,
            default=cls.MAX_RECENT_ITEMS,
        )

        if request.user.is_authenticated:
            return list(
                RecentlyViewed.objects
                .filter(user=request.user)
                .values_list(
                    "product_id",
                    flat=True,
                )[:limit]
            )

        return cls._guest_recent_ids(
            request,
        )[:limit]

    @classmethod
    def recent_products(
        cls,
        request,
        limit=40,
    ):
        product_ids = cls.recent_product_ids(
            request=request,
            limit=limit,
        )

        if not product_ids:
            return []

        products = (
            cls._base_queryset()
            .filter(id__in=product_ids)
            .in_bulk()
        )

        return [
            products[product_id]
            for product_id in product_ids
            if product_id in products
        ]

    @classmethod
    def _price_similarity_score(
        cls,
        source_product,
        candidate,
    ):
        source_price = cls._safe_decimal(
            source_product.price,
        )
        candidate_price = cls._safe_decimal(
            candidate.price,
        )

        if source_price <= 0 or candidate_price <= 0:
            return 0

        difference = abs(
            candidate_price - source_price,
        )
        ratio = difference / source_price

        if ratio <= Decimal("0.10"):
            return cls.PRICE_SIMILARITY_WEIGHT

        if ratio <= Decimal("0.20"):
            return 18

        if ratio <= Decimal("0.35"):
            return 10

        if ratio <= Decimal("0.50"):
            return 5

        return 0

    @classmethod
    def score_product(
        cls,
        source_product,
        candidate,
    ):
        score = 0
        reasons = []

        if (
            source_product.category_id
            and source_product.category_id
            == candidate.category_id
        ):
            score += cls.CATEGORY_WEIGHT
            reasons.append("Same category")

        if (
            source_product.brand_id
            and source_product.brand_id
            == candidate.brand_id
        ):
            score += cls.BRAND_WEIGHT
            reasons.append("Same brand")

        if (
            source_product.vendor_id
            and source_product.vendor_id
            == candidate.vendor_id
        ):
            score += cls.VENDOR_WEIGHT
            reasons.append("Same vendor")

        price_score = cls._price_similarity_score(
            source_product,
            candidate,
        )

        if price_score:
            score += price_score
            reasons.append("Similar price")

        if candidate.is_featured:
            score += cls.FEATURED_WEIGHT
            reasons.append("Featured")

        if getattr(candidate, "is_in_stock", False):
            score += cls.IN_STOCK_WEIGHT
            reasons.append("In stock")

        if getattr(candidate, "is_new", False):
            score += cls.NEW_PRODUCT_WEIGHT
            reasons.append("New arrival")

        score += min(
            int(candidate.sales_count or 0),
            100,
        )

        score += int(
            float(candidate.rating_avg or 0) * 10
        )

        score += min(
            int(candidate.rating_count or 0),
            50,
        )

        return {
            "product": candidate,
            "score": score,
            "reasons": reasons,
            "reason": reasons[0] if reasons else "Popular choice",
        }

    @classmethod
    def similar_products(
        cls,
        product,
        limit=8,
        include_scores=False,
    ):
        limit = cls._normalize_limit(
            limit,
            default=8,
        )

        candidates = list(
            cls._base_queryset()
            .exclude(pk=product.pk)
            .order_by(
                "-is_featured",
                "-sales_count",
                "-rating_avg",
                "-rating_count",
                "-created_at",
            )[:cls.MAX_CANDIDATES]
        )

        ranked = sorted(
            (
                cls.score_product(
                    product,
                    candidate,
                )
                for candidate in candidates
            ),
            key=lambda item: item["score"],
            reverse=True,
        )

        ranked = ranked[:limit]

        if include_scores:
            return ranked

        return [
            item["product"]
            for item in ranked
        ]

    @classmethod
    def same_brand(
        cls,
        product,
        limit=8,
    ):
        limit = cls._normalize_limit(
            limit,
            default=8,
        )

        if not product.brand_id:
            return []

        return list(
            cls._base_queryset()
            .filter(brand_id=product.brand_id)
            .exclude(pk=product.pk)
            .order_by(
                "-is_featured",
                "-sales_count",
                "-rating_avg",
                "-created_at",
            )[:limit]
        )

    @classmethod
    def same_category(
        cls,
        product,
        limit=8,
    ):
        limit = cls._normalize_limit(
            limit,
            default=8,
        )

        if not product.category_id:
            return []

        return list(
            cls._base_queryset()
            .filter(category_id=product.category_id)
            .exclude(pk=product.pk)
            .order_by(
                "-is_featured",
                "-sales_count",
                "-rating_avg",
                "-created_at",
            )[:limit]
        )

    @classmethod
    def trending(
        cls,
        limit=8,
    ):
        limit = cls._normalize_limit(
            limit,
            default=8,
        )

        return list(
            cls._base_queryset()
            .order_by(
                "-views_count",
                "-sales_count",
                "-rating_avg",
                "-created_at",
            )[:limit]
        )

    @classmethod
    def new_arrivals(
        cls,
        limit=8,
    ):
        limit = cls._normalize_limit(
            limit,
            default=8,
        )

        return list(
            cls._base_queryset()
            .order_by("-created_at")[:limit]
        )

    @classmethod
    def featured(
        cls,
        limit=8,
    ):
        limit = cls._normalize_limit(
            limit,
            default=8,
        )

        return list(
            cls._base_queryset()
            .filter(is_featured=True)
            .order_by(
                "-sales_count",
                "-rating_avg",
                "-created_at",
            )[:limit]
        )

    @classmethod
    def top_rated(
        cls,
        limit=8,
    ):
        limit = cls._normalize_limit(
            limit,
            default=8,
        )

        return list(
            cls._base_queryset()
            .order_by(
                "-rating_avg",
                "-rating_count",
                "-sales_count",
            )[:limit]
        )

    @classmethod
    def for_user(
        cls,
        request,
        limit=10,
        exclude_ids=None,
    ):
        limit = cls._normalize_limit(
            limit,
            default=10,
        )

        recent_products = cls.recent_products(
            request=request,
            limit=cls.MAX_RECENT_ITEMS,
        )

        excluded = set(exclude_ids or [])
        excluded.update(
            product.id
            for product in recent_products
        )

        if not recent_products:
            return list(
                cls._base_queryset()
                .exclude(id__in=excluded)
                .order_by(
                    "-is_featured",
                    "-sales_count",
                    "-rating_avg",
                    "-rating_count",
                    "-created_at",
                )[:limit]
            )

        candidates = list(
            cls._base_queryset()
            .exclude(id__in=excluded)
            .order_by(
                "-is_featured",
                "-sales_count",
                "-rating_avg",
                "-rating_count",
                "-created_at",
            )[:cls.MAX_CANDIDATES]
        )

        ranked = []

        for candidate in candidates:
            total_score = 0
            reasons = []

            for source_product in recent_products[:10]:
                scored = cls.score_product(
                    source_product,
                    candidate,
                )

                total_score += scored["score"]

                for reason in scored["reasons"]:
                    if reason not in reasons:
                        reasons.append(reason)

            ranked.append(
                {
                    "product": candidate,
                    "score": total_score,
                    "reasons": reasons,
                }
            )

        ranked.sort(
            key=lambda item: item["score"],
            reverse=True,
        )

        recommendations = [
            item["product"]
            for item in ranked[:limit]
        ]

        if len(recommendations) >= limit:
            return recommendations

        used_ids = excluded.union(
            product.id
            for product in recommendations
        )

        fallback = list(
            cls._base_queryset()
            .exclude(id__in=used_ids)
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

    @classmethod
    def for_cart(
        cls,
        cart,
        limit=10,
    ):
        limit = cls._normalize_limit(
            limit,
            default=10,
        )

        cart_products = []
        cart_product_ids = set()

        try:
            cart_items = cart.items.all()
        except Exception:
            return cls.trending(limit=limit)

        for item in cart_items:
            product = getattr(item, "product", None)

            if not product:
                continue

            if product.id in cart_product_ids:
                continue

            cart_product_ids.add(product.id)
            cart_products.append(product)

        if not cart_products:
            return cls.trending(limit=limit)

        candidates = list(
            cls._base_queryset()
            .exclude(id__in=cart_product_ids)
            .order_by(
                "-is_featured",
                "-sales_count",
                "-rating_avg",
                "-rating_count",
                "-created_at",
            )[:cls.MAX_CANDIDATES]
        )

        ranked = []

        for candidate in candidates:
            total_score = 0

            for cart_product in cart_products:
                result = cls.score_product(
                    cart_product,
                    candidate,
                )
                total_score += result["score"]

            ranked.append(
                {
                    "product": candidate,
                    "score": total_score,
                }
            )

        ranked.sort(
            key=lambda item: item["score"],
            reverse=True,
        )

        recommendations = [
            item["product"]
            for item in ranked[:limit]
        ]

        if len(recommendations) >= limit:
            return recommendations

        used_ids = cart_product_ids.union(
            product.id
            for product in recommendations
        )

        fallback = list(
            cls._base_queryset()
            .exclude(id__in=used_ids)
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