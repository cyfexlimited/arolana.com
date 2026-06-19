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


def _xml_response(xml):
    response = HttpResponse(
        xml,
        content_type="application/xml; charset=utf-8",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "public, max-age=1800"
    return response


def robots_txt(request):
    site_url = getattr(settings, "SITE_URL", "https://arolana.com").rstrip("/")

    lines = [
        "User-agent: *",
        "Allow: /",
        "Allow: /products/",
        "Allow: /vendors/",
        "Allow: /blog/",
        "Allow: /ads/promo/",
        "Allow: /media/ads/",
        "Allow: /media/advertisements/",
        "Allow: /media/promo/",
        "Disallow: /admin/",
        "Disallow: /dashboard/",
        "Disallow: /accounts/",
        "Disallow: /cart/",
        "Disallow: /checkout/",
        "Disallow: /products/cart/",
        "Disallow: /products/checkout/",
        "Disallow: /ads/track-click/",
        "Disallow: /ads/track-impression/",
        "Disallow: /ads/api/",
        "",
        f"Sitemap: {site_url}/sitemap.xml",
        f"Sitemap: {site_url}/products/sitemap.xml",
    ]

    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")


def main_sitemap_xml(request):
    site_url = getattr(settings, "SITE_URL", "https://arolana.com").rstrip("/")
    today = timezone.now().date().isoformat()

    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        "  <url>",
        f"    <loc>{escape(site_url + '/')}</loc>",
        f"    <lastmod>{today}</lastmod>",
        "    <changefreq>daily</changefreq>",
        "    <priority>1.00</priority>",
        "  </url>",
        "  <url>",
        f"    <loc>{escape(site_url + '/about/')}</loc>",
        f"    <lastmod>{today}</lastmod>",
        "    <changefreq>monthly</changefreq>",
        "    <priority>0.60</priority>",
        "  </url>",
        "  <url>",
        f"    <loc>{escape(site_url + '/contact/')}</loc>",
        f"    <lastmod>{today}</lastmod>",
        "    <changefreq>monthly</changefreq>",
        "    <priority>0.60</priority>",
        "  </url>",
        "  <url>",
        f"    <loc>{escape(site_url + '/privacy/')}</loc>",
        f"    <lastmod>{today}</lastmod>",
        "    <changefreq>monthly</changefreq>",
        "    <priority>0.40</priority>",
        "  </url>",
        "  <url>",
        f"    <loc>{escape(site_url + '/terms/')}</loc>",
        f"    <lastmod>{today}</lastmod>",
        "    <changefreq>monthly</changefreq>",
        "    <priority>0.40</priority>",
        "  </url>",
        "</urlset>",
    ]

    return _xml_response("\n".join(rows))


def google_merchant_feed(request):
    currency_code = GOOGLE_MERCHANT_CURRENCY
    site_url = getattr(settings, "SITE_URL", "https://arolana.com").rstrip("/")

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


def product_sitemap_xml(request):
    site_url = getattr(settings, "SITE_URL", "https://arolana.com").rstrip("/")

    products = (
        Product.objects
        .filter(is_active=True, approval_status="approved")
        .order_by("-updated_at")[:50000]
    )

    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for product in products:
        try:
            loc = f"{site_url}{product.get_absolute_url()}"
        except Exception:
            continue

        lastmod = getattr(product, "updated_at", None) or timezone.now()

        rows.extend([
            "  <url>",
            f"    <loc>{escape(loc)}</loc>",
            f"    <lastmod>{lastmod.date().isoformat()}</lastmod>",
            "    <changefreq>daily</changefreq>",
            "    <priority>0.90</priority>",
            "  </url>",
        ])

    rows.append("</urlset>")

    return _xml_response("\n".join(rows))
