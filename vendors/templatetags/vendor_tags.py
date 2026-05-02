from django import template
from django.core.serializers.json import DjangoJSONEncoder
from vendors.models import VendorProfile
import json
import random

register = template.Library()

@register.inclusion_tag('vendors/carousel.html', takes_context=True)
def vendor_carousel(context):
    request = context.get('request')
    
    # Get vendors - simplify to avoid missing fields
    vendors = VendorProfile.objects.filter(
        is_verified=True, 
        is_active=True
    ).order_by('-rating_avg', '-total_sales')[:12]
    
    # Shuffle for random order each time
    vendors_list = list(vendors)
    random.shuffle(vendors_list)
    
    return {
        'vendors': vendors_list,
        'request': request,
    }
