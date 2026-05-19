from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import escape

from products.models import Product
from arolana_seo.utils import merchant_metadata


def robots_txt(request):
    site_url = getattr(settings, "SITE_URL", "https://arolana.com").rstrip("/")

    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /dashboard/",
        "Disallow: /accounts/",
        "",
        f"Sitemap: {site_url}/sitemap.xml",
        f"Sitemap: {site_url}/products/sitemap.xml",
    ]

    return HttpResponse("\n".join(lines), content_type="text/plain")


def google_merchant_feed(request):
    currency_code = getattr(settings, "AROLANA_BASE_CURRENCY", "NGN")

    products = (
        Product.objects
        .filter(is_active=True, approval_status="approved")
        .select_related("category", "brand")
        .order_by("-updated_at")[:5000]
    )

    items = []

    for product in products:
        data = merchant_metadata(product, request, currency_code)

        items.append(f"""
        <item>
            <g:id>{escape(data["id"])}</g:id>
            <g:title>{escape(data["title"])}</g:title>
            <g:description>{escape(data["description"])}</g:description>
            <g:link>{escape(data["link"])}</g:link>
            <g:image_link>{escape(data["image_link"])}</g:image_link>
            <g:availability>{escape(data["availability"])}</g:availability>
            <g:price>{escape(data["price"])}</g:price>
            <g:brand>{escape(data["brand"])}</g:brand>
            <g:condition>{escape(data["condition"])}</g:condition>
            <g:google_product_category>{escape(data["google_product_category"])}</g:google_product_category>
        </item>
        """)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">
    <channel>
        <title>Arolana Product Feed</title>
        <link>{escape(getattr(settings, "SITE_URL", "https://arolana.com"))}</link>
        <description>Arolana approved marketplace products</description>
        <lastBuildDate>{timezone.now().strftime("%a, %d %b %Y %H:%M:%S +0000")}</lastBuildDate>
        {''.join(items)}
    </channel>
</rss>
"""

    return HttpResponse(xml, content_type="application/xml")


def product_sitemap_xml(request):
    """
    Clean Google-friendly XML sitemap for approved products.

    URL:
    /products/sitemap.xml
    """

    site_url = getattr(settings, "SITE_URL", "https://arolana.com").rstrip("/")

    products = (
        Product.objects
        .filter(is_active=True, approval_status="approved")
        .order_by("-updated_at")[:50000]
    )

    urls = []

    for product in products:
        try:
            loc = f"{site_url}{product.get_absolute_url()}"
        except Exception:
            continue

        if getattr(product, "updated_at", None):
            lastmod = product.updated_at.date().isoformat()
        else:
            lastmod = timezone.now().date().isoformat()

        urls.append(f"""
    <url>
        <loc>{escape(loc)}</loc>
        <lastmod>{lastmod}</lastmod>
        <changefreq>daily</changefreq>
        <priority>0.90</priority>
    </url>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{''.join(urls)}
</urlset>
"""

    return HttpResponse(xml, content_type="application/xml")