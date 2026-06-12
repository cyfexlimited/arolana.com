from django.core.management.base import BaseCommand

from ads.models import AdBanner, AdCreative, Advertisement
from core.media_optimization import get_optimized_image_url
from core.models import HomePageAppearance, SiteSettings
from blog.models import BlogCategory, BlogPost
from homepage.models import HomepageVideoSection
from hero_banners.models import HeroBanner
from manufacturers.models import Manufacturer
from products.models import (
    Accessory,
    Category,
    Product,
    ProductImage,
    ProductListingBanner,
    ProductVariant,
    ProductVariantImage,
)
from vendors.models import VendorProfile


class Command(BaseCommand):
    help = 'Generate optimized WebP derivatives for common public media images.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument(
            '--only',
            choices=['accessories', 'storefront'],
            default=None,
            help='Generate only one media group.',
        )

    def handle(self, *args, **options):
        limit = options['limit']
        only = options['only']
        jobs = [
            (SiteSettings.objects.all(), [('site_logo', 'logo'), ('site_favicon', 'nav_icon'), ('footer_logo', 'logo')]),
            (HomePageAppearance.objects.filter(is_active=True), [('desktop_background_image', 'hero'), ('mobile_background_image', 'hero')]),
            (Category.objects.filter(is_active=True), [
                ('image', 'nav_icon'),
                ('image', 'category_card'),
                ('background_image', 'category_card'),
                ('background_image', 'hero'),
            ]),
            (ProductListingBanner.objects.filter(is_active=True), [('background_image', 'hero'), ('side_image', 'category_card')]),
            (Product.objects.filter(is_active=True, approval_status='approved'), [
                ('main_image', 'product_thumb'),
                ('main_image', 'product_card'),
                ('main_image', 'product_detail'),
                ('video_thumbnail', 'product_thumb'),
            ]),
            (ProductImage.objects.filter(is_active=True), [('image', 'product_thumb'), ('image', 'product_card'), ('image', 'product_detail')]),
            (ProductVariant.objects.filter(is_active=True), [('image', 'product_thumb'), ('image', 'product_card'), ('image', 'product_detail')]),
            (ProductVariantImage.objects.filter(is_active=True), [('image', 'product_thumb'), ('image', 'product_card'), ('image', 'product_detail')]),
            (Accessory.objects.filter(is_active=True), [('image', 'accessory_thumb')]),
            (BlogPost.objects.filter(is_published=True), [('featured_image', 'hero'), ('thumbnail_image', 'category_card')]),
            (BlogCategory.objects.filter(is_active=True), [('featured_image', 'category_card')]),
            (VendorProfile.objects.filter(is_active=True), [('store_logo', 'avatar'), ('store_banner', 'hero')]),
            (Manufacturer.objects.filter(is_active=True), [('logo', 'avatar'), ('banner', 'ad_card')]),
            (AdBanner.objects.filter(is_active=True), [('image', 'ad_card'), ('image_mobile', 'ad_card')]),
            (AdCreative.objects.filter(is_active=True), [('image', 'ad_card'), ('image_mobile', 'ad_card')]),
            (Advertisement.objects.filter(is_active=True), [('image', 'ad_card')]),
            (HomepageVideoSection.objects.filter(is_active=True), [('poster_image', 'hero')]),
            (HeroBanner.objects.filter(is_active=True), [('image_desktop', 'hero'), ('image_tablet', 'hero'), ('image_mobile', 'hero')]),
        ]
        if only == 'accessories':
            jobs = [
                (Accessory.objects.filter(is_active=True), [('image', 'accessory_thumb')]),
            ]
        elif only == 'storefront':
            jobs = jobs[2:9]

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
                    get_optimized_image_url(image, preset, force_generate=True)
                    generated += 1

        self.stdout.write(self.style.SUCCESS(f'Optimized media checked: {generated}; skipped empty fields: {skipped}'))
