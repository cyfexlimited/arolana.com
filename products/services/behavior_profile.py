from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
import re

from django.apps import apps
from django.utils import timezone

from products.models import Product, RecentlyViewed, Wishlist
from visitor_analytics.models import ClickEvent


GUEST_RECENTLY_VIEWED_KEY = "guest_recently_viewed_products"


@dataclass
class BehaviorProfile:
    product_scores: dict[int, float] = field(
        default_factory=dict,
    )
    category_scores: dict[int, float] = field(
        default_factory=dict,
    )
    brand_scores: dict[int, float] = field(
        default_factory=dict,
    )
    vendor_scores: dict[int, float] = field(
        default_factory=dict,
    )
    search_terms: dict[str, float] = field(
        default_factory=dict,
    )
    excluded_product_ids: set[int] = field(
        default_factory=set,
    )
    viewed_product_ids: set[int] = field(
        default_factory=set,
    )
    wishlist_product_ids: set[int] = field(
        default_factory=set,
    )
    purchased_product_ids: set[int] = field(
        default_factory=set,
    )

    def as_dict(self):
        return {
            "product_scores": self.product_scores,
            "category_scores": self.category_scores,
            "brand_scores": self.brand_scores,
            "vendor_scores": self.vendor_scores,
            "search_terms": self.search_terms,
            "excluded_product_ids": self.excluded_product_ids,
            "viewed_product_ids": self.viewed_product_ids,
            "wishlist_product_ids": self.wishlist_product_ids,
            "purchased_product_ids": self.purchased_product_ids,
        }


class BehaviorProfileBuilder:
    """
    Build a weighted customer-interest profile from existing Arolana data.

    Current signals:
    - Product view: +1
    - Search term: +2
    - Wishlist add: +5
    - Wishlist remove: -3
    - Add to cart: +10
    - Completed/paid purchase: +50

    Recent interactions receive stronger weights through time decay.
    """

    VIEW_WEIGHT = 1.0
    SEARCH_WEIGHT = 2.0
    WISHLIST_ADD_WEIGHT = 5.0
    WISHLIST_REMOVE_WEIGHT = -3.0
    CART_WEIGHT = 10.0
    PURCHASE_WEIGHT = 50.0

    CATEGORY_MULTIPLIER = 1.0
    BRAND_MULTIPLIER = 0.75
    VENDOR_MULTIPLIER = 0.50

    MAX_EVENTS = 500
    MAX_RECENT_PRODUCTS = 80
    MAX_WISHLIST_ITEMS = 100
    MAX_PURCHASE_ITEMS = 200

    SEARCH_PREFIXES = (
        "Search:",
        "Search [",
    )

    @staticmethod
    def _safe_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_float(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _time_decay(cls, created_at):
        if not created_at:
            return 0.20

        age = timezone.now() - created_at

        if age <= timedelta(days=1):
            return 1.00

        if age <= timedelta(days=7):
            return 0.80

        if age <= timedelta(days=30):
            return 0.50

        return 0.20

    @staticmethod
    def _normalize_search_term(value):
        value = str(value or "").strip().lower()

        value = re.sub(
            r"^search\s*(\[[^\]]+\])?\s*:\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )

        value = value.split("; results=", 1)[0].strip()
        value = re.sub(r"\s+", " ", value)

        return value[:200]

    @staticmethod
    def _guest_recent_ids(request):
        try:
            values = request.session.get(
                GUEST_RECENTLY_VIEWED_KEY,
                [],
            )
        except Exception:
            return []

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
    def _add_product_signal(
        cls,
        *,
        product,
        weight,
        product_scores,
        category_scores,
        brand_scores,
        vendor_scores,
    ):
        if not product:
            return

        product_scores[product.id] += weight

        if product.category_id:
            category_scores[
                product.category_id
            ] += (
                weight
                * cls.CATEGORY_MULTIPLIER
            )

        if product.brand_id:
            brand_scores[
                product.brand_id
            ] += (
                weight
                * cls.BRAND_MULTIPLIER
            )

        if product.vendor_id:
            vendor_scores[
                product.vendor_id
            ] += (
                weight
                * cls.VENDOR_MULTIPLIER
            )

    @classmethod
    def _build_product_map(cls, product_ids):
        if not product_ids:
            return {}

        return (
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

    @classmethod
    def _event_weight(cls, clicked_text):
        text = str(clicked_text or "").strip().lower()

        if text.startswith("add to cart:"):
            return cls.CART_WEIGHT

        if text.startswith("add to wishlist:"):
            return cls.WISHLIST_ADD_WEIGHT

        if text.startswith("remove from wishlist:"):
            return cls.WISHLIST_REMOVE_WEIGHT

        return 0.0

    @classmethod
    def build(
        cls,
        request,
        *,
        exclude_purchased=False,
    ):
        product_scores = defaultdict(float)
        category_scores = defaultdict(float)
        brand_scores = defaultdict(float)
        vendor_scores = defaultdict(float)
        search_terms = defaultdict(float)

        viewed_product_ids = set()
        wishlist_product_ids = set()
        purchased_product_ids = set()
        excluded_product_ids = set()

        user = getattr(request, "user", None)
        is_authenticated = bool(
            user
            and getattr(
                user,
                "is_authenticated",
                False,
            )
        )

        # =========================================================
        # Recently viewed
        # =========================================================

        if is_authenticated:
            recent_rows = list(
                RecentlyViewed.objects
                .filter(user=user)
                .select_related(
                    "product",
                    "product__category",
                    "product__brand",
                    "product__vendor",
                )
                .order_by("-viewed_at")[
                    :cls.MAX_RECENT_PRODUCTS
                ]
            )

            for row in recent_rows:
                product = row.product
                viewed_product_ids.add(product.id)

                weight = (
                    cls.VIEW_WEIGHT
                    * cls._time_decay(
                        row.viewed_at,
                    )
                )

                cls._add_product_signal(
                    product=product,
                    weight=weight,
                    product_scores=product_scores,
                    category_scores=category_scores,
                    brand_scores=brand_scores,
                    vendor_scores=vendor_scores,
                )

        else:
            guest_ids = cls._guest_recent_ids(
                request,
            )[
                :cls.MAX_RECENT_PRODUCTS
            ]

            products_by_id = cls._build_product_map(
                guest_ids,
            )

            for position, product_id in enumerate(
                guest_ids,
            ):
                product = products_by_id.get(
                    product_id,
                )

                if not product:
                    continue

                viewed_product_ids.add(
                    product.id,
                )

                position_decay = max(
                    0.25,
                    1.0 - (position * 0.05),
                )

                cls._add_product_signal(
                    product=product,
                    weight=(
                        cls.VIEW_WEIGHT
                        * position_decay
                    ),
                    product_scores=product_scores,
                    category_scores=category_scores,
                    brand_scores=brand_scores,
                    vendor_scores=vendor_scores,
                )

        # =========================================================
        # Wishlist database state
        # =========================================================

        if is_authenticated:
            wishlist_rows = list(
                Wishlist.objects
                .filter(user=user)
                .select_related(
                    "product",
                    "product__category",
                    "product__brand",
                    "product__vendor",
                )
                .order_by("-added_at")[
                    :cls.MAX_WISHLIST_ITEMS
                ]
            )

            for row in wishlist_rows:
                product = row.product
                wishlist_product_ids.add(
                    product.id,
                )

                weight = (
                    cls.WISHLIST_ADD_WEIGHT
                    * cls._time_decay(
                        row.added_at,
                    )
                )

                cls._add_product_signal(
                    product=product,
                    weight=weight,
                    product_scores=product_scores,
                    category_scores=category_scores,
                    brand_scores=brand_scores,
                    vendor_scores=vendor_scores,
                )

        # =========================================================
        # ClickEvent behavior
        # =========================================================

        session_key = ""

        try:
            session_key = (
                request.session.session_key
                or ""
            )
        except Exception:
            session_key = ""

        events = ClickEvent.objects.filter(
            is_bot=False,
        )

        if is_authenticated:
            events = events.filter(user=user)
        elif session_key:
            events = events.filter(
                session_key=session_key,
            )
        else:
            events = events.none()

        events = list(
            events.order_by("-created_at")[
                :cls.MAX_EVENTS
            ]
        )

        event_product_ids = {
            product_id
            for product_id in (
                cls._safe_int(
                    event.product_id,
                )
                for event in events
            )
            if product_id
        }

        event_product_map = cls._build_product_map(
            event_product_ids,
        )

        for event in events:
            clicked_text = str(
                event.clicked_text
                or ""
            ).strip()

            if clicked_text.lower().startswith(
                "search"
            ):
                term = cls._normalize_search_term(
                    clicked_text,
                )

                if term:
                    search_terms[term] += (
                        cls.SEARCH_WEIGHT
                        * cls._time_decay(
                            event.created_at,
                        )
                    )

                continue

            product_id = cls._safe_int(
                event.product_id,
            )

            if not product_id:
                continue

            product = event_product_map.get(
                product_id,
            )

            if not product:
                continue

            weight = cls._event_weight(
                clicked_text,
            )

            if not weight:
                continue

            weight *= cls._time_decay(
                event.created_at,
            )

            cls._add_product_signal(
                product=product,
                weight=weight,
                product_scores=product_scores,
                category_scores=category_scores,
                brand_scores=brand_scores,
                vendor_scores=vendor_scores,
            )

        # =========================================================
        # Completed or paid purchases
        # =========================================================

        OrderItem = apps.get_model(
            "orders",
            "OrderItem",
        )

        if is_authenticated:
            purchase_rows = list(
                OrderItem.objects
                .filter(
                    order__user=user,
                    product__isnull=False,
                )
                .filter(
                    order__payment_status__in=[
                        "paid",
                        "successful",
                        "success",
                        "completed",
                    ],
                )
                .exclude(
                    order__status__in=[
                        "cancelled",
                        "refunded",
                    ],
                )
                .select_related(
                    "product",
                    "product__category",
                    "product__brand",
                    "product__vendor",
                    "order",
                )
                .order_by("-created_at")[
                    :cls.MAX_PURCHASE_ITEMS
                ]
            )

            for item in purchase_rows:
                product = item.product

                if not product:
                    continue

                purchased_product_ids.add(
                    product.id,
                )

                quantity = max(
                    int(item.quantity or 1),
                    1,
                )

                quantity_factor = min(
                    Decimal(quantity),
                    Decimal("5"),
                )

                weight = (
                    cls.PURCHASE_WEIGHT
                    * float(quantity_factor)
                    * cls._time_decay(
                        item.created_at,
                    )
                )

                cls._add_product_signal(
                    product=product,
                    weight=weight,
                    product_scores=product_scores,
                    category_scores=category_scores,
                    brand_scores=brand_scores,
                    vendor_scores=vendor_scores,
                )

        if exclude_purchased:
            excluded_product_ids.update(
                purchased_product_ids,
            )

        return BehaviorProfile(
            product_scores=dict(
                product_scores,
            ),
            category_scores=dict(
                category_scores,
            ),
            brand_scores=dict(
                brand_scores,
            ),
            vendor_scores=dict(
                vendor_scores,
            ),
            search_terms=dict(
                search_terms,
            ),
            excluded_product_ids=(
                excluded_product_ids
            ),
            viewed_product_ids=(
                viewed_product_ids
            ),
            wishlist_product_ids=(
                wishlist_product_ids
            ),
            purchased_product_ids=(
                purchased_product_ids
            ),
        )
