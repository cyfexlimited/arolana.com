class V2RecommendationAdapter:
    """Presentation adapter for Ads V2 recommendation payloads.

    The decisioning service remains the source of ranking, sponsorship, and
    tracking identity. This adapter only reshapes safe fields for existing web,
    mobile web, and app renderers.
    """

    SUPPORTED_TYPES = {
        "product",
        "product_video",
        "service",
        "provider",
        "store",
        "vendor_store",
        "provider_profile",
        "provider_service",
    }

    def adapt_results(self, results, *, surface="", client="web"):
        return [self.adapt_result(item, surface=surface, client=client) for item in results]

    def adapt_result(self, item, *, surface="", client="web"):
        item_payload = item.get("item") or {}
        tracking = item.get("tracking") or {}
        result_type = item.get("type") or ""
        normalized_type = self._normalized_type(result_type)
        label = item.get("label") if item.get("sponsored") else ""

        return {
            "type": normalized_type,
            "id": item.get("id"),
            "title": item_payload.get("name") or item_payload.get("title") or "",
            "url": item_payload.get("url") or "",
            "item": item_payload,
            "sponsored": bool(item.get("sponsored")),
            "label": label,
            "sponsor": item.get("sponsor") if item.get("sponsored") else None,
            "tracking": {
                "delivery_id": tracking.get("delivery_id") or "",
                "asset_id": tracking.get("asset_id"),
                "campaign_id": tracking.get("campaign_id"),
                "delivery_token": tracking.get("delivery_token") or "",
            },
            "ui": {
                "surface": surface,
                "client": client,
                "badge": "Sponsored" if item.get("sponsored") else "",
                "component": self._component_for_type(normalized_type),
            },
        }

    def _normalized_type(self, result_type):
        if result_type == "vendor_store":
            return "store"
        if result_type == "provider_profile":
            return "provider"
        if result_type == "provider_service":
            return "service"
        return result_type

    def _component_for_type(self, result_type):
        return {
            "product": "product_card",
            "product_video": "video_card",
            "service": "service_card",
            "provider": "provider_card",
            "store": "store_card",
        }.get(result_type, "recommendation_card")


v2_recommendation_adapter = V2RecommendationAdapter()
