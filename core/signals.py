from django.apps import apps
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.background_tasks import submit_background
from core.media_optimization import get_optimized_image_url
from products.models import (
    Accessory,
    Category,
    Product,
    ProductImage,
    ProductListingBanner,
    ProductVariant,
    ProductVariantImage,
)


MEDIA_PRESETS = {
    Category: (
        ('image', 'nav_icon'),
        ('image', 'category_card'),
        ('background_image', 'category_card'),
        ('background_image', 'hero'),
    ),
    Product: (
        ('main_image', 'product_thumb'),
        ('main_image', 'product_card'),
        ('main_image', 'product_detail'),
        ('video_thumbnail', 'product_thumb'),
    ),
    ProductImage: (
        ('image', 'product_thumb'),
        ('image', 'product_card'),
        ('image', 'product_detail'),
    ),
    ProductVariant: (
        ('image', 'product_thumb'),
        ('image', 'product_card'),
        ('image', 'product_detail'),
    ),
    ProductVariantImage: (
        ('image', 'product_thumb'),
        ('image', 'product_card'),
        ('image', 'product_detail'),
    ),
    Accessory: (('image', 'accessory_thumb'),),
    ProductListingBanner: (
        ('background_image', 'hero'),
        ('side_image', 'category_card'),
    ),
}


def _generate_model_media(model_label, object_id):
    model = apps.get_model(model_label)
    obj = model.objects.filter(pk=object_id).first()
    if not obj:
        return

    for field_name, preset in MEDIA_PRESETS.get(model, ()):
        image = getattr(obj, field_name, None)
        if image:
            get_optimized_image_url(image, preset, force_generate=True)


@receiver(post_save, sender=Category)
@receiver(post_save, sender=Product)
@receiver(post_save, sender=ProductImage)
@receiver(post_save, sender=ProductVariant)
@receiver(post_save, sender=ProductVariantImage)
@receiver(post_save, sender=Accessory)
@receiver(post_save, sender=ProductListingBanner)
def optimize_storefront_media_after_save(sender, instance, **kwargs):
    presets = MEDIA_PRESETS.get(sender, ())
    if not any(getattr(instance, field_name, None) for field_name, _preset in presets):
        return

    model_label = instance._meta.label
    object_id = instance.pk
    transaction.on_commit(
        lambda: submit_background(_generate_model_media, model_label, object_id)
    )
