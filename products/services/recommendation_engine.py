from decimal import Decimal, InvalidOperation

from products.models import Product, RecentlyViewed
from products.services.behavior_profile import (
    BehaviorProfileBuilder,
)


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

    MAX_PER_BRAND = 4
    MAX_PER_CATEGORY = 6

    SEARCH_INTENT_RATIO = 0.20
    DISCOVERY_RATIO = 0.20

    REASON_LABELS = {
        "Same category": "Because you viewed similar products",
        "Same brand": "From a brand you browse",
        "Same vendor": "From a seller you've explored",
        "Similar price": "Matches your usual price range",
        "Featured": "Editor's choice",
        "In stock": "Available now",
    }

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
        exclude_purchased=False,
    ):
        """
        Return behavior-ranked product recommendations.

        The return value remains a list of Product objects so existing
        website templates and mobile API serializers remain compatible.
        """

        limit = cls._normalize_limit(
            limit,
            default=10,
        )

        profile = BehaviorProfileBuilder.build(
            request=request,
            exclude_purchased=exclude_purchased,
        )

        excluded = {
            int(product_id)
            for product_id in (
                exclude_ids or []
            )
            if product_id
        }

        excluded.update(
            profile.excluded_product_ids
        )

        # Do not recommend the exact products currently stored as
        # recently viewed. Their categories, brands and vendors still
        # influence the ranking of other products.
        excluded.update(
            profile.viewed_product_ids
        )

        candidates = list(
            cls._base_queryset()
            .exclude(
                id__in=excluded,
            )
            .order_by(
                "-is_featured",
                "-sales_count",
                "-rating_avg",
                "-rating_count",
                "-created_at",
            )[
                :cls.MAX_CANDIDATES
            ]
        )

        has_behavior = any(
            [
                profile.product_scores,
                profile.category_scores,
                profile.brand_scores,
                profile.vendor_scores,
                profile.search_terms,
                profile.wishlist_product_ids,
                profile.purchased_product_ids,
            ]
        )

        if not has_behavior:
            return candidates[:limit]

        ranked = []

        for candidate in candidates:
            scored = cls._behavior_profile_score(
                candidate=candidate,
                profile=profile,
            )

            ranked.append(
                {
                    "product": candidate,
                    "score": scored["score"],
                    "reasons": scored["reasons"],
                }
            )

        ranked.sort(
            key=lambda item: (
                item["score"],
                int(
                    getattr(
                        item["product"],
                        "sales_count",
                        0,
                    )
                    or 0
                ),
                float(
                    getattr(
                        item["product"],
                        "rating_avg",
                        0,
                    )
                    or 0
                ),
                int(
                    getattr(
                        item["product"],
                        "rating_count",
                        0,
                    )
                    or 0
                ),
            ),
            reverse=True,
        )

        search_slots = min(
            max(
                round(
                    limit
                    * cls.SEARCH_INTENT_RATIO
                ),
                1,
            ),
            limit,
        )

        discovery_slots = min(
            max(
                round(
                    limit
                    * cls.DISCOVERY_RATIO
                ),
                1,
            ),
            max(
                limit - search_slots,
                0,
            ),
        )

        personalized_slots = max(
            limit
            - search_slots
            - discovery_slots,
            0,
        )

        search_ranked = [
            {
                **item,
                "search_score": cls._candidate_search_score(
                    item["product"],
                    profile,
                ),
            }
            for item in ranked
        ]

        search_ranked.sort(
            key=lambda item: (
                item["search_score"],
                item["score"],
            ),
            reverse=True,
        )

        recommendations = []

        if profile.search_terms:
            recommendations.extend(
                cls._select_diverse_ranked(
                    search_ranked,
                    limit=search_slots,
                )
            )

        recommendations.extend(
            cls._select_diverse_ranked(
                ranked,
                limit=personalized_slots,
                used_ids={
                    product.id
                    for product in recommendations
                },
            )
        )

        discovery = cls._discovery_products(
            limit=discovery_slots,
            exclude_ids=excluded.union(
                product.id
                for product in recommendations
            ),
        )

        existing_keys = {
            cls._normalized_product_key(product)
            for product in recommendations
        }

        for product in discovery:
            product_key = cls._normalized_product_key(
                product
            )

            if (
                product_key
                and product_key in existing_keys
            ):
                continue

            recommendations.append(product)

            if product_key:
                existing_keys.add(product_key)

            if len(recommendations) >= limit:
                break

        used_ids = excluded.union(
            product.id
            for product in recommendations
        )

        fallback = list(
            cls._base_queryset()
            .exclude(
                id__in=used_ids,
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

        recommendations.extend(
            fallback
        )

        if len(recommendations) >= limit:
            return recommendations[:limit]

    @classmethod
    def for_user_with_reasons(
        cls,
        request,
        limit=10,
        exclude_ids=None,
        exclude_purchased=False,
    ):
        """
        Same recommendation engine but returns metadata
        instead of Product objects.
        """

        recommendations = cls.for_user(
            request=request,
            limit=limit,
            exclude_ids=exclude_ids,
            exclude_purchased=exclude_purchased,
        )

        profile = BehaviorProfileBuilder.build(
            request=request,
            exclude_purchased=exclude_purchased,
        )

        results = []

        for product in recommendations:
            scored = cls._behavior_profile_score(
                candidate=product,
                profile=profile,
            )

            results.append(
                {
                    "product": product,
                    "score": scored["score"],
                    "reasons": scored["reasons"],
                }
            )

        return results

    @classmethod
    def human_reasons(cls, reasons):
        return [
            cls.REASON_LABELS.get(reason, reason)
            for reason in reasons[:3]
        ]

    @classmethod
    def _candidate_search_score(
        cls,
        candidate,
        profile,
    ):
        searchable_text = " ".join(
            [
                str(getattr(candidate, "name", "") or ""),
                str(
                    getattr(
                        candidate,
                        "short_description",
                        "",
                    )
                    or ""
                ),
                str(
                    getattr(
                        candidate,
                        "description",
                        "",
                    )
                    or ""
                ),
                str(
                    getattr(
                        getattr(candidate, "category", None),
                        "name",
                        "",
                    )
                    or ""
                ),
                str(
                    getattr(
                        getattr(candidate, "brand", None),
                        "name",
                        "",
                    )
                    or ""
                ),
            ]
        ).lower()

        score = 0.0

        for term, weight in profile.search_terms.items():
            normalized_term = str(term or "").strip().lower()

            if not normalized_term:
                continue

            if normalized_term in searchable_text:
                score += float(weight) * 8.0
                continue

            words = [
                word
                for word in normalized_term.split()
                if len(word) >= 3
            ]

            if not words:
                continue

            matched_words = sum(
                1
                for word in words
                if word in searchable_text
            )

            score += (
                float(weight)
                * 4.0
                * (
                    matched_words
                    / len(words)
                )
            )

        return score

    @staticmethod
    def _normalized_product_key(product):
        import re

        name = str(
            getattr(product, "name", "")
            or ""
        ).strip().lower()

        # Ignore specification text appended after a comma.
        name = name.split(",", 1)[0]

        # Normalize punctuation and spacing.
        name = name.replace("–", "-")
        name = name.replace("—", "-")
        name = re.sub(
            r"[^a-z0-9]+",
            " ",
            name,
        )

        return " ".join(
            name.split()
        )

    @classmethod
    def _select_diverse_ranked(
        cls,
        ranked,
        *,
        limit,
        max_per_brand=None,
        max_per_category=None,
        used_ids=None,
    ):
        max_per_brand = (
            max_per_brand
            or cls.MAX_PER_BRAND
        )

        max_per_category = (
            max_per_category
            or cls.MAX_PER_CATEGORY
        )

        selected = []
        selected_ids = set(used_ids or [])
        selected_product_keys = set()
        brand_counts = {}
        category_counts = {}

        for item in ranked:
            product = item["product"]

            product_key = cls._normalized_product_key(
                product
            )

            if (
                product_key
                and product_key in selected_product_keys
            ):
                continue

            if product.id in selected_ids:
                continue

            brand_id = product.brand_id
            category_id = product.category_id

            if (
                brand_id
                and brand_counts.get(brand_id, 0)
                >= max_per_brand
            ):
                continue

            if (
                category_id
                and category_counts.get(category_id, 0)
                >= max_per_category
            ):
                continue

            selected.append(product)
            selected_ids.add(product.id)

            if product_key:
                selected_product_keys.add(
                    product_key
                )

            if brand_id:
                brand_counts[brand_id] = (
                    brand_counts.get(brand_id, 0)
                    + 1
                )

            if category_id:
                category_counts[category_id] = (
                    category_counts.get(category_id, 0)
                    + 1
                )

            if len(selected) >= limit:
                break

        return selected

    @classmethod
    def _discovery_products(
        cls,
        *,
        limit,
        exclude_ids=None,
    ):
        if limit <= 0:
            return []

        return list(
            cls._base_queryset()
            .exclude(
                id__in=set(exclude_ids or []),
            )
            .order_by(
                "-is_featured",
                "-sales_count",
                "-rating_avg",
                "-rating_count",
                "-created_at",
            )[:limit]
        )

    @classmethod
    def _behavior_profile_score(
        cls,
        candidate,
        profile,
    ):
        """
        Score one candidate against a customer's behavior profile.

        Returns both the numerical score and human-readable reasons.
        """

        score = 0.0
        reasons = []

        direct_product_score = float(
            profile.product_scores.get(
                candidate.id,
                0,
            )
        )

        if direct_product_score:
            score += direct_product_score * 0.35
            reasons.append(
                "Based on products you interacted with"
            )

        if candidate.category_id:
            category_score = float(
                profile.category_scores.get(
                    candidate.category_id,
                    0,
                )
            )

            if category_score:
                score += category_score * 1.50
                reasons.append(
                    "Popular in categories you browse"
                )

        if candidate.brand_id:
            brand_score = float(
                profile.brand_scores.get(
                    candidate.brand_id,
                    0,
                )
            )

            if brand_score:
                score += brand_score * 1.20
                reasons.append(
                    "From brands you are interested in"
                )

        if candidate.vendor_id:
            vendor_score = float(
                profile.vendor_scores.get(
                    candidate.vendor_id,
                    0,
                )
            )

            if vendor_score:
                score += vendor_score * 0.75
                reasons.append(
                    "From sellers you have explored"
                )

        searchable_text = " ".join(
            [
                str(
                    getattr(
                        candidate,
                        "name",
                        "",
                    )
                    or ""
                ),
                str(
                    getattr(
                        candidate,
                        "short_description",
                        "",
                    )
                    or ""
                ),
                str(
                    getattr(
                        candidate,
                        "description",
                        "",
                    )
                    or ""
                ),
                str(
                    getattr(
                        getattr(
                            candidate,
                            "category",
                            None,
                        ),
                        "name",
                        "",
                    )
                    or ""
                ),
                str(
                    getattr(
                        getattr(
                            candidate,
                            "brand",
                            None,
                        ),
                        "name",
                        "",
                    )
                    or ""
                ),
            ]
        ).lower()

        matched_search_terms = []

        for term, term_weight in profile.search_terms.items():
            normalized_term = str(
                term or ""
            ).strip().lower()

            if not normalized_term:
                continue

            if normalized_term in searchable_text:
                score += float(term_weight) * 4.0
                matched_search_terms.append(
                    normalized_term
                )

                continue

            term_words = [
                word
                for word in normalized_term.split()
                if len(word) >= 3
            ]

            matched_words = sum(
                1
                for word in term_words
                if word in searchable_text
            )

            if term_words and matched_words:
                match_ratio = (
                    matched_words
                    / len(term_words)
                )

                score += (
                    float(term_weight)
                    * 2.0
                    * match_ratio
                )

                matched_search_terms.append(
                    normalized_term
                )

        if matched_search_terms:
            reasons.append(
                "Based on your recent searches"
            )

        if candidate.id in profile.wishlist_product_ids:
            score += 8.0
            reasons.append(
                "Similar to items in your wishlist"
            )

        if candidate.is_featured:
            score += cls.FEATURED_WEIGHT

        stock_quantity = int(
            getattr(
                candidate,
                "stock_quantity",
                0,
            )
            or 0
        )

        if stock_quantity > 0:
            score += cls.IN_STOCK_WEIGHT
        else:
            score -= 40

        sales_count = int(
            getattr(
                candidate,
                "sales_count",
                0,
            )
            or 0
        )

        score += min(
            sales_count,
            100,
        ) * 0.35

        rating_avg = float(
            getattr(
                candidate,
                "rating_avg",
                0,
            )
            or 0
        )

        rating_count = int(
            getattr(
                candidate,
                "rating_count",
                0,
            )
            or 0
        )

        score += rating_avg * 5.0
        score += min(
            rating_count,
            50,
        ) * 0.20

        if getattr(
            candidate,
            "is_new",
            False,
        ):
            score += cls.NEW_PRODUCT_WEIGHT

        unique_reasons = []

        for reason in reasons:
            if reason not in unique_reasons:
                unique_reasons.append(reason)

        return {
            "score": score,
            "reasons": unique_reasons,
        }


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