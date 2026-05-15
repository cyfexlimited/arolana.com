from django import template

from core.media_optimization import get_optimized_image_url


register = template.Library()


@register.simple_tag
def optimized_image_url(image, preset='product_card'):
    return get_optimized_image_url(image, preset)
