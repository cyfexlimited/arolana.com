from django import template

from core.media_optimization import get_optimized_image_url

register = template.Library()


@register.filter(name="optimized_image_url")
def optimized_image_url_filter(image, preset="product_card"):
    return get_optimized_image_url(image, preset)


@register.simple_tag(name="optimized_image_url")
def optimized_image_url_tag(image, preset="product_card"):
    return get_optimized_image_url(image, preset)
