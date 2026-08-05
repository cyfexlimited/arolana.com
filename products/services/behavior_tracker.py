from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from django.utils import timezone

from products.models import RecentlyViewed
from visitor_analytics.models import ClickEvent


GUEST_RECENTLY_VIEWED_KEY = "guest_recently_viewed_products"
MAX_GUEST_RECENTLY_VIEWED = 40


class BehaviorTracker:
    """
    Central customer-behaviour tracking service.

    This service reuses:
    - RecentlyViewed for product browsing history.
    - ClickEvent for user actions and recommendation signals.
    - PageVisit middleware for normal page-visit analytics.

    Tracking failures must never prevent the customer's requested action.
    """

    @staticmethod
    def _safe_text(value: Any, max_length: int = 500) -> str:
        return str(value or "").strip()[:max_length]

    @staticmethod
    def _ensure_session_key(request) -> str:
        try:
            if not request.session.session_key:
                request.session.create()

            return request.session.session_key or ""
        except Exception:
            return ""

    @staticmethod
    def _client_ip(request) -> str | None:
        meta = getattr(request, "META", {}) or {}

        forwarded_for = meta.get("HTTP_CF_CONNECTING_IP")
        if forwarded_for:
            return forwarded_for.strip()

        forwarded_for = meta.get("HTTP_X_FORWARDED_FOR")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        return meta.get("REMOTE_ADDR") or None

    @staticmethod
    def _country(request) -> str:
        meta = getattr(request, "META", {}) or {}

        return (
            meta.get("HTTP_CF_IPCOUNTRY")
            or meta.get("HTTP_X_COUNTRY_CODE")
            or ""
        )[:10]

    @staticmethod
    def _user_agent(request) -> str:
        meta = getattr(request, "META", {}) or {}
        return str(meta.get("HTTP_USER_AGENT") or "")

    @staticmethod
    def _is_bot(user_agent: str) -> bool:
        value = user_agent.lower()

        bot_markers = (
            "bot",
            "crawler",
            "spider",
            "slurp",
            "bingpreview",
            "facebookexternalhit",
            "googleinspectiontool",
            "headlesschrome",
            "python-requests",
            "curl/",
            "wget/",
        )

        return any(marker in value for marker in bot_markers)

    @staticmethod
    def _referrer(request) -> str:
        meta = getattr(request, "META", {}) or {}
        return str(meta.get("HTTP_REFERER") or "")[:1000]

    @classmethod
    def _referrer_domain(cls, request) -> str:
        referrer = cls._referrer(request)

        if not referrer:
            return ""

        try:
            return urlparse(referrer).netloc[:255]
        except Exception:
            return ""

    @staticmethod
    def _page_url(request) -> str:
        try:
            return request.build_absolute_uri()[:1000]
        except Exception:
            return ""

    @staticmethod
    def _path(request) -> str:
        return str(getattr(request, "path", "") or "")[:1000]

    @staticmethod
    def _utm_value(request, name: str) -> str:
        try:
            return str(request.GET.get(name) or "")[:255]
        except Exception:
            return ""

    @classmethod
    def _traffic_source(cls, request) -> str:
        utm_source = cls._utm_value(request, "utm_source")

        if utm_source:
            return utm_source[:100]

        domain = cls._referrer_domain(request)

        if not domain:
            return "direct"

        domain_lower = domain.lower()

        if "google." in domain_lower:
            return "google"

        if "facebook." in domain_lower or "instagram." in domain_lower:
            return "meta"

        if "tiktok." in domain_lower:
            return "tiktok"

        if "youtube." in domain_lower:
            return "youtube"

        if "whatsapp." in domain_lower:
            return "whatsapp"

        return "referral"

    @classmethod
    def _base_event_data(cls, request) -> dict:
        user_agent = cls._user_agent(request)
        user = getattr(request, "user", None)

        authenticated_user = (
            user
            if user is not None
            and getattr(user, "is_authenticated", False)
            else None
        )

        return {
            "user": authenticated_user,
            "ip_address": cls._client_ip(request),
            "country": cls._country(request),
            "user_agent": user_agent,
            "referrer": cls._referrer(request),
            "referrer_domain": cls._referrer_domain(request),
            "traffic_source": cls._traffic_source(request),
            "utm_source": cls._utm_value(request, "utm_source"),
            "utm_medium": cls._utm_value(request, "utm_medium"),
            "utm_campaign": cls._utm_value(request, "utm_campaign"),
            "utm_content": cls._utm_value(request, "utm_content"),
            "utm_term": cls._utm_value(request, "utm_term"),
            "page_url": cls._page_url(request),
            "path": cls._path(request),
            "session_key": cls._ensure_session_key(request),
            "is_authenticated": authenticated_user is not None,
            "is_bot": cls._is_bot(user_agent),
        }

    @classmethod
    def _record_click_event(
        cls,
        *,
        request,
        event_type: str,
        clicked_text: str,
        clicked_url: str = "",
        product_id: Any = "",
        category_id: Any = "",
        vendor_id: Any = "",
        element_tag: str = "",
        element_id: str = "",
        element_classes: str = "",
    ):
        try:
            event_data = cls._base_event_data(request)

            if event_data["is_bot"]:
                return None

            return ClickEvent.objects.create(
                **event_data,
                event_type=event_type,
                clicked_text=cls._safe_text(
                    clicked_text,
                    max_length=500,
                ),
                clicked_url=cls._safe_text(
                    clicked_url,
                    max_length=1000,
                ),
                product_id=cls._safe_text(
                    product_id,
                    max_length=100,
                ),
                category_id=cls._safe_text(
                    category_id,
                    max_length=100,
                ),
                vendor_id=cls._safe_text(
                    vendor_id,
                    max_length=100,
                ),
                element_tag=cls._safe_text(
                    element_tag,
                    max_length=50,
                ),
                element_id=cls._safe_text(
                    element_id,
                    max_length=200,
                ),
                element_classes=cls._safe_text(
                    element_classes,
                    max_length=500,
                ),
            )
        except Exception:
            return None

    @classmethod
    def _save_guest_recently_viewed(
        cls,
        request,
        product,
    ) -> None:
        try:
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

            updated = [
                product.id,
                *[
                    product_id
                    for product_id in cleaned
                    if product_id != product.id
                ],
            ]

            request.session[
                GUEST_RECENTLY_VIEWED_KEY
            ] = updated[:MAX_GUEST_RECENTLY_VIEWED]

            request.session.modified = True
        except Exception:
            return

    @classmethod
    def product_view(
        cls,
        request,
        product,
    ):
        """
        Save recently viewed history.

        Normal page traffic remains handled by PageVisit middleware,
        so this method does not create a duplicate PageVisit row.
        """

        if not product:
            return None

        try:
            user = getattr(request, "user", None)

            if (
                user is not None
                and getattr(user, "is_authenticated", False)
            ):
                RecentlyViewed.objects.update_or_create(
                    user=user,
                    product=product,
                    defaults={
                        "viewed_at": timezone.now(),
                    },
                )
            else:
                cls._save_guest_recently_viewed(
                    request,
                    product,
                )
        except Exception:
            return None

        return product

    @classmethod
    def product_click(
        cls,
        request,
        product,
        clicked_text="View Product",
    ):
        if not product:
            return None

        try:
            product_url = product.get_absolute_url()
        except Exception:
            product_url = ""

        return cls._record_click_event(
            request=request,
            event_type=ClickEvent.EVENT_PRODUCT,
            clicked_text=clicked_text,
            clicked_url=product_url,
            product_id=product.pk,
            category_id=getattr(
                product,
                "category_id",
                "",
            ),
            vendor_id=getattr(
                product,
                "vendor_id",
                "",
            ),
        )

    @classmethod
    def search(
        cls,
        request,
        query,
        *,
        context="products",
        result_count=None,
    ):
        query = cls._safe_text(
            query,
            max_length=500,
        )

        if not query:
            return None

        context = cls._safe_text(
            context,
            max_length=50,
        ) or "products"

        result_text = ""

        if result_count is not None:
            try:
                result_text = f"; results={int(result_count)}"
            except (TypeError, ValueError):
                result_text = ""

        return cls._record_click_event(
            request=request,
            event_type=ClickEvent.EVENT_BUTTON,
            clicked_text=(
                f"Search [{context}]: "
                f"{query}"
                f"{result_text}"
            ),
            element_tag="search",
            element_id=f"{context}-search",
        )

    @classmethod
    def category_view(
        cls,
        request,
        category,
    ):
        if not category:
            return None

        try:
            category_url = category.get_absolute_url()
        except Exception:
            category_url = ""

        return cls._record_click_event(
            request=request,
            event_type=ClickEvent.EVENT_CATEGORY,
            clicked_text=getattr(
                category,
                "name",
                "Category",
            ),
            clicked_url=category_url,
            category_id=category.pk,
        )

    @classmethod
    def vendor_view(
        cls,
        request,
        vendor,
    ):
        if not vendor:
            return None

        vendor_name = (
            getattr(vendor, "store_name", "")
            or getattr(vendor, "company_name", "")
            or str(vendor)
        )

        try:
            vendor_url = vendor.get_absolute_url()
        except Exception:
            vendor_url = ""

        return cls._record_click_event(
            request=request,
            event_type=ClickEvent.EVENT_VENDOR,
            clicked_text=vendor_name,
            clicked_url=vendor_url,
            vendor_id=vendor.pk,
        )

    @classmethod
    def add_to_cart(
        cls,
        request,
        product,
        quantity=1,
    ):
        if not product:
            return None

        return cls._record_click_event(
            request=request,
            event_type=ClickEvent.EVENT_PRODUCT,
            clicked_text=(
                f"Add to cart: {product.name} "
                f"(quantity {quantity})"
            ),
            product_id=product.pk,
            category_id=getattr(
                product,
                "category_id",
                "",
            ),
            vendor_id=getattr(
                product,
                "vendor_id",
                "",
            ),
            element_tag="button",
            element_id="add-to-cart",
        )

    @classmethod
    def add_to_wishlist(
        cls,
        request,
        product,
    ):
        if not product:
            return None

        return cls._record_click_event(
            request=request,
            event_type=ClickEvent.EVENT_PRODUCT,
            clicked_text=(
                f"Add to wishlist: {product.name}"
            ),
            product_id=product.pk,
            category_id=getattr(
                product,
                "category_id",
                "",
            ),
            vendor_id=getattr(
                product,
                "vendor_id",
                "",
            ),
            element_tag="button",
            element_id="add-to-wishlist",
        )

    @classmethod
    def remove_from_wishlist(
        cls,
        request,
        product,
    ):
        if not product:
            return None

        return cls._record_click_event(
            request=request,
            event_type=ClickEvent.EVENT_PRODUCT,
            clicked_text=(
                f"Remove from wishlist: {product.name}"
            ),
            product_id=product.pk,
            category_id=getattr(
                product,
                "category_id",
                "",
            ),
            vendor_id=getattr(
                product,
                "vendor_id",
                "",
            ),
            element_tag="button",
            element_id="remove-from-wishlist",
        )

    @classmethod
    def purchase_product(
        cls,
        request,
        product,
        order=None,
        quantity=1,
    ):
        if not product:
            return None

        order_reference = (
            getattr(order, "order_number", "")
            or getattr(order, "reference", "")
            or getattr(order, "pk", "")
            or ""
        )

        return cls._record_click_event(
            request=request,
            event_type=ClickEvent.EVENT_PRODUCT,
            clicked_text=(
                f"Purchase: {product.name}; "
                f"quantity={quantity}; "
                f"order={order_reference}"
            ),
            product_id=product.pk,
            category_id=getattr(
                product,
                "category_id",
                "",
            ),
            vendor_id=getattr(
                product,
                "vendor_id",
                "",
            ),
            element_tag="checkout",
            element_id="purchase-completed",
        )

    @classmethod
    def article_view(
        cls,
        request,
        article,
    ):
        if not article:
            return None

        try:
            article_url = article.get_absolute_url()
        except Exception:
            article_url = ""

        return cls._record_click_event(
            request=request,
            event_type=ClickEvent.EVENT_LINK,
            clicked_text=(
                f"Article: "
                f"{getattr(article, 'title', str(article))}"
            ),
            clicked_url=article_url,
            element_tag="article",
            element_id="article-view",
        )

    @classmethod
    def provider_view(
        cls,
        request,
        provider,
    ):
        if not provider:
            return None

        try:
            provider_url = provider.get_absolute_url()
        except Exception:
            provider_url = ""

        return cls._record_click_event(
            request=request,
            event_type=ClickEvent.EVENT_VENDOR,
            clicked_text=(
                f"Service provider: "
                f"{getattr(provider, 'business_name', str(provider))}"
            ),
            clicked_url=provider_url,
            vendor_id=provider.pk,
            element_tag="provider",
            element_id="service-provider-view",
        )
