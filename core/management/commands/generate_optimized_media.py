from django.core.management.base import BaseCommand

from ads.models import AdBanner, AdCreative, Advertisement
from core.media_optimization import get_optimized_image_url
from core.models import SiteSettings
from homepage.models import HomepageVideoSection
from hero_banners.models import HeroBanner
from manufacturers.models import Manufacturer
from products.models import Category, Product
from vendors.models import VendorProfile


class Command(BaseCommand):
    help = 'Generate optimized WebP derivatives for common public media images.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None)

    def handle(self, *args, **options):
        limit = options['limit']
        jobs = [
            (SiteSettings.objects.all(), [('site_logo', 'logo'), ('site_favicon', 'nav_icon'), ('footer_logo', 'logo')]),
            (Category.objects.filter(is_active=True), [('image', 'category_card'), ('background_image', 'hero')]),
            (Product.objects.filter(is_active=True, approval_status='approved'), [('main_image', 'product_card'), ('video_thumbnail', 'product_card')]),
            (VendorProfile.objects.filter(is_active=True), [('store_logo', 'avatar'), ('store_banner', 'hero')]),
            (Manufacturer.objects.filter(is_active=True), [('logo', 'avatar'), ('banner', 'ad_card')]),
            (AdBanner.objects.filter(is_active=True), [('image', 'ad_card'), ('image_mobile', 'ad_card')]),
            (AdCreative.objects.filter(is_active=True), [('image', 'ad_card'), ('image_mobile', 'ad_card')]),
            (Advertisement.objects.filter(is_active=True), [('image', 'ad_card')]),
            (HomepageVideoSection.objects.filter(is_active=True), [('poster_image', 'hero')]),
            (HeroBanner.objects.filter(is_active=True), [('image_desktop', 'hero'), ('image_tablet', 'hero'), ('image_mobile', 'hero')]),
        ]

        generated = 0
        skipped = 0

        for queryset, fields in jobs:
            if limit is not None:
                queryset = queryset[:limit]
            for obj in queryset:
                for field_name, preset in fields:
                    image = getattr(obj, field_name, None)
                    if not image:
                        skipped += 1
                        continue
                    get_optimized_image_url(image, preset)
                    generated += 1

        self.stdout.write(self.style.SUCCESS(f'Optimized media checked: {generated}; skipped empty fields: {skipped}'))
