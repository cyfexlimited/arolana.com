from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import escape

from products.models import Product
from arolana_seo.utils import merchant_metadata


GOOGLE_MERCHANT_COUNTRY = getattr(settings, "GOOGLE_MERCHANT_COUNTRY", "NG")
GOOGLE_MERCHANT_LANGUAGE = getattr(settings, "GOOGLE_MERCHANT_LANGUAGE", "en")
GOOGLE_MERCHANT_CURRENCY = getattr(settings, "GOOGLE_MERCHANT_CURRENCY", "NGN")
GOOGLE_MERCHANT_FEED_LABEL = getattr(settings, "GOOGLE_MERCHANT_FEED_LABEL", "NG")


def robots_txt(request):
    site_url = getattr(settings, "SITE_URL", "https://arolana.com").rstrip("/")

    lines = [
        "User-agent: *",
        "Allow: /",

        # Public pages Google can crawl
        "Allow: /products/",
        "Allow: /vendors/",
        "Allow: /blog/",
        "Allow: /ads/promo/",
        "Allow: /media/ads/",
        "Allow: /media/advertisements/",
        "Allow: /media/promo/",

        # Private/system pages Google should not index
        "Disallow: /admin/",
        "Disallow: /dashboard/",
        "Disallow: /accounts/",
        "Disallow: /cart/",
        "Disallow: /checkout/",
        "Disallow: /products/cart/",
        "Disallow: /products/checkout/",

        # Tracking endpoints should not be indexed
        "Disallow: /ads/track-click/",
        "Disallow: /ads/track-impression/",
        "Disallow: /ads/api/",

        "",
        f"Sitemap: {site_url}/sitemap.xml",
        f"Sitemap: {site_url}/products/sitemap.xml",
    ]

    return HttpResponse("\n".join(lines), content_type="text/plain")


def google_merchant_feed(request):
    """
    Google Merchant Center feed.

    For Arolana launch, keep Merchant feed Nigeria + NGN only.
    Do not use visitor IP currency here.
    """

    currency_code = GOOGLE_MERCHANT_CURRENCY
    site_url = getattr(settings, "SITE_URL", "https://arolana.com").rstrip("/")

    products = (
        Product.objects
        .filter(is_active=True, approval_status="approved")
        .select_related("category", "brand")
        .order_by("-updated_at")[:5000]
    )

    items = []

    for product in products:
        data = merchant_metadata(product, request, currency_code)

        raw_price = str(data.get("price", "")).strip()
        amount = raw_price.split()[0] if raw_price else "0.00"
        price = f"{amount} {currency_code}"

        items.append(f"""
        <item>
            <g:id>{escape(data.get("id", ""))}</g:id>
            <g:title>{escape(data.get("title", ""))}</g:title>
            <g:description>{escape(data.get("description", ""))}</g:description>
            <g:link>{escape(data.get("link", ""))}</g:link>
            <g:image_link>{escape(data.get("image_link", ""))}</g:image_link>
            <g:availability>{escape(data.get("availability", "in stock"))}</g:availability>
            <g:price>{escape(price)}</g:price>
            <g:brand>{escape(data.get("brand", "Arolana"))}</g:brand>
            <g:condition>{escape(data.get("condition", "new"))}</g:condition>
            <g:google_product_category>{escape(data.get("google_product_category", ""))}</g:google_product_category>
            <g:target_country>{escape(GOOGLE_MERCHANT_COUNTRY)}</g:target_country>
            <g:feed_label>{escape(GOOGLE_MERCHANT_FEED_LABEL)}</g:feed_label>
        </item>
        """)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">
    <channel>
        <title>Arolana Nigeria Product Feed</title>
        <link>{escape(site_url)}</link>
        <description>Arolana approved marketplace products for Nigeria in NGN</description>
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