from django.contrib.sitemaps import Sitemap
from products.models import Product, Category


class ArolanaProductSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.9
    protocol = "https"

    def items(self):
        return (
            Product.objects
            .filter(is_active=True, approval_status="approved")
            .select_related("category", "brand")
            .order_by("-updated_at")
        )

    def lastmod(self, obj):
        return getattr(obj, "updated_at", None)

    def location(self, obj):
        return obj.get_absolute_url()


class ArolanaCategorySitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.75
    protocol = "https"

    def items(self):
        return Category.objects.filter(is_active=True).order_by("order", "name")

    def lastmod(self, obj):
        return getattr(obj, "updated_at", None)

    def location(self, obj):
        return obj.get_absolute_url()
