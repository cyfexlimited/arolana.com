from django import template

from ads.frontend import recommendation_shelf


register = template.Library()


@register.inclusion_tag("ads/partials/v2_recommendation_shelf.html", takes_context=True)
def ads_v2_recommendation_shelf(context, placement, limit=8, **kwargs):
    request = context.get("request")
    if request is None:
        return {"enabled": False, "results": []}
    return recommendation_shelf(
        request,
        placement=placement,
        limit=limit,
        **kwargs,
    )
