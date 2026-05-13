from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from products.models import Product, Category
from vendors.models import VendorProfile

class StaticViewSitemap(Sitemap):
    priority = 0.5
    changefreq = 'daily'

    def items(self):
        return ['home', 'about', 'contact', 'privacy', 'terms', 'returns', 'faq_page']
    
    def location(self, item):
        return reverse(item)

class ProductSitemap(Sitemap):
    priority = 0.8
    changefreq = 'weekly'
    
    def items(self):
        return Product.objects.filter(is_active=True, approval_status='approved')
    
    def lastmod(self, obj):
        return obj.updated_at

class CategorySitemap(Sitemap):
    priority = 0.6
    changefreq = 'weekly'
    
    def items(self):
        return Category.objects.filter(is_active=True)

class VendorSitemap(Sitemap):
    priority = 0.7
    changefreq = 'weekly'
    
    def items(self):
        return VendorProfile.objects.filter(is_verified=True, is_active=True)

class BlogSitemap(Sitemap):
    priority = 0.7
    changefreq = 'weekly'
    
    def items(self):
        # Adjust based on your blog model
        from blog.models import BlogPost
        return BlogPost.objects.filter(is_published=True)
    
    def lastmod(self, obj):
        return obj.updated_at