from django import template

from hero_banners.models import HeroBanner
from hero_banners.views import get_active_banners


register = template.Library()


@register.inclusion_tag(
    "hero_banners/carousel.html",
    takes_context=True,
)
def hero_carousel(context):
    request = context.get("request")

    banners = get_active_banners(
        request,
        placement=HeroBanner.PLACEMENT_HOME,
    )

    return {
        "banners": banners,
        "request": request,
    }