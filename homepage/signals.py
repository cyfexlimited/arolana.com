from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from core.local_cache import local_delete
from products.models import Product
from vendors.models import VendorProfile


@receiver([post_save, post_delete], sender=Product)
@receiver([post_save, post_delete], sender=VendorProfile)
def clear_product_section_cache(**kwargs):
    """Keep homepage rows current when products or vendor benefits change."""
    local_delete("homepage:sections")
