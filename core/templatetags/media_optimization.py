from django import template

from core.media_optimization import get_optimized_image_url, get_seo_media_url


register = template.Library()


@register.simple_tag
def optimized_image_url(image, preset="product_card"):
    return get_optimized_image_url(image, preset)


@register.simple_tag(takes_context=True)
def seo_media_url(context, image, preset=None):
    request = context.get("request")
    return get_seo_media_url(image, preset=preset, request=request)