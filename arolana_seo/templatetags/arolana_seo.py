from django import template
from django.utils.safestring import mark_safe

from arolana_seo.utils import (
    category_seo_description,
    category_seo_title,
    canonical_url_for_product,
    merchant_metadata,
    product_image_alt,
    product_schema_json,
    seo_description_for_product,
    seo_title_for_product,
)

register = template.Library()


@register.simple_tag(takes_context=True)
def product_seo_title(context, product):
    return seo_title_for_product(product)


@register.simple_tag(takes_context=True)
def product_seo_description(context, product):
    return seo_description_for_product(product)


@register.simple_tag(takes_context=True)
def product_canonical_url(context, product):
    request = context.get("request")
    return canonical_url_for_product(product, request)


@register.simple_tag(takes_context=True)
def product_schema_ld(context, product, currency_code="NGN"):
    request = context.get("request")
    return mark_safe(product_schema_json(product, request, currency_code))


@register.simple_tag
def product_alt(product, image=None):
    return product_image_alt(product, image)


@register.simple_tag(takes_context=True)
def product_merchant_metadata(context, product, currency_code="NGN"):
    request = context.get("request")
    return merchant_metadata(product, request, currency_code)


@register.simple_tag
def category_title(category):
    return category_seo_title(category)


@register.simple_tag
def category_description(category):
    return category_seo_description(category)
