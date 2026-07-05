from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import escape

from products.models import Product, Category
from vendors.models import VendorProfile
from pages.models import Page
from blog.models import BlogPost, BlogCategory
from landing_pages.models import LandingPage
from manufacturers.models import Manufacturer
from installers.models import ServicePortfolio

from arolana_seo.utils import merchant_metadata, product_image_alt, product_images


GOOGLE_MERCHANT_COUNTRY = getattr(settings, "GOOGLE_MERCHANT_COUNTRY", "NG")
GOOGLE_MERCHANT_LANGUAGE = getattr(settings, "GOOGLE_MERCHANT_LANGUAGE", "en")
GOOGLE_MERCHANT_CURRENCY = getattr(settings, "GOOGLE_MERCHANT_CURRENCY", "NGN")
GOOGLE_MERCHANT_FEED_LABEL = getattr(settings, "GOOGLE_MERCHANT_FEED_LABEL", "NG")


def _xml_response(xml):
    response = HttpResponse(xml, content_type="application/xml; charset=utf-8")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "public, max-age=1800"
    return response


def _site_url():
    return getattr(settings, "SITE_URL", "https://arolana.com").rstrip("/")


def _safe_absolute_url(site_url, obj):
    try:
        url = obj.get_absolute_url()
        if not url:
            return ""
        if str(url).startswith("http"):
            return str(url)
        return f"{site_url}{url}"
    except Exception:
        return ""


def _lastmod(obj):
    value = getattr(obj, "updated_at", None) or getattr(obj, "published_at", None) or getattr(obj, "created_at", None)
    return (value or timezone.now()).date().isoformat()


def _urlset_response(items, changefreq="weekly", priority="0.70"):
    site_url = _site_url()
    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for obj in items:
        loc = _safe_absolute_url(site_url, obj)
        if not loc:
            continue

        rows.extend([
            "  <url>",
            f"    <loc>{escape(loc)}</loc>",
            f"    <lastmod>{_lastmod(obj)}</lastmod>",
            f"    <changefreq>{changefreq}</changefreq>",
            f"    <priority>{priority}</priority>",
            "  </url>",
        ])

    rows.append("</urlset>")
    return _xml_response("\n".join(rows))


def robots_txt(request):
    site_url = _site_url()

    lines = [
        "User-agent: *",
        "Allow: /",
        "Allow: /products/",
        "Allow: /vendors/",
        "Allow: /blog/",
        "Allow: /landing/",
        "Allow: /manufacturers/",
        "Allow: /projects/",
        "Allow: /pages/",
        "Allow: /media/",
        "Disallow: /admin/",
        "Disallow: /dashboard/",
        "Disallow: /accounts/",
        "Disallow: /cart/",
        "Disallow: /checkout/",
        "Disallow: /orders/",
        "Disallow: /api/",
        "Disallow: /chat/",
        "Disallow: /notifications/",
        "Disallow: /payments/",
        "Disallow: /kyc/",
        "Disallow: /reports/",
        "Disallow: /ads/track-click/",
        "Disallow: /ads/track-impression/",
        "Disallow: /ads/api/",
        "",
        f"Sitemap: {site_url}/sitemap.xml",
    ]

    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")


def main_sitemap_xml(request):
    site_url = _site_url()
    today = timezone.now().date().isoformat()

    sitemap_paths = [
        "/static/sitemap.xml",
        "/products/sitemap.xml",
        "/products/images-sitemap.xml",
        "/categories/sitemap.xml",
        "/vendors/sitemap.xml",
        "/blog/sitemap.xml",
        "/blog-categories/sitemap.xml",
        "/landing/sitemap.xml",
        "/manufacturers/sitemap.xml",
        "/pages/sitemap.xml",
        "/projects/sitemap.xml",
    ]

    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for path in sitemap_paths:
        rows.extend([
            "  <sitemap>",
            f"    <loc>{escape(site_url + path)}</loc>",
            f"    <lastmod>{today}</lastmod>",
            "  </sitemap>",
        ])

    rows.append("</sitemapindex>")
    return _xml_response("\n".join(rows))


def static_sitemap_xml(request):
    site_url = _site_url()
    today = timezone.now().date().isoformat()

    static_urls = [
        ("/", "daily", "1.00"),
        ("/about/", "monthly", "0.60"),
        ("/contact/", "monthly", "0.60"),
        ("/support/", "monthly", "0.60"),
        ("/shipping/", "monthly", "0.50"),
        ("/faq/", "monthly", "0.50"),
        ("/privacy/", "monthly", "0.40"),
        ("/terms/", "monthly", "0.40"),
        ("/returns/", "monthly", "0.40"),
    ]

    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for path, changefreq, priority in static_urls:
        rows.extend([
            "  <url>",
            f"    <loc>{escape(site_url + path)}</loc>",
            f"    <lastmod>{today}</lastmod>",
            f"    <changefreq>{changefreq}</changefreq>",
            f"    <priority>{priority}</priority>",
            "  </url>",
        ])

    rows.append("</urlset>")
    return _xml_response("\n".join(rows))


def product_sitemap_xml(request):
    products = (
        Product.objects
        .filter(is_active=True, approval_status="approved")
        .select_related("category", "brand", "vendor")
        .order_by("-updated_at")[:50000]
    )
    return _urlset_response(products, "daily", "0.90")


def product_image_sitemap_xml(request):
    site_url = _site_url()
    products = (
        Product.objects
        .filter(is_active=True, approval_status="approved")
        .select_related("category", "brand", "vendor")
        .prefetch_related("images", "variants")
        .order_by("-updated_at")[:50000]
    )

    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
    ]

    for product in products:
        loc = _safe_absolute_url(site_url, product)
        if not loc:
            continue

        images = product_images(product)
        if not images:
            continue

        rows.extend([
            "  <url>",
            f"    <loc>{escape(loc)}</loc>",
            f"    <lastmod>{_lastmod(product)}</lastmod>",
        ])

        seen = set()
        for image_url in images[:12]:
            if not image_url or image_url in seen:
                continue
            seen.add(image_url)
            rows.extend([
                "    <image:image>",
                f"      <image:loc>{escape(image_url)}</image:loc>",
                f"      <image:title>{escape(str(product.name or 'Arolana product'))}</image:title>",
                f"      <image:caption>{escape(product_image_alt(product))}</image:caption>",
                "    </image:image>",
            ])

        rows.append("  </url>")

    rows.append("</urlset>")
    return _xml_response("\n".join(rows))


def category_sitemap_xml(request):
    categories = Category.objects.filter(is_active=True).order_by("order", "name")[:50000]
    return _urlset_response(categories, "weekly", "0.80")


def vendor_sitemap_xml(request):
    vendors = (
        VendorProfile.objects
        .filter(is_active=True, is_verified=True)
        .order_by("-updated_at")[:50000]
    )
    return _urlset_response(vendors, "weekly", "0.75")


def project_sitemap_xml(request):
    projects = ServicePortfolio.objects.public().order_by("-published_at", "-updated_at")[:50000]
    return _urlset_response(projects, "weekly", "0.80")


def blog_sitemap_xml(request):
    posts = (
        BlogPost.objects
        .filter(is_active=True, is_published=True)
        .order_by("-published_at", "-updated_at")[:50000]
    )
    return _urlset_response(posts, "weekly", "0.75")


def blog_category_sitemap_xml(request):
    categories = BlogCategory.objects.filter(is_active=True).order_by("name")[:50000]
    return _urlset_response(categories, "weekly", "0.60")


def landing_sitemap_xml(request):
    pages = (
        LandingPage.objects
        .filter(is_active=True, status="published")
        .order_by("-published_at", "-updated_at")[:50000]
    )
    return _urlset_response(pages, "weekly", "0.80")


def manufacturer_sitemap_xml(request):
    manufacturers = (
        Manufacturer.objects
        .filter(is_active=True)
        .order_by("-is_featured", "display_order", "name")[:50000]
    )
    return _urlset_response(manufacturers, "weekly", "0.70")


def page_sitemap_xml(request):
    pages = Page.objects.filter(is_active=True).order_by("footer_order", "title")[:50000]
    return _urlset_response(pages, "monthly", "0.55")


def google_merchant_feed(request):
    currency_code = GOOGLE_MERCHANT_CURRENCY
    site_url = _site_url()

    products = (
        Product.objects
        .filter(is_active=True, approval_status="approved")
        .select_related("category", "brand")
        .order_by("-updated_at")[:5000]
    )

    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">',
        "  <channel>",
        "    <title>Arolana Nigeria Product Feed</title>",
        f"    <link>{escape(site_url)}</link>",
        "    <description>Arolana approved marketplace products for Nigeria in NGN</description>",
        f"    <lastBuildDate>{timezone.now().strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>",
    ]

    for product in products:
        data = merchant_metadata(product, request, currency_code)

        raw_price = str(data.get("price", "")).strip()
        amount = raw_price.split()[0] if raw_price else "0.00"
        price = f"{amount} {currency_code}"

        rows.extend([
            "    <item>",
            f"      <g:id>{escape(data.get('id', ''))}</g:id>",
            f"      <g:title>{escape(data.get('title', ''))}</g:title>",
            f"      <g:description>{escape(data.get('description', ''))}</g:description>",
            f"      <g:link>{escape(data.get('link', ''))}</g:link>",
            f"      <g:image_link>{escape(data.get('image_link', ''))}</g:image_link>",
            f"      <g:availability>{escape(data.get('availability', 'in stock'))}</g:availability>",
            f"      <g:price>{escape(price)}</g:price>",
            f"      <g:brand>{escape(data.get('brand', 'Arolana'))}</g:brand>",
            f"      <g:condition>{escape(data.get('condition', 'new'))}</g:condition>",
            f"      <g:google_product_category>{escape(data.get('google_product_category', ''))}</g:google_product_category>",
            f"      <g:target_country>{escape(GOOGLE_MERCHANT_COUNTRY)}</g:target_country>",
            f"      <g:feed_label>{escape(GOOGLE_MERCHANT_FEED_LABEL)}</g:feed_label>",
            "    </item>",
        ])

    rows.extend([
        "  </channel>",
        "</rss>",
    ])

    return _xml_response("\n".join(rows))
