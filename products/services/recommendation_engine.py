from decimal import Decimal, InvalidOperation
from django.db.models import Count
from collections import Counter
from django.core.cache import cache
from django.utils import timezone
from orders.models import OrderItem
from visitor_analytics.models import ClickEvent
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

    RECOMMENDATION_CACHE_VERSION = "v1"

    SIMILAR_CACHE_TTL = 600
    CO_PURCHASE_CACHE_TTL = 300
    FREQUENTLY_BOUGHT_CACHE_TTL = 300
    ALSO_VIEWED_CACHE_TTL = 300

    REASON_LABELS = {
        "Same category": "Similar products",
        "Same brand": "From a brand you browse",
        "Same vendor": "From a seller you explored",
        "Similar price": "Matches your price range",
        "Featured": "Featured pick",
        "In stock": "Available now",
        "Based on your recent searches": "Based on your searches",
        "Popular in categories you browse": "Based on your browsing",
        "From brands you are interested in": "From brands you browse",
        "From sellers you have explored": "From sellers you explored",
        "Purchased after similar recommendations": "Customers bought this recommendation",
    }


    PURCHASE_PAYMENT_STATUSES = {
        "paid",
    }

    INVALID_PURCHASE_ORDER_STATUSES = {
        "cancelled",
        "refunded",
    }

    MIN_COPURCHASE_ORDERS = 1

    # Recommendation → paid purchase learning.
    #
    # These signals are deliberately capped so recommendation conversions
    # improve ranking without overpowering category, brand, price, stock,
    # co-purchase, and customer-intent signals.
    RECOMMENDATION_CONVERSION_WEIGHT = 12.0
    RECOMMENDATION_CONVERSION_MAX_BONUS = 36.0
    RECOMMENDATION_CONVERSION_CACHE_TTL = 300
    RECOMMENDATION_CONVERSION_PRIOR_RATE = 0.02
    RECOMMENDATION_CONVERSION_PRIOR_IMPRESSIONS = 25.0
    RECOMMENDATION_CONVERSION_RATE_WEIGHT = 120.0

    # Recommendation section + algorithm performance learning.
    #
    # Channel learning is intentionally weaker than product-specific
    # recommendation conversions so broad placement performance cannot
    # overpower stronger product, inventory, and personalization signals.
    RECOMMENDATION_CHANNEL_UNKNOWN_ALGORITHM = "unknown"
    RECOMMENDATION_CHANNEL_CTR_PRIOR_RATE = 0.03
    RECOMMENDATION_CHANNEL_CTR_PRIOR_IMPRESSIONS = 100.0
    RECOMMENDATION_CHANNEL_CVR_PRIOR_RATE = 0.005
    RECOMMENDATION_CHANNEL_CVR_PRIOR_IMPRESSIONS = 150.0
    RECOMMENDATION_CHANNEL_REFERENCE_CTR = 0.08
    RECOMMENDATION_CHANNEL_REFERENCE_CVR = 0.02
    RECOMMENDATION_CHANNEL_CONFIDENCE_IMPRESSIONS = 500.0
    RECOMMENDATION_CHANNEL_MAX_SCORE = 1.0
    RECOMMENDATION_CHANNEL_BASELINE_SCORE = 0.30
    RECOMMENDATION_CHANNEL_MAX_BONUS = 12.0
    RECOMMENDATION_CHANNEL_CACHE_TTL = 300
    RECOMMENDATION_CHANNEL_EXPLORATION_RATIO = 0.20
    RECOMMENDATION_CHANNEL_MIN_ALLOCATION = 0.10
    RECOMMENDATION_CHANNEL_MAX_ALLOCATION = 0.40
    RECOMMENDATION_CHANNEL_ALLOCATION_CACHE_TTL = 300
    RECOMMENDATION_CHANNELS = {
        "customers_also_viewed": {
            "algorithm": "behavioral",
            "default_limit": 12,
        },
        "customers_who_bought": {
            "algorithm": "co_purchase",
            "default_limit": 12,
        },
        "related_products": {
            "algorithm": "product_similarity",
            "default_limit": 8,
        },
        "ai_recommendations": {
            "algorithm": "product_similarity",
            "default_limit": 8,
        },
        "top_rated_similar": {
            "algorithm": "product_similarity",
            "default_limit": 8,
        },
    }


    @classmethod
    def customers_who_bought_this_also_bought(
        cls,
        *,
        product,
        limit=12,
    ):
        """
        Return products genuinely purchased alongside the current product.

        Only paid, non-cancelled/non-refunded orders are considered.

        One order contributes at most one co-purchase vote per product,
        so buying multiple units in the same order does not artificially
        increase recommendation strength.

        This method never manufactures fallback results.
        If genuine co-purchase evidence does not exist, it returns [].
        """

        if not product or not getattr(product, "pk", None):
            return []

        limit = cls._normalize_limit(
            limit,
            default=12,
        )

        cache_key = cls._recommendation_cache_key(
            kind="co-purchase",
            product_id=product.pk,
            limit=limit,
        )

        cached = cache.get(cache_key)

        if cached is not None:
            cached_ids = [
                item["product_id"]
                for item in cached
            ]

            products_by_id = (
                cls._base_queryset()
                .filter(id__in=cached_ids)
                .in_bulk()
            )

            restored = []

            for item in cached:
                candidate = products_by_id.get(
                    item["product_id"]
                )

                if not candidate:
                    continue

                restored.append({
                    "product": candidate,
                    "co_purchase_orders": item.get(
                        "co_purchase_orders",
                        0,
                    ),

                    "unique_buyers": item.get(
                        "unique_buyers",
                        0,
                    ),
                    "score": item.get("score", 0),
                    "reasons": item.get("reasons", []),
                })

            return restored

        # ============================================================
        # 1. Find genuine paid orders containing the source product
        # ============================================================

        source_order_ids = list(
            OrderItem.objects
            .filter(
                product_id=product.pk,
                order__payment_status__in=(
                    cls.PURCHASE_PAYMENT_STATUSES
                ),
            )
            .exclude(
                order__status__in=(
                    cls.INVALID_PURCHASE_ORDER_STATUSES
                )
            )
            .values_list(
                "order_id",
                flat=True,
            )
            .distinct()
        )

        if not source_order_ids:
            return []

        # ============================================================
        # 2. Count other products appearing in the same paid orders
        #
        # Count distinct orders, not quantities.
        # ============================================================

        co_purchase_rows = list(
            OrderItem.objects
            .filter(
                order_id__in=source_order_ids,
                product__isnull=False,
                order__payment_status__in=(
                    cls.PURCHASE_PAYMENT_STATUSES
                ),
            )
            .exclude(
                order__status__in=(
                    cls.INVALID_PURCHASE_ORDER_STATUSES
                )
            )
            .exclude(
                product_id=product.pk,
            )
            .filter(
                product__is_active=True,
                product__approval_status="approved",
            )
            .values(
                "product_id",
            )
            .annotate(
                co_purchase_orders=Count(
                    "order_id",
                    distinct=True,
                ),
                unique_buyers=Count(
                    "order__user_id",
                    distinct=True,
                ),
            )
            .filter(
                co_purchase_orders__gte=(
                    cls.MIN_COPURCHASE_ORDERS
                )
            )
            .order_by(
                "-co_purchase_orders",
                "-unique_buyers",
            )
        )

        if not co_purchase_rows:
            return []

        # ============================================================
        # 3. Create a lookup for the behavioral purchase statistics
        # ============================================================

        stats_by_product_id = {
            row["product_id"]: row
            for row in co_purchase_rows
        }

        candidate_ids = list(
            stats_by_product_id.keys()
        )

        # ============================================================
        # 4. Load only valid storefront products
        # ============================================================

        candidates = list(
            cls._base_queryset()
            .filter(
                id__in=candidate_ids,
            )
        )

        source_category_id = getattr(
            product,
            "category_id",
            None,
        )

        source_brand_id = getattr(
            product,
            "brand_id",
            None,
        )

        source_vendor_id = getattr(
            product,
            "vendor_id",
            None,
        )

        ranked = []

        # ============================================================
        # 5. Rank using real purchase behaviour first
        # ============================================================

        for candidate in candidates:
            stats = stats_by_product_id.get(
                candidate.id,
                {},
            )

            co_purchase_orders = int(
                stats.get(
                    "co_purchase_orders",
                    0,
                )
                or 0
            )

            unique_buyers = int(
                stats.get(
                    "unique_buyers",
                    0,
                )
                or 0
            )

            # Purchase evidence must remain the dominant signal.
            score = float(
                (co_purchase_orders * 100)
                + (unique_buyers * 20)
            )

            reasons = []

            if co_purchase_orders == 1:
                reasons.append(
                    "Bought together by a customer"
                )
            else:
                reasons.append(
                    (
                        "Bought together in "
                        f"{co_purchase_orders} orders"
                    )
                )

            # --------------------------------------------------------
            # Relevance bonuses
            # --------------------------------------------------------

            if (
                source_category_id
                and candidate.category_id
                == source_category_id
            ):
                score += 30
                reasons.append(
                    "Same product category"
                )

            if (
                source_brand_id
                and candidate.brand_id
                == source_brand_id
            ):
                score += 8
                reasons.append(
                    "Same brand"
                )

            if (
                source_vendor_id
                and candidate.vendor_id
                == source_vendor_id
            ):
                score += 4
                reasons.append(
                    "Same seller"
                )

            # --------------------------------------------------------
            # Price relevance
            # --------------------------------------------------------

            price_score = cls._price_similarity_score(
                product,
                candidate,
            )

            if price_score:
                score += min(
                    float(price_score),
                    12.0,
                )

            # --------------------------------------------------------
            # Listing/storefront quality
            # --------------------------------------------------------

            if getattr(
                candidate,
                "is_featured",
                False,
            ):
                score += 4

            stock_quantity = int(
                getattr(
                    candidate,
                    "stock_quantity",
                    0,
                )
                or 0
            )

            if stock_quantity > 0:
                score += 6
            else:
                score -= 30

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
                20,
            ) * 0.5

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

            score += rating_avg * 2.0
            score += min(
                rating_count,
                20,
            ) * 0.25

            ranked.append(
                {
                    "product": candidate,
                    "score": round(
                        score,
                        2,
                    ),
                    "co_purchase_orders": (
                        co_purchase_orders
                    ),
                    "unique_buyers": (
                        unique_buyers
                    ),
                    "reasons": reasons[:3],
                }
            )

        # ============================================================
        # 6. Final deterministic ordering
        # ============================================================

        ranked.sort(
            key=lambda item: (
                -item["score"],
                -item["co_purchase_orders"],
                -item["unique_buyers"],
                -int(
                    getattr(
                        item["product"],
                        "sales_count",
                        0,
                    )
                    or 0
                ),
                item["product"].id,
            )
        )

        ranked = ranked[:limit]

        cache.set(
            cache_key,
            [
                {
                    "product_id": item["product"].id,
                    "co_purchase_orders": item.get(
                        "co_purchase_orders",
                        0,
                    ),
                    "unique_buyers": item.get(
                        "unique_buyers",
                        0,
                    ),
                    "score": item.get("score", 0),
                    "reasons": item.get("reasons", []),
                }
                for item in ranked
            ],
            cls.CO_PURCHASE_CACHE_TTL,
        )

        return ranked

    @classmethod
    def recommendation_conversion_stats(
        cls,
        *,
        source_product,
    ):
        """
        Return paid recommendation conversions originating from source_product.

        A conversion counts only when:
        - the recommended product was permanently attributed to source_product;
        - the resulting order is paid;
        - the order is not cancelled or refunded;
        - the purchased product still exists.

        Results are keyed by the purchased recommended product id.

        Example:
            Samsung Galaxy S24
                -> recommendation
            OnePlus Open
                -> add to cart
                -> paid order

            {
                23: {
                    "paid_orders": 3,
                    "unique_buyers": 2,
                    "bonus": 36.0,
                }
            }
        """
        if not source_product or not getattr(
            source_product,
            "pk",
            None,
        ):
            return {}

        cache_key = (
            f"arolana:recommendations:"
            f"{cls.RECOMMENDATION_CACHE_VERSION}:"
            f"conversion:"
            f"{source_product.pk}"
        )

        cached = cache.get(cache_key)

        if cached is not None:
            return cached

        rows = list(
            OrderItem.objects
            .filter(
                recommendation_source_product_id=(
                    source_product.pk
                ),
                product__isnull=False,
                order__payment_status__in=(
                    cls.PURCHASE_PAYMENT_STATUSES
                ),
                product__is_active=True,
                product__approval_status="approved",
            )
            .exclude(
                order__status__in=(
                    cls.INVALID_PURCHASE_ORDER_STATUSES
                )
            )
            .values(
                "product_id",
            )
            .annotate(
                paid_orders=Count(
                    "order_id",
                    distinct=True,
                ),
                unique_buyers=Count(
                    "order__user_id",
                    distinct=True,
                ),
            )
        )

        stats = {}

        impression_rows = list(
            ClickEvent.objects
            .filter(
                event_type=(
                    ClickEvent.EVENT_RECOMMENDATION_IMPRESSION
                ),
                source_product_id=str(source_product.pk),
            )
            .exclude(product_id="")
            .values(
                "product_id",
            )
            .annotate(
                impressions=Count("id"),
            )
        )

        impressions_by_product_id = {}

        for row in impression_rows:
            try:
                product_id = int(row["product_id"])
            except (TypeError, ValueError):
                continue

            impressions_by_product_id[product_id] = int(
                row.get("impressions") or 0
            )

        for row in rows:
            product_id = row.get("product_id")

            if not product_id:
                continue

            paid_orders = int(
                row.get("paid_orders") or 0
            )

            unique_buyers = int(
                row.get("unique_buyers") or 0
            )

            impressions = int(
                impressions_by_product_id.get(
                    product_id,
                    0,
                )
                or 0
            )

            raw_conversion_rate = (
                paid_orders / impressions
                if impressions > 0
                else 0.0
            )

            prior_rate = (
                cls.RECOMMENDATION_CONVERSION_PRIOR_RATE
            )

            prior_impressions = (
                cls.RECOMMENDATION_CONVERSION_PRIOR_IMPRESSIONS
            )

            smoothed_conversion_rate = (
                (
                    paid_orders
                    + (
                        prior_rate
                        * prior_impressions
                    )
                )
                / (
                    impressions
                    + prior_impressions
                )
            )

            # Base reward for genuine paid recommendation conversions.
            raw_bonus = (
                paid_orders
                * cls.RECOMMENDATION_CONVERSION_WEIGHT
            )

            # Reward conversion efficiency, but use the smoothed CVR
            # so tiny samples do not dominate ranking.
            raw_bonus += (
                smoothed_conversion_rate
                * cls.RECOMMENDATION_CONVERSION_RATE_WEIGHT
            )

            # Additional confidence when multiple distinct customers convert.
            if unique_buyers > 1:
                raw_bonus += min(
                    unique_buyers - 1,
                    4,
                ) * 2.0

            bonus = min(
                raw_bonus,
                cls.RECOMMENDATION_CONVERSION_MAX_BONUS,
            )

            stats[product_id] = {
                "paid_orders": paid_orders,
                "unique_buyers": unique_buyers,
                "impressions": impressions,
                "raw_conversion_rate": round(
                    raw_conversion_rate,
                    4,
                ),
                "smoothed_conversion_rate": round(
                    smoothed_conversion_rate,
                    4,
                ),
                "bonus": round(
                    float(bonus),
                    2,
                ),
            }

        cache.set(
            cache_key,
            stats,
            cls.RECOMMENDATION_CONVERSION_CACHE_TTL,
        )

        return stats

    @classmethod
    def recommendation_channel_performance(cls):
        """
        Return recommendation performance by section + algorithm channel.

        Results are keyed as "section::algorithm" and use permanent
        OrderItem attribution as the purchase source of truth.
        """
        cache_key = (
            f"arolana:recommendations:"
            f"{cls.RECOMMENDATION_CACHE_VERSION}:"
            f"channel-performance"
        )

        cached = cache.get(cache_key)

        if cached is not None:
            return cached

        stats = {}

        impression_rows = list(
            ClickEvent.objects
            .filter(
                event_type=(
                    ClickEvent.EVENT_RECOMMENDATION_IMPRESSION
                ),
                is_bot=False,
            )
            .exclude(
                recommendation_section="",
            )
            .values(
                "recommendation_section",
                "recommendation_algorithm",
            )
            .annotate(
                impressions=Count("id"),
            )
        )

        click_rows = list(
            ClickEvent.objects
            .filter(
                event_type=(
                    ClickEvent.EVENT_RECOMMENDATION_CLICK
                ),
                is_bot=False,
            )
            .exclude(
                recommendation_section="",
            )
            .values(
                "recommendation_section",
                "recommendation_algorithm",
            )
            .annotate(
                clicks=Count("id"),
            )
        )

        purchase_rows = list(
            OrderItem.objects
            .filter(
                product__isnull=False,
                order__payment_status__in=(
                    cls.PURCHASE_PAYMENT_STATUSES
                ),
            )
            .exclude(
                recommendation_section="",
            )
            .exclude(
                order__status__in=(
                    cls.INVALID_PURCHASE_ORDER_STATUSES
                )
            )
            .values(
                "recommendation_section",
                "recommendation_algorithm",
                "order_id",
                "order__user_id",
            )
            .distinct()
        )

        purchase_order_ids_by_key = {}
        buyer_ids_by_key = {}

        for row in impression_rows:
            key, section, algorithm = (
                cls._recommendation_channel_key_from_row(row)
            )

            if not key:
                continue

            stats.setdefault(
                key,
                cls._empty_recommendation_channel_stats(
                    section=section,
                    algorithm=algorithm,
                ),
            )

            stats[key]["impressions"] += int(
                row.get("impressions") or 0
            )

        for row in click_rows:
            key, section, algorithm = (
                cls._recommendation_channel_key_from_row(row)
            )

            if not key:
                continue

            stats.setdefault(
                key,
                cls._empty_recommendation_channel_stats(
                    section=section,
                    algorithm=algorithm,
                ),
            )

            stats[key]["clicks"] += int(
                row.get("clicks") or 0
            )

        for row in purchase_rows:
            key, section, algorithm = (
                cls._recommendation_channel_key_from_row(row)
            )

            if not key:
                continue

            stats.setdefault(
                key,
                cls._empty_recommendation_channel_stats(
                    section=section,
                    algorithm=algorithm,
                ),
            )

            purchase_order_ids_by_key.setdefault(
                key,
                set(),
            ).add(row.get("order_id"))

            buyer_id = row.get("order__user_id")

            if buyer_id:
                buyer_ids_by_key.setdefault(
                    key,
                    set(),
                ).add(buyer_id)

        for key, channel_stats in stats.items():
            channel_stats["paid_orders"] = len(
                purchase_order_ids_by_key.get(key, set())
            )
            channel_stats["unique_buyers"] = len(
                buyer_ids_by_key.get(key, set())
            )

            impressions = channel_stats["impressions"]
            clicks = channel_stats["clicks"]
            paid_orders = channel_stats["paid_orders"]

            raw_ctr = (
                clicks / impressions
                if impressions > 0
                else 0.0
            )

            raw_purchase_cvr = (
                paid_orders / impressions
                if impressions > 0
                else 0.0
            )

            smoothed_ctr = cls._smoothed_rate(
                successes=clicks,
                trials=impressions,
                prior_rate=(
                    cls.RECOMMENDATION_CHANNEL_CTR_PRIOR_RATE
                ),
                prior_trials=(
                    cls.RECOMMENDATION_CHANNEL_CTR_PRIOR_IMPRESSIONS
                ),
            )

            smoothed_purchase_cvr = cls._smoothed_rate(
                successes=paid_orders,
                trials=impressions,
                prior_rate=(
                    cls.RECOMMENDATION_CHANNEL_CVR_PRIOR_RATE
                ),
                prior_trials=(
                    cls.RECOMMENDATION_CHANNEL_CVR_PRIOR_IMPRESSIONS
                ),
            )

            ctr_score = min(
                smoothed_ctr
                / cls.RECOMMENDATION_CHANNEL_REFERENCE_CTR,
                1.0,
            )

            purchase_score = min(
                smoothed_purchase_cvr
                / cls.RECOMMENDATION_CHANNEL_REFERENCE_CVR,
                1.0,
            )

            performance_score = min(
                (
                    (ctr_score * 0.30)
                    + (purchase_score * 0.70)
                ),
                cls.RECOMMENDATION_CHANNEL_MAX_SCORE,
            )

            confidence = min(
                impressions
                / cls.RECOMMENDATION_CHANNEL_CONFIDENCE_IMPRESSIONS,
                1.0,
            )

            excess_performance = max(
                performance_score
                - cls.RECOMMENDATION_CHANNEL_BASELINE_SCORE,
                0.0,
            )

            # Rescale the above-baseline portion so a perfect-performing
            # channel can still reach RECOMMENDATION_CHANNEL_MAX_BONUS.
            available_performance_range = max(
                cls.RECOMMENDATION_CHANNEL_MAX_SCORE
                - cls.RECOMMENDATION_CHANNEL_BASELINE_SCORE,
                0.0001,
            )

            normalized_excess_performance = min(
                excess_performance / available_performance_range,
                1.0,
            )

            bonus = (
                normalized_excess_performance
                * confidence
                * cls.RECOMMENDATION_CHANNEL_MAX_BONUS
            )

            channel_stats.update({
                "raw_ctr": round(raw_ctr, 4),
                "smoothed_ctr": round(smoothed_ctr, 4),
                "raw_purchase_cvr": round(raw_purchase_cvr, 4),
                "smoothed_purchase_cvr": round(
                    smoothed_purchase_cvr,
                    4,
                ),
                "performance_score": round(
                    performance_score,
                    4,
                ),
                "bonus": round(float(bonus), 2),
                "confidence": round(confidence, 4),
                "excess_performance": round(
                    excess_performance,
                    4,
                ),
                "normalized_excess_performance": round(
                    normalized_excess_performance,
                    4,
                ),
            })

        cache.set(
            cache_key,
            stats,
            cls.RECOMMENDATION_CHANNEL_CACHE_TTL,
        )

        return stats

    @classmethod
    def recommendation_channel_bonus(
        cls,
        *,
        section,
        algorithm="",
    ):
        """Return the learned bonus for a recommendation channel."""
        key = cls._recommendation_channel_key(
            section=section,
            algorithm=algorithm,
        )

        if not key:
            return 0.0

        stats = cls.recommendation_channel_performance()
        channel_stats = stats.get(key)

        if not channel_stats:
            return 0.0

        return float(channel_stats.get("bonus") or 0.0)

    @classmethod
    def recommendation_channel_allocation(cls):
        """
        Return normalized recommendation-channel traffic allocation.

        The policy combines:

        - exploitation:
        channels with stronger learned performance receive more exposure;

        - exploration:
        every valid channel retains enough traffic to continue learning;

        - safety bounds:
        no channel can receive too little or dominate the entire surface.

        Returned values sum to approximately 1.0.

        Example:

            {
                "customers_also_viewed::behavioral": 0.27,
                "ai_recommendations::product_similarity": 0.19,
                ...
            }
        """
        cache_key = (
            f"arolana:recommendations:"
            f"{cls.RECOMMENDATION_CACHE_VERSION}:"
            f"channel-allocation"
        )

        cached = cache.get(cache_key)

        if cached is not None:
            return cached

        performance = (
            cls.recommendation_channel_performance()
        )

        if not performance:
            return {}

        channel_keys = sorted(performance.keys())

        channel_count = len(channel_keys)

        if channel_count == 0:
            return {}

        # ------------------------------------------------------------
        # Base exploration allocation
        # ------------------------------------------------------------

        equal_share = 1.0 / channel_count

        exploration_ratio = min(
            max(
                float(
                    cls.RECOMMENDATION_CHANNEL_EXPLORATION_RATIO
                ),
                0.0,
            ),
            1.0,
        )

        exploitation_ratio = 1.0 - exploration_ratio

        # ------------------------------------------------------------
        # Build exploitation weights
        #
        # Start every channel with weight 1.0 so channels with no
        # historical bonus are not completely starved.
        # ------------------------------------------------------------

        exploitation_weights = {}

        for key in channel_keys:
            data = performance.get(key, {})

            bonus = max(
                float(
                    data.get("bonus", 0.0)
                    or 0.0
                ),
                0.0,
            )

            performance_score = max(
                float(
                    data.get(
                        "performance_score",
                        0.0,
                    )
                    or 0.0
                ),
                0.0,
            )

            confidence = min(
                max(
                    float(
                        data.get(
                            "confidence",
                            0.0,
                        )
                        or 0.0
                    ),
                    0.0,
                ),
                1.0,
            )

            # Bonus remains the strongest learned channel signal.
            #
            # Performance contributes only in proportion to confidence,
            # so tiny samples cannot dominate.
            learned_weight = (
                1.0
                + bonus
                + (
                    performance_score
                    * confidence
                )
            )

            exploitation_weights[key] = max(
                learned_weight,
                0.0001,
            )

        total_exploitation_weight = sum(
            exploitation_weights.values()
        )

        # ------------------------------------------------------------
        # Combine exploration + exploitation
        # ------------------------------------------------------------

        allocations = {}

        for key in channel_keys:
            if total_exploitation_weight > 0:
                exploitation_share = (
                    exploitation_weights[key]
                    / total_exploitation_weight
                )
            else:
                exploitation_share = equal_share

            allocation = (
                exploration_ratio
                * equal_share
            ) + (
                exploitation_ratio
                * exploitation_share
            )

            allocations[key] = allocation

        # ------------------------------------------------------------
        # Apply safety floor / ceiling.
        # ------------------------------------------------------------

        min_allocation = max(
            float(
                cls.RECOMMENDATION_CHANNEL_MIN_ALLOCATION
            ),
            0.0,
        )

        max_allocation = min(
            max(
                float(
                    cls.RECOMMENDATION_CHANNEL_MAX_ALLOCATION
                ),
                min_allocation,
            ),
            1.0,
        )

        allocations = {
            key: min(
                max(
                    value,
                    min_allocation,
                ),
                max_allocation,
            )
            for key, value in allocations.items()
        }

        # ------------------------------------------------------------
        # Renormalize after safety bounds.
        # ------------------------------------------------------------

        total = sum(allocations.values())

        if total <= 0:
            allocations = {
                key: equal_share
                for key in channel_keys
            }
        else:
            allocations = {
                key: value / total
                for key, value in allocations.items()
            }

        # Round for stable API/debug output, then repair any tiny
        # floating-point remainder on the strongest allocation.
        allocations = {
            key: round(value, 4)
            for key, value in allocations.items()
        }

        rounded_total = sum(allocations.values())

        if allocations and rounded_total != 1.0:
            strongest_key = max(
                allocations,
                key=allocations.get,
            )

            allocations[strongest_key] = round(
                allocations[strongest_key]
                + (1.0 - rounded_total),
                4,
            )

        cache.set(
            cache_key,
            allocations,
            cls.RECOMMENDATION_CHANNEL_ALLOCATION_CACHE_TTL,
        )

        return allocations

    @classmethod
    def recommendation_channel_allocation_for(
        cls,
        *,
        section,
        algorithm="",
    ):
        """
        Return the normalized traffic share for one channel.
        """
        key = cls._recommendation_channel_key(
            section=section,
            algorithm=algorithm,
        )

        if not key:
            return 0.0

        allocations = (
            cls.recommendation_channel_allocation()
        )

        return float(
            allocations.get(
                key,
                0.0,
            )
            or 0.0
        )

    @classmethod
    def recommendation_exposure_plan(cls):
        """
        Return a conservative presentation plan for known channels.
        """
        cache_key = (
            f"arolana:recommendations:"
            f"{cls.RECOMMENDATION_CACHE_VERSION}:"
            f"exposure-plan"
        )

        cached = cache.get(cache_key)

        if cached is not None:
            return cached

        allocations = cls.recommendation_channel_allocation()
        channel_count = len(cls.RECOMMENDATION_CHANNELS)
        equal_share = (
            1.0 / channel_count
            if channel_count > 0
            else 0.0
        )

        plan_items = []

        for section, config in cls.RECOMMENDATION_CHANNELS.items():
            algorithm = config.get("algorithm", "")
            default_limit = int(
                config.get("default_limit", cls.MAX_RESULTS)
                or cls.MAX_RESULTS
            )
            channel_key = cls._recommendation_channel_key(
                section=section,
                algorithm=algorithm,
            )
            allocation = float(
                allocations.get(channel_key, equal_share)
                or equal_share
            )

            min_limit = max(4, default_limit - 4)
            max_limit = min(cls.MAX_RESULTS, default_limit + 4)
            adjustment = round(
                (
                    allocation - equal_share
                )
                * channel_count
                * 2
            )
            limit = min(
                max(
                    default_limit + adjustment,
                    min_limit,
                ),
                max_limit,
            )

            plan_items.append({
                "section": section,
                "algorithm": algorithm,
                "channel_key": channel_key,
                "allocation": round(allocation, 4),
                "limit": int(limit),
                "_default_order": len(plan_items),
            })

        plan_items.sort(
            key=lambda item: (
                -item["allocation"],
                item["_default_order"],
                item["section"],
                item["algorithm"],
            )
        )

        plan = {}

        for priority, item in enumerate(plan_items, start=1):
            item = {
                key: value
                for key, value in item.items()
                if key != "_default_order"
            }
            item["priority"] = priority
            plan[item["section"]] = item

        cache.set(
            cache_key,
            plan,
            cls.RECOMMENDATION_CHANNEL_ALLOCATION_CACHE_TTL,
        )

        return plan

    @classmethod
    def recommendation_exposure_for(
        cls,
        *,
        section,
        algorithm="",
    ):
        """
        Return a safe exposure-plan entry for one channel.
        """
        plan = cls.recommendation_exposure_plan()

        if section in plan:
            return plan[section]

        config = cls.RECOMMENDATION_CHANNELS.get(
            section,
            {},
        )
        resolved_algorithm = (
            algorithm
            or config.get("algorithm", "")
        )
        default_limit = int(
            config.get("default_limit", 8)
            or 8
        )

        return {
            "section": section or "",
            "algorithm": (
                resolved_algorithm
                or cls.RECOMMENDATION_CHANNEL_UNKNOWN_ALGORITHM
            ),
            "channel_key": cls._recommendation_channel_key(
                section=section,
                algorithm=resolved_algorithm,
            ),
            "allocation": 0.0,
            "priority": len(cls.RECOMMENDATION_CHANNELS) + 1,
            "limit": min(
                max(default_limit, 4),
                cls.MAX_RESULTS,
            ),
        }

    @classmethod
    def _empty_recommendation_channel_stats(
        cls,
        *,
        section,
        algorithm,
    ):
        return {
            "section": section,
            "algorithm": algorithm,
            "impressions": 0,
            "clicks": 0,
            "paid_orders": 0,
            "unique_buyers": 0,
            "raw_ctr": 0.0,
            "smoothed_ctr": 0.0,
            "raw_purchase_cvr": 0.0,
            "smoothed_purchase_cvr": 0.0,
            "performance_score": 0.0,
            "bonus": 0.0,
        }

    @classmethod
    def _recommendation_channel_key_from_row(cls, row):
        section = row.get("recommendation_section")
        algorithm = row.get("recommendation_algorithm")
        key = cls._recommendation_channel_key(
            section=section,
            algorithm=algorithm,
        )

        if not key:
            return None, "", ""

        normalized_section = section.strip()
        normalized_algorithm = (
            algorithm.strip()
            if algorithm and algorithm.strip()
            else cls.RECOMMENDATION_CHANNEL_UNKNOWN_ALGORITHM
        )

        return key, normalized_section, normalized_algorithm

    @classmethod
    def _recommendation_channel_key(
        cls,
        *,
        section,
        algorithm="",
    ):
        if not section or not section.strip():
            return ""

        normalized_section = section.strip()
        normalized_algorithm = (
            algorithm.strip()
            if algorithm and algorithm.strip()
            else cls.RECOMMENDATION_CHANNEL_UNKNOWN_ALGORITHM
        )

        return f"{normalized_section}::{normalized_algorithm}"

    @staticmethod
    def _smoothed_rate(
        *,
        successes,
        trials,
        prior_rate,
        prior_trials,
    ):
        return (
            (
                successes
                + (prior_rate * prior_trials)
            )
            / (
                trials
                + prior_trials
            )
        )

    @classmethod
    def _recommendation_cache_key(
        cls,
        kind,
        product_id,
        limit,
    ):
        return (
            f"arolana:recommendations:"
            f"{cls.RECOMMENDATION_CACHE_VERSION}:"
            f"{kind}:"
            f"{product_id}:"
            f"{limit}"
        )

    @classmethod
    def frequently_bought_together(
        cls,
        product,
        limit=8,
    ):
        """
        Return products that are genuinely bought together with ``product``.

        This deliberately builds on the real co-purchase engine rather than
        creating a second OrderItem implementation.

        Preference is given to complementary products from another category
        because those are generally better bundle candidates than alternative
        versions of the same product.
        """

        results = cls.customers_who_bought_this_also_bought(
            product=product,
            limit=max(limit * 4, 24),
        )

        if not results:
            return []

        def bundle_score(item):
            candidate = item["product"]

            score = float(
                item.get(
                    "score",
                    0,
                )
                or 0
            )

            # Products from another category are usually more useful
            # as bundle/add-on recommendations.
            if (
                getattr(candidate, "category_id", None)
                and getattr(product, "category_id", None)
                and candidate.category_id != product.category_id
            ):
                score += 75

            # Real repeated co-purchases remain the strongest signal.
            score += (
                int(
                    item.get(
                        "co_purchase_orders",
                        0,
                    )
                    or 0
                )
                * 25
            )

            score += (
                int(
                    item.get(
                        "unique_buyers",
                        0,
                    )
                    or 0
                )
                * 10
            )

            return score

        # Frequently Bought Together should focus on complementary
        # products rather than alternative products from the same category.
        complementary_results = [
            item
            for item in results
            if (
                getattr(item["product"], "category_id", None)
                and getattr(product, "category_id", None)
                and item["product"].category_id != product.category_id
            )
        ]

        ranked = sorted(
            complementary_results,
            key=bundle_score,
            reverse=True,
        )

        return [
            item["product"]
            for item in ranked[:limit]
        ]

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
    def customers_also_viewed(
        cls,
        product,
        limit=10,
        days=90,
    ):
        """
        Return products viewed by the same users or guest sessions
        that viewed the supplied product.
        """

        if not product:
            return []

        limit = cls._normalize_limit(
            limit,
            default=10,
        )

        try:
            days = max(
                int(days or 90),
                1,
            )
        except (TypeError, ValueError):
            days = 90

        cache_key = (
            f"arolana:recommendations:"
            f"{cls.RECOMMENDATION_CACHE_VERSION}:"
            f"also-viewed:"
            f"{product.pk}:"
            f"{limit}:"
            f"{days}"
        )

        cached_ids = cache.get(cache_key)

        if cached_ids is not None:
            products_by_id = (
                cls._base_queryset()
                .filter(id__in=cached_ids)
                .in_bulk()
            )

            return [
                products_by_id[product_id]
                for product_id in cached_ids
                if product_id in products_by_id
            ]

        cutoff = (
            timezone.now()
            - timezone.timedelta(
                days=days,
            )
        )

        view_events = (
            ClickEvent.objects
            .filter(
                event_type=ClickEvent.EVENT_PRODUCT,
                clicked_text="View Product",
                is_bot=False,
                created_at__gte=cutoff,
            )
            .exclude(product_id="")
        )

        source_events = view_events.filter(
            product_id=str(product.pk),
        )

        session_keys = set(
            source_events
            .exclude(session_key="")
            .values_list(
                "session_key",
                flat=True,
            )
            .distinct()
        )

        user_ids = set(
            source_events
            .exclude(user_id=None)
            .values_list(
                "user_id",
                flat=True,
            )
            .distinct()
        )

        if not session_keys and not user_ids:
            return []

        related_events = view_events.exclude(
            product_id=str(product.pk),
        )

        if session_keys and user_ids:
            from django.db.models import Q

            related_events = related_events.filter(
                Q(session_key__in=session_keys)
                | Q(user_id__in=user_ids)
            )
        elif session_keys:
            related_events = related_events.filter(
                session_key__in=session_keys,
            )
        else:
            related_events = related_events.filter(
                user_id__in=user_ids,
            )

        identity_product_pairs = set()
        product_scores = Counter()

        for event in related_events.only(
            "product_id",
            "session_key",
            "user_id",
            "created_at",
        ):
            product_id = str(
                event.product_id or ""
            ).strip()

            if not product_id:
                continue

            identity = (
                f"user:{event.user_id}"
                if event.user_id
                else f"session:{event.session_key}"
            )

            if identity.endswith(":"):
                continue

            pair = (
                identity,
                product_id,
            )

            if pair in identity_product_pairs:
                continue

            identity_product_pairs.add(pair)

            age_days = max(
                (
                    timezone.now()
                    - event.created_at
                ).days,
                0,
            )

            recency_bonus = max(
                1.0,
                5.0 - (
                    age_days / 30
                ),
            )

            product_scores[product_id] += (
                10.0
                + recency_bonus
            )

        if not product_scores:
            return []

        ranked_ids = [
            product_id
            for product_id, _score
            in product_scores.most_common(
                cls.MAX_CANDIDATES
            )
        ]

        valid_product_ids = []

        for product_id in ranked_ids:
            try:
                valid_product_ids.append(
                    int(product_id)
                )
            except (TypeError, ValueError):
                continue

        products = list(
            cls._base_queryset()
            .filter(
                id__in=valid_product_ids,
            )
        )

        product_by_id = {
            str(item.id): item
            for item in products
        }

        ordered = [
            product_by_id[product_id]
            for product_id in ranked_ids
            if product_id in product_by_id
        ]

        ordered = ordered[:limit]

        cache.set(
            cache_key,
            [item.id for item in ordered],
            cls.ALSO_VIEWED_CACHE_TTL,
        )

        return ordered

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

        conversion_stats = cls.recommendation_conversion_stats(
            source_product=source_product,
        )

        conversion_data = conversion_stats.get(
            candidate.id,
            {},
        )

        conversion_bonus = float(
            conversion_data.get(
                "bonus",
                0,
            )
            or 0
        )

        if conversion_bonus:
            score += conversion_bonus
            reasons.append(
                "Purchased after similar recommendations"
            )

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

        cache_key = cls._recommendation_cache_key(
            kind="similar",
            product_id=product.pk,
            limit=limit,
        )

        cached_ids = cache.get(
            cache_key
        )

        if (
            cached_ids is not None
            and not include_scores
        ):
            products_by_id = (
                cls._base_queryset()
                .filter(
                    id__in=cached_ids
                )
                .in_bulk()
            )

            return [
                products_by_id[product_id]
                for product_id in cached_ids
                if product_id in products_by_id
            ]

        candidates = list(
            cls._base_queryset()
            .exclude(
                pk=product.pk
            )
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

        cache.set(
            cache_key,
            [
                item["product"].id
                for item in ranked
            ],
            cls.SIMILAR_CACHE_TTL,
        )

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
        product=None,
        limit=8,
        exclude_ids=None,
        include_scores=False,
    ):
        limit = cls._normalize_limit(
            limit,
            default=8,
        )

        excluded = {
            int(product_id)
            for product_id in (exclude_ids or [])
            if product_id
        }

        if product and getattr(product, "pk", None):
            excluded.add(product.pk)

        queryset = cls._base_queryset()

        if excluded:
            queryset = queryset.exclude(id__in=excluded)

        if product and getattr(product, "pk", None):
            candidates = list(
                queryset.order_by(
                    "-rating_avg",
                    "-rating_count",
                    "-sales_count",
                    "-is_featured",
                )[:cls.MAX_CANDIDATES]
            )

            ranked = []

            for candidate in candidates:
                scored = cls.score_product(
                    product,
                    candidate,
                )
                scored["score"] += int(
                    float(candidate.rating_avg or 0) * 10
                )
                scored["score"] += min(
                    int(candidate.rating_count or 0),
                    50,
                )
                ranked.append(scored)

            ranked = sorted(
                ranked,
                key=lambda item: item["score"],
                reverse=True,
            )[:limit]

            if include_scores:
                return ranked

            return [
                item["product"]
                for item in ranked
            ]

        products = list(
            queryset.order_by(
                "-rating_avg",
                "-rating_count",
                "-sales_count",
            )[:limit]
        )

        if include_scores:
            return [
                {
                    "product": item,
                    "score": None,
                    "reasons": [],
                    "reason": "Top rated product",
                }
                for item in products
            ]

        return products

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

            reasons = list(
                scored["reasons"]
            )

            if not reasons:
                if getattr(
                    candidate,
                    "is_featured",
                    False,
                ):
                    reasons.append(
                        "Featured pick"
                    )

                elif int(
                    getattr(
                        candidate,
                        "sales_count",
                        0,
                    )
                    or 0
                ) > 0:
                    reasons.append(
                        "Popular on Arolana"
                    )

                elif float(
                    getattr(
                        candidate,
                        "rating_avg",
                        0,
                    )
                    or 0
                ) >= 4:
                    reasons.append(
                        "Highly rated"
                    )

                else:
                    reasons.append(
                        "Recommended for you"
                    )

            ranked.append(
                {
                    "product": candidate,
                    "score": scored["score"],
                    "reasons": reasons,
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

            reasons = list(scored["reasons"])

            if not reasons:
                if getattr(product, "is_featured", False):
                    reasons.append("Featured pick")
                elif int(getattr(product, "sales_count", 0) or 0) > 0:
                    reasons.append("Popular on Arolana")
                elif float(getattr(product, "rating_avg", 0) or 0) >= 4:
                    reasons.append("Highly rated")
                else:
                    reasons.append("Recommended for you")

            results.append(
                {
                    "product": product,
                    "score": scored["score"],
                    "reasons": reasons,
                }
            )

        return results

    @classmethod
    def contextual_product_recommendations(
        cls,
        request,
        product,
        limit=12,
    ):
        """
        Product-page recommendations that combine:

        - product similarity,
        - customer behaviour,
        - popularity signals.

        Keeps recommendations relevant to the current product while
        still personalizing them for the shopper.
        """

        limit = cls._normalize_limit(
            limit,
            default=12,
        )

        exclude_ids = {
            product.id,
        }

        profile = BehaviorProfileBuilder.build(
            request=request,
            exclude_purchased=False,
        )

        candidates = list(
            cls._base_queryset()
            .exclude(id__in=exclude_ids)
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
            similarity = cls.score_product(
                product,
                candidate,
            )

            behavior = cls._behavior_profile_score(
                candidate=candidate,
                profile=profile,
            )

            similarity_score = float(
                similarity.get("score", 0)
                or 0
            )

            behavior_score = float(
                behavior.get("score", 0)
                or 0
            )

            # Current product relevance is the strongest signal.
            final_score = (
                similarity_score * 0.70
                + behavior_score * 0.30
            )

            if (
                product.category_id
                and candidate.category_id == product.category_id
            ):
                final_score += 40

            reasons = []

            for reason in similarity.get(
                "reasons",
                [],
            ):
                if reason not in reasons:
                    reasons.append(reason)

            for reason in behavior.get(
                "reasons",
                [],
            ):
                if reason not in reasons:
                    reasons.append(reason)

            if not reasons:
                reasons.append(
                    "Recommended for you"
                )

            ranked.append({
                "product": candidate,
                "score": round(
                    final_score,
                    2,
                ),
                "reasons": reasons[:3],
            })

        ranked.sort(
            key=lambda item: item["score"],
            reverse=True,
        )

        return ranked[:limit]

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
