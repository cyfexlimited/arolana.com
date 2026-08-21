from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from .models import AdAttribution, AdEvent, CampaignAsset
from .ownership import ownership_resolver


class CommerceAttributionService:
    """Server-authoritative commerce attribution for Ads V2.

    Client events are treated only as signals. Purchase revenue and service lead
    attribution are created from trusted server-side order/quote/video objects.
    """

    TOUCH_EVENT_TYPES = [
        AdEvent.EVENT_CLICK,
        AdEvent.EVENT_VIEW,
        AdEvent.EVENT_IMPRESSION,
    ]

    def find_last_touch(
        self,
        *,
        user=None,
        session_id="",
        product=None,
        asset=None,
        delivery_id=None,
        lookback_days=None,
    ):
        click_lookback_days = int(getattr(settings, "ADS_ATTRIBUTION_CLICK_LOOKBACK_DAYS", 7) or 7)
        view_lookback_days = int(getattr(settings, "ADS_ATTRIBUTION_VIEW_LOOKBACK_DAYS", 1) or 1)
        max_lookback_days = lookback_days or max(click_lookback_days, view_lookback_days)
        qs = AdEvent.objects.filter(
            event_type__in=self.TOUCH_EVENT_TYPES,
            occurred_at__gte=timezone.now() - timedelta(days=max_lookback_days),
        ).select_related("asset", "campaign", "advertiser_identity")

        if delivery_id:
            qs = qs.filter(delivery_id=delivery_id)
        if asset:
            qs = qs.filter(asset=asset)
        elif product is not None:
            product_ct = ContentType.objects.get_for_model(product)
            qs = qs.filter(asset__content_type=product_ct, asset__object_id=product.pk)

        if user and getattr(user, "is_authenticated", False):
            qs = qs.filter(user=user)
        elif session_id:
            qs = qs.filter(session_id=session_id)
        else:
            return None

        ordering = {
            AdEvent.EVENT_CLICK: 0,
            AdEvent.EVENT_VIEW: 1,
            AdEvent.EVENT_IMPRESSION: 2,
        }
        now = timezone.now()
        events = [
            event
            for event in qs.order_by("-occurred_at")[:50]
            if self._event_within_type_window(
                event,
                now=now,
                click_days=click_lookback_days,
                view_days=view_lookback_days,
            )
        ]
        events.sort(key=lambda event: (ordering.get(event.event_type, 99), -event.occurred_at.timestamp()))
        return events[0] if events else None

    def attribute_order_item(
        self,
        order_item,
        *,
        source_event=None,
        delivery_id=None,
        model=AdAttribution.MODEL_LAST_TOUCH,
    ):
        order = getattr(order_item, "order", None)
        product = getattr(order_item, "product", None)
        if product is None:
            return None

        source_event = source_event or self.find_last_touch(
            user=getattr(order, "user", None),
            product=product,
            delivery_id=delivery_id,
        )
        if source_event is None or source_event.asset_id is None:
            return None

        asset = source_event.asset
        if not self._asset_matches_product(asset, product):
            return None

        revenue = self._order_item_revenue(order_item)
        if revenue is None:
            return None

        attribution_type = (
            AdAttribution.ATTR_CLICK_THROUGH
            if source_event.event_type == AdEvent.EVENT_CLICK
            else AdAttribution.ATTR_VIEW_THROUGH
        )
        defaults = self._base_defaults(source_event)
        defaults.update(
            {
                "source_click_event": source_event if source_event.event_type == AdEvent.EVENT_CLICK else None,
                "product": product,
                "vendor": self._vendor_for_product(product),
                "order": order,
                "revenue_amount": revenue,
                "gross_revenue_amount": revenue,
                "net_revenue_amount": revenue,
                "lifecycle_status": AdAttribution.LIFECYCLE_ACTIVE,
                "currency": self._currency_for_order(order),
                "metadata": {
                    "server_authoritative": True,
                    "commerce_event": "order_item_purchase",
                    "order_item_id": order_item.pk,
                    "quantity": getattr(order_item, "quantity", None),
                    "recommendation_section": getattr(order_item, "recommendation_section", ""),
                    "recommendation_algorithm": getattr(order_item, "recommendation_algorithm", ""),
                },
            }
        )
        attribution, _ = AdAttribution.objects.get_or_create(
            source_event=source_event,
            order_item=order_item,
            attribution_type=attribution_type,
            attribution_model=model,
            defaults=defaults,
        )
        return attribution

    def attribute_order(self, order, *, model=AdAttribution.MODEL_LAST_TOUCH):
        return [
            attribution
            for item in order.items.select_related("product", "order").all()
            for attribution in [self.attribute_order_item(item, model=model)]
            if attribution is not None
        ]

    @transaction.atomic
    def reverse_order_attribution(
        self,
        order,
        *,
        reason,
        reference="",
        amount=None,
    ):
        """Reverse or adjust server-authoritative attribution for an order.

        Refunds, cancellations, and payment reversals must not erase attribution
        history. Full reversals mark existing rows as reversed and set net
        revenue to zero. Partial adjustments are only applied when an
        authoritative amount is supplied by the server-side payment/refund flow.
        """
        if order is None:
            return []

        qs = (
            AdAttribution.objects
            .select_for_update()
            .filter(order=order, order_item__isnull=False)
        )
        reversal_reference = str(reference or "")[:160]
        reversal_reason = str(reason or "commerce_reversal")[:80]
        adjustment_amount = self._money_or_none(amount)
        changed = []

        for attribution in qs:
            metadata = dict(attribution.metadata or {})
            applied_refs = metadata.get("reversal_references") or []
            if reversal_reference and reversal_reference in applied_refs:
                continue

            current_net = self._effective_net_revenue(attribution)
            if adjustment_amount is None:
                new_net = Decimal("0.00")
                lifecycle_status = AdAttribution.LIFECYCLE_REVERSED
            else:
                new_net = max(Decimal("0.00"), current_net - adjustment_amount)
                lifecycle_status = (
                    AdAttribution.LIFECYCLE_REVERSED
                    if new_net == Decimal("0.00")
                    else AdAttribution.LIFECYCLE_ADJUSTED
                )

            if reversal_reference:
                applied_refs.append(reversal_reference)

            metadata["reversal_references"] = applied_refs
            metadata["last_reversal_reason"] = reversal_reason
            metadata["last_reversal_amount"] = str(adjustment_amount) if adjustment_amount is not None else "full"
            metadata["server_authoritative_reversal"] = True

            attribution.net_revenue_amount = new_net
            attribution.lifecycle_status = lifecycle_status
            attribution.reversed_at = timezone.now()
            attribution.reversal_reason = reversal_reason
            attribution.reversal_reference = reversal_reference
            attribution.metadata = metadata
            attribution.save(
                update_fields=[
                    "net_revenue_amount",
                    "lifecycle_status",
                    "reversed_at",
                    "reversal_reason",
                    "reversal_reference",
                    "metadata",
                    "updated_at",
                ]
            )
            changed.append(attribution)

        return changed

    def attribute_service_quote(self, quote_request, *, source_event=None, delivery_id=None):
        source_event = source_event or self.find_last_touch(
            user=getattr(quote_request, "customer", None),
            delivery_id=delivery_id,
        )
        if source_event is None:
            return None

        target_ct = ContentType.objects.get_for_model(quote_request)
        defaults = self._base_defaults(source_event)
        defaults.update(
            {
                "revenue_amount": None,
                "currency": "NGN",
                "metadata": {
                    "server_authoritative": True,
                    "commerce_event": "qualified_service_lead",
                    "quote_request_id": quote_request.pk,
                    "provider_id": getattr(quote_request, "provider_id", None),
                    "category_id": getattr(quote_request, "category_id", None),
                    "revenue_unavailable": True,
                },
            }
        )
        attribution, _ = AdAttribution.objects.get_or_create(
            source_event=source_event,
            attribution_type=AdAttribution.ATTR_CLICK_THROUGH
            if source_event.event_type == AdEvent.EVENT_CLICK
            else AdAttribution.ATTR_VIEW_THROUGH,
            attribution_model=AdAttribution.MODEL_LAST_TOUCH,
            target_content_type=target_ct,
            target_object_id=quote_request.pk,
            defaults=defaults,
        )
        return attribution

    def link_video_event(self, video_event, *, source_event=None):
        source_event = source_event or self._source_event_for_video_event(video_event)
        if source_event is None:
            return None

        target_ct = ContentType.objects.get_for_model(video_event)
        defaults = self._base_defaults(source_event)
        defaults.update(
            {
                "product": getattr(video_event, "product", None),
                "vendor": self._vendor_for_product(getattr(video_event, "product", None)),
                "revenue_amount": None,
                "metadata": {
                    "server_authoritative": True,
                    "commerce_event": "video_signal",
                    "video_event_id": video_event.pk,
                    "video_event_type": video_event.event_type,
                    "content_type": video_event.content_type,
                    "source_id": video_event.source_id,
                    "revenue_unavailable": True,
                },
            }
        )
        attribution, _ = AdAttribution.objects.get_or_create(
            source_event=source_event,
            attribution_type=AdAttribution.ATTR_CLICK_THROUGH
            if video_event.event_type == "video_cta_click"
            else AdAttribution.ATTR_VIEW_THROUGH,
            attribution_model=AdAttribution.MODEL_LAST_TOUCH,
            target_content_type=target_ct,
            target_object_id=video_event.pk,
            defaults=defaults,
        )
        return attribution

    def _base_defaults(self, source_event):
        return {
            "delivery_id": source_event.delivery_id,
            "campaign": source_event.campaign,
            "advertiser_identity": source_event.advertiser_identity,
            "asset": source_event.asset,
        }

    def _asset_matches_product(self, asset, product):
        if not asset or not product:
            return False
        if asset.asset_type == CampaignAsset.ASSET_PRODUCT:
            return asset.content_object == product
        if asset.asset_type == CampaignAsset.ASSET_PRODUCT_VIDEO:
            video = asset.product_video or asset.content_object
            return getattr(video, "product_id", None) == product.pk
        return False

    def _vendor_for_product(self, product):
        if product is None:
            return None
        resolution = ownership_resolver.resolve_product_owner(product)
        return resolution.vendor if resolution.is_resolved else None

    def _order_item_revenue(self, order_item):
        value = getattr(order_item, "subtotal", None)
        if value is None:
            price = getattr(order_item, "price", None)
            quantity = getattr(order_item, "quantity", None)
            if price is None or quantity is None:
                return None
            value = Decimal(str(price)) * Decimal(str(quantity))
        return Decimal(str(value)).quantize(Decimal("0.01"))

    def _money_or_none(self, value):
        if value is None:
            return None
        try:
            money = Decimal(str(value)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return money if money > 0 else None

    def _effective_net_revenue(self, attribution):
        value = (
            attribution.net_revenue_amount
            if attribution.net_revenue_amount is not None
            else attribution.revenue_amount
        )
        if value is None:
            return Decimal("0.00")
        return Decimal(str(value)).quantize(Decimal("0.01"))

    def _currency_for_order(self, order):
        return str(getattr(order, "currency", "") or "NGN")[:10]

    def _source_event_for_video_event(self, video_event):
        delivery_id = (video_event.metadata or {}).get("delivery_id")
        asset_id = (video_event.metadata or {}).get("asset_id")
        qs = AdEvent.objects.filter(event_type__in=self.TOUCH_EVENT_TYPES)
        if delivery_id:
            qs = qs.filter(delivery_id=delivery_id)
        if asset_id:
            qs = qs.filter(asset_id=asset_id)
        if getattr(video_event, "user_id", None):
            qs = qs.filter(user_id=video_event.user_id)
        elif getattr(video_event, "session_key", ""):
            qs = qs.filter(session_id=video_event.session_key)
        return qs.order_by("-occurred_at").first()

    def _event_within_type_window(self, event, *, now, click_days, view_days):
        age = now - event.occurred_at
        if event.event_type == AdEvent.EVENT_CLICK:
            return age <= timedelta(days=click_days)
        return age <= timedelta(days=view_days)


commerce_attribution_service = CommerceAttributionService()
