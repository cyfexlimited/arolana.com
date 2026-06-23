from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from django.utils.html import escape

from accounts.models import User

from .models import EmailAudienceMember, NewsletterSubscriber


IMAGE_EXTENSIONS = (
    ".webp",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
)


def upsert_email_audience(
    email,
    name="",
    source="manual",
    user=None,
    subscriber=None,
    accepts_promos=None,
):
    if not email:
        return None

    email = str(email).strip().lower()

    member, created = EmailAudienceMember.objects.get_or_create(
        email=email,
        defaults={
            "name": name,
            "source": source,
            "user": user,
            "subscriber": subscriber,
            "accepts_promos": bool(accepts_promos),
            "last_synced_at": timezone.now(),
            "is_active": True,
        },
    )

    if not created:
        sources = {member.source, source}

        if "registered" in sources and "newsletter" in sources:
            member.source = "both"
        elif source != "manual" and member.source == "manual":
            member.source = source

        if name and not member.name:
            member.name = name

        if user and not member.user:
            member.user = user

        if subscriber and not member.subscriber:
            member.subscriber = subscriber

        if accepts_promos is not None:
            member.accepts_promos = bool(accepts_promos)

        member.is_active = True
        member.last_synced_at = timezone.now()
        member.save()

    return member


def sync_email_audience():
    synced = 0

    for user in User.objects.filter(is_active=True).exclude(email=""):
        try:
            profile = user.profile
        except Exception:
            profile = None

        accepts_promos = bool(
            getattr(profile, "newsletter_subscription", False)
            or getattr(profile, "promo_emails", False)
            or getattr(profile, "marketing_emails", False)
        )

        if upsert_email_audience(
            user.email,
            name=user.get_full_name() or user.username,
            source="registered",
            user=user,
            accepts_promos=accepts_promos,
        ):
            synced += 1

    for subscriber in NewsletterSubscriber.objects.filter(is_active=True):
        if upsert_email_audience(
            subscriber.email,
            name=subscriber.name,
            source="newsletter",
            subscriber=subscriber,
            accepts_promos=True,
        ):
            synced += 1

    return synced


def campaign_recipient_emails(campaign):
    sync_email_audience()

    audience = EmailAudienceMember.objects.filter(
        is_active=True,
        accepts_promos=True,
    )

    recipient_scope = getattr(campaign, "recipient_scope", "all")

    if recipient_scope == "subscribers":
        audience = audience.filter(source__in=["newsletter", "both"])
    elif recipient_scope == "registered":
        audience = audience.filter(source__in=["registered", "both"])

    return sorted(audience.values_list("email", flat=True).distinct())


def _clean(value, default=""):
    if value is None:
        return default

    value = str(value).strip()
    return value or default


def _html(value, default=""):
    return escape(_clean(value, default))


def _site_url():
    value = getattr(settings, "SITE_URL", "https://arolana.com")
    return str(value).strip().rstrip("/")


def _absolute_url(value):
    value = _clean(value)

    if not value:
        return ""

    if value.startswith("https://") or value.startswith("http://"):
        return value

    if value.startswith("//"):
        return "https:" + value

    if value.startswith("/"):
        return f"{_site_url()}{value}"

    return f'{_site_url()}/{value.lstrip("/")}'


def _looks_like_image_url(url):
    url = _clean(url)

    if not url:
        return False

    clean_url = url.split("?")[0].split("#")[0].lower()
    return clean_url.endswith(IMAGE_EXTENSIONS)


def _resolve_file_field_url(campaign, field_name):
    try:
        file_field = getattr(campaign, field_name, None)
    except Exception:
        return ""

    if not file_field:
        return ""

    try:
        file_url = getattr(file_field, "url", "")
        if file_url:
            return _absolute_url(file_url)
    except Exception:
        return ""

    return ""


def _resolve_image_url_field(campaign, field_name):
    try:
        value = getattr(campaign, field_name, "")
    except Exception:
        return ""

    url = _absolute_url(value)

    if not _looks_like_image_url(url):
        return ""

    return url


def _resolve_campaign_image_url(campaign, upload_fields=None, url_fields=None):
    """
    Priority:
    1. Uploaded admin image from PC.
    2. Manual direct image URL.

    Product/category/page URLs are ignored.
    """
    upload_fields = upload_fields or []
    url_fields = url_fields or []

    for field_name in upload_fields:
        url = _resolve_file_field_url(campaign, field_name)
        if url:
            return url

    for field_name in url_fields:
        url = _resolve_image_url_field(campaign, field_name)
        if url:
            return url

    return ""


def _render_button(url, text, filled=True):
    url = _absolute_url(url)
    text = _html(text)

    if not url or not text:
        return ""

    if filled:
        return f"""
        <a href="{url}" style="
            display:inline-block;
            background:#ff7a00;
            color:#ffffff;
            text-decoration:none;
            font-weight:900;
            font-size:17px;
            line-height:1;
            padding:17px 34px;
            border-radius:999px;
            border:1px solid #ff7a00;
            box-shadow:0 12px 28px rgba(255,122,0,0.28);
        ">{text}</a>
        """

    return f"""
    <a href="{url}" style="
        display:inline-block;
        background:#ffffff;
        color:#164cff;
        text-decoration:none;
        font-weight:900;
        font-size:17px;
        line-height:1;
        padding:16px 32px;
        border-radius:999px;
        border:2px solid #164cff;
    ">{text}</a>
    """


def _paragraphs_to_html(content, max_paragraphs=4):
    content = _clean(content)

    if not content:
        return """
        <p style="margin:0 0 20px 0;font-size:18px;line-height:1.85;color:#4f5f7a;">
            Discover premium products, trusted vendors, and smart marketplace opportunities on Arolana.
        </p>
        """

    parts = [p.strip() for p in content.split("\n") if p.strip()]
    html_parts = []

    for part in parts[:max_paragraphs]:
        html_parts.append(
            f"""
            <p style="margin:0 0 20px 0;font-size:18px;line-height:1.85;color:#4f5f7a;">
                {escape(part)}
            </p>
            """
        )

    return "".join(html_parts)


def _campaign_plain_text(campaign, is_test=False):
    subject = _clean(getattr(campaign, "subject", ""), "Arolana Update")
    headline = _clean(getattr(campaign, "headline", ""), subject)
    subheadline = _clean(getattr(campaign, "subheadline", ""))
    content = _clean(getattr(campaign, "content", ""))
    product_title = _clean(getattr(campaign, "product_title", ""))
    product_description = _clean(getattr(campaign, "product_description", ""))
    product_price_text = _clean(getattr(campaign, "product_price_text", ""))
    button_text = _clean(getattr(campaign, "button_text", "View Product"))
    button_url = _absolute_url(getattr(campaign, "button_url", "") or "/")
    secondary_button_text = _clean(getattr(campaign, "secondary_button_text", "Visit Arolana"))
    secondary_button_url = _absolute_url(getattr(campaign, "secondary_button_url", "") or "/")

    lines = []

    if is_test:
        lines.append("TEST EMAIL — not sent to subscribers yet.")
        lines.append("")

    lines.append(headline)

    if subheadline:
        lines.append(subheadline)
        lines.append("")

    if content:
        lines.append(content)
        lines.append("")

    if product_title:
        lines.append(f"Featured Product: {product_title}")

    if product_description:
        lines.append(product_description)

    if product_price_text:
        lines.append(f"Price: {product_price_text}")

    lines.append("")
    lines.append(f"{button_text}: {button_url}")

    if secondary_button_text and secondary_button_url:
        lines.append(f"{secondary_button_text}: {secondary_button_url}")

    return "\n".join(lines).strip()


def _common_campaign_values(campaign, recipient_email=None):
    site_url = _site_url()

    subject = _html(getattr(campaign, "subject", ""), "Arolana Update")
    preheader = _html(
        getattr(campaign, "preheader", ""),
        "Premium marketplace updates, featured products, and trusted vendor opportunities.",
    )

    eyebrow = _html(getattr(campaign, "eyebrow", ""), "NEW PRODUCT ON AROLANA")
    headline = _html(getattr(campaign, "headline", ""), subject)
    subheadline = _html(
        getattr(campaign, "subheadline", ""),
        "Premium technology for boardrooms, offices, schools, churches, and modern business spaces.",
    )

    hero_image_url = _resolve_campaign_image_url(
        campaign,
        upload_fields=["hero_image"],
        url_fields=["hero_image_url"],
    )

    product_image_url = _resolve_campaign_image_url(
        campaign,
        upload_fields=["product_image"],
        url_fields=["product_image_url"],
    )

    button_text = _clean(getattr(campaign, "button_text", ""), "View Product")
    button_url = _absolute_url(getattr(campaign, "button_url", "") or "/")

    secondary_button_text = _clean(getattr(campaign, "secondary_button_text", ""), "Visit Arolana")
    secondary_button_url = _absolute_url(getattr(campaign, "secondary_button_url", "") or "/")

    footer_note = _html(
        getattr(campaign, "footer_note", ""),
        (
            "You are receiving this email because you subscribed to Arolana updates, "
            "created an account, or interacted with Arolana Marketplace. Arolana will "
            "never ask for your password, OTP, or sensitive payment details by email."
        ),
    )

    unsubscribe_email = quote(recipient_email or "")
    unsubscribe_link = (
        f"{site_url}/newsletter/unsubscribe/{unsubscribe_email}/"
        if recipient_email
        else f"{site_url}/"
    )

    return {
        "site_url": site_url,
        "subject": subject,
        "preheader": preheader,
        "eyebrow": eyebrow,
        "headline": headline,
        "subheadline": subheadline,
        "hero_image_url": hero_image_url,
        "product_image_url": product_image_url,
        "button_text": button_text,
        "button_url": button_url,
        "secondary_button_text": secondary_button_text,
        "secondary_button_url": secondary_button_url,
        "footer_note": footer_note,
        "unsubscribe_link": unsubscribe_link,
    }


def _mobile_email_css():
    """
    Mobile CSS for Gmail/iOS Mail.
    Keeps desktop wide, but stacks columns on phones.
    """
    return """
    <style>
        @media only screen and (max-width: 640px) {
            .ar-container {
                width: 100% !important;
                max-width: 100% !important;
            }

            .ar-shell {
                width: 100% !important;
                max-width: 100% !important;
                border-radius: 0 !important;
            }

            .ar-header {
                padding: 22px 18px 20px 18px !important;
            }

            .ar-brand {
                font-size: 25px !important;
                line-height: 1.1 !important;
            }

            .ar-header-text {
                font-size: 13px !important;
                line-height: 1.55 !important;
            }

            .ar-body {
                padding: 20px 14px 26px 14px !important;
            }

            .ar-stack {
                display: block !important;
                width: 100% !important;
                max-width: 100% !important;
            }

            .ar-hero-img-cell {
                padding: 0 0 18px 0 !important;
            }

            .ar-product-img-cell {
                padding: 0 0 18px 0 !important;
            }

            .ar-img {
                width: 100% !important;
                max-width: 100% !important;
                height: auto !important;
                border-radius: 20px !important;
            }

            .ar-placeholder {
                min-height: 220px !important;
                border-radius: 20px !important;
            }

            .ar-test-wrap {
                padding: 0 0 18px 0 !important;
            }

            .ar-test {
                border-radius: 14px !important;
                padding: 12px 14px !important;
                font-size: 12px !important;
                line-height: 1.4 !important;
            }

            .ar-hero-table {
                margin-bottom: 26px !important;
            }

            .ar-eyebrow {
                font-size: 11px !important;
                letter-spacing: 1.8px !important;
                padding-bottom: 10px !important;
            }

            .ar-headline {
                font-size: 29px !important;
                line-height: 1.12 !important;
                letter-spacing: -0.5px !important;
                padding-bottom: 14px !important;
            }

            .ar-subheadline {
                font-size: 15px !important;
                line-height: 1.65 !important;
                padding-bottom: 20px !important;
            }

            .ar-content {
                font-size: 15px !important;
                line-height: 1.7 !important;
            }

            .ar-content p {
                font-size: 15px !important;
                line-height: 1.7 !important;
                margin-bottom: 16px !important;
            }

            .ar-product-card {
                border-radius: 22px !important;
            }

            .ar-product-pad {
                padding: 20px !important;
            }

            .ar-product-title {
                font-size: 25px !important;
                line-height: 1.18 !important;
            }

            .ar-product-desc {
                font-size: 15px !important;
                line-height: 1.7 !important;
            }

            .ar-price {
                font-size: 23px !important;
            }

            .ar-button-cell {
                display: block !important;
                width: 100% !important;
                padding: 0 0 12px 0 !important;
            }

            .ar-button-cell a {
                display: block !important;
                width: auto !important;
                text-align: center !important;
                font-size: 15px !important;
                padding: 15px 18px !important;
            }

            .ar-footer {
                padding: 16px 18px 15px 18px !important;
            }

            .ar-footer-title {
                font-size: 18px !important;
                margin-bottom: 8px !important;
            }

            .ar-footer-note {
                font-size: 12px !important;
                line-height: 1.55 !important;
            }

            .ar-footer-small {
                font-size: 11px !important;
                line-height: 1.45 !important;
            }

            .ar-copy {
                font-size: 11px !important;
                padding: 8px 10px 10px 10px !important;
            }

            .ar-hero-only-footer {
                padding: 16px 18px 15px 18px !important;
            }

            .ar-hero-only-note {
                font-size: 12px !important;
                line-height: 1.55 !important;
            }
        }
    </style>
    """


def _render_hero_only_html(campaign, recipient_email=None, is_test=False):
    values = _common_campaign_values(campaign, recipient_email=recipient_email)

    subject = values["subject"]
    preheader = values["preheader"]
    headline = values["headline"]
    hero_image_url = values["hero_image_url"] or values["product_image_url"]
    button_url = values["button_url"]
    footer_note = values["footer_note"]
    unsubscribe_link = values["unsubscribe_link"]

    test_banner = ""
    if is_test:
        test_banner = """
        <tr>
            <td style="padding:0;">
                <div style="
                    background:#fff7ed;
                    color:#9a3412;
                    border-bottom:1px solid #fdba74;
                    padding:14px 24px;
                    font-size:14px;
                    font-weight:900;
                    letter-spacing:0.2px;
                ">
                    TEST EMAIL — not sent to subscribers yet.
                </div>
            </td>
        </tr>
        """

    if hero_image_url:
        hero_block = f"""
        <a href="{button_url}" style="display:block;text-decoration:none;">
            <img src="{hero_image_url}" alt="{headline}" width="1500" style="
                display:block;
                width:100%;
                max-width:1500px;
                height:auto;
                border:0;
                outline:none;
                text-decoration:none;
            ">
        </a>
        """
    else:
        hero_block = f"""
        <div style="
            background:#f3f6fb;
            padding:80px 24px;
            text-align:center;
            color:#081738;
            font-size:30px;
            line-height:1.25;
            font-weight:900;
        ">
            {headline}
            <div style="
                color:#66758f;
                font-size:16px;
                line-height:1.7;
                font-weight:400;
                margin-top:18px;
            ">
                Upload a hero image or add a direct hero image URL to show the full banner.
            </div>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{subject}</title>
        {_mobile_email_css()}
    </head>

    <body style="margin:0;padding:0;background:#edf2f8;font-family:Arial,Helvetica,sans-serif;">
        <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
            {preheader}
        </div>

        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="
            background:#edf2f8;
            margin:0;
            padding:0;
        ">
            <tr>
                <td align="center">
                    <table class="ar-container" role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="
                        width:100%;
                        max-width:1500px;
                        margin:0 auto;
                        background:#ffffff;
                    ">
                        {test_banner}

                        <tr>
                            <td style="padding:0;">
                                {hero_block}
                            </td>
                        </tr>

                        <tr>
                            <td class="ar-hero-only-footer" style="
                                background:#061741;
                                padding:18px 30px 16px 30px;
                            ">
                                <div class="ar-hero-only-note" style="
                                    font-size:14px;
                                    line-height:1.65;
                                    color:#d4def5;
                                    margin:0 0 8px 0;
                                ">
                                    {footer_note}
                                </div>

                                <div class="ar-footer-small" style="
                                    font-size:13px;
                                    line-height:1.55;
                                    color:#9fb0d7;
                                    margin:0 0 8px 0;
                                ">
                                    Official Arolana Marketplace communication · Products, vendors, and smart commerce updates.
                                </div>

                                <div class="ar-footer-small" style="font-size:13px;line-height:1.5;">
                                    <a href="{unsubscribe_link}" style="color:#ffd19d;text-decoration:underline;">Unsubscribe</a>
                                </div>
                            </td>
                        </tr>
                    </table>

                    <div class="ar-copy" style="
                        text-align:center;
                        font-size:12px;
                        color:#8695b1;
                        padding:10px 10px 12px 10px;
                    ">
                        © Arolana. All rights reserved.
                    </div>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def _render_designed_html(campaign, recipient_email=None, is_test=False):
    values = _common_campaign_values(campaign, recipient_email=recipient_email)

    site_name = "Arolana"
    subject = values["subject"]
    preheader = values["preheader"]
    eyebrow = values["eyebrow"]
    headline = values["headline"]
    subheadline = values["subheadline"]
    hero_image_url = values["hero_image_url"]
    product_image_url = values["product_image_url"]
    button_text = values["button_text"]
    button_url = values["button_url"]
    secondary_button_text = values["secondary_button_text"]
    secondary_button_url = values["secondary_button_url"]
    footer_note = values["footer_note"]
    unsubscribe_link = values["unsubscribe_link"]

    content = _clean(getattr(campaign, "content", ""))
    extra_html_content = _clean(getattr(campaign, "html_content", ""))

    product_title = _html(
        getattr(campaign, "product_title", ""),
        _clean(headline) or "Featured Product",
    )

    product_price_text = _html(getattr(campaign, "product_price_text", ""))

    product_description = _html(
        getattr(campaign, "product_description", ""),
        "A premium professional solution for serious buyers looking for quality, performance, and reliability.",
    )

    content_html = _paragraphs_to_html(content)

    test_banner = ""
    if is_test:
        test_banner = """
        <tr>
            <td class="ar-test-wrap" style="padding:0 0 24px 0;">
                <div class="ar-test" style="
                    background:#fff7ed;
                    color:#9a3412;
                    border:1px solid #fdba74;
                    border-radius:16px;
                    padding:14px 20px;
                    font-size:14px;
                    font-weight:900;
                    letter-spacing:0.2px;
                ">
                    TEST EMAIL — not sent to subscribers yet.
                </div>
            </td>
        </tr>
        """

    if hero_image_url:
        hero_image_block = f"""
        <td class="ar-stack ar-hero-img-cell" width="56%" valign="middle" style="padding:0 34px 0 0;">
            <img class="ar-img" src="{hero_image_url}" alt="{headline}" width="820" style="
                display:block;
                width:100%;
                max-width:820px;
                height:auto;
                border:0;
                outline:none;
                text-decoration:none;
                border-radius:28px;
                background:#eef2f7;
            ">
        </td>
        """
    else:
        hero_image_block = """
        <td class="ar-stack ar-hero-img-cell" width="56%" valign="middle" style="padding:0 34px 0 0;">
            <div class="ar-placeholder" style="
                width:100%;
                min-height:420px;
                background:#eef2f7;
                border-radius:28px;
            "></div>
        </td>
        """

    product_image_block = ""
    product_text_width = "100%"

    if product_image_url:
        product_image_block = f"""
        <td class="ar-stack ar-product-img-cell" width="38%" valign="middle" style="padding:0 30px 0 0;">
            <img class="ar-img" src="{product_image_url}" alt="{product_title}" width="420" style="
                display:block;
                width:100%;
                max-width:420px;
                height:auto;
                border:0;
                outline:none;
                text-decoration:none;
                border-radius:24px;
                background:#ffffff;
            ">
        </td>
        """
        product_text_width = "62%"

    primary_button_html = _render_button(button_url, button_text, filled=True)
    secondary_button_html = _render_button(secondary_button_url, secondary_button_text, filled=False)

    price_html = ""
    if product_price_text:
        price_html = f"""
        <div class="ar-price" style="
            font-size:32px;
            line-height:1.2;
            font-weight:900;
            color:#081738;
            margin:0 0 24px 0;
        ">
            {product_price_text}
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{subject}</title>
        {_mobile_email_css()}
    </head>

    <body style="margin:0;padding:0;background:#edf2f8;font-family:Arial,Helvetica,sans-serif;">
        <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
            {preheader}
        </div>

        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="
            background:#edf2f8;
            margin:0;
            padding:12px 0;
        ">
            <tr>
                <td align="center">
                    <table class="ar-container" role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="
                        width:100%;
                        max-width:1580px;
                        margin:0 auto;
                    ">
                        <tr>
                            <td style="padding:0;">
                                <table class="ar-shell" role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="
                                    width:100%;
                                    background:#ffffff;
                                    border-radius:0;
                                    overflow:hidden;
                                ">

                                    <tr>
                                        <td class="ar-header" style="
                                            background:#061741;
                                            padding:38px 54px 34px 54px;
                                            border-bottom:6px solid #ff7a00;
                                        ">
                                            <div class="ar-brand" style="
                                                font-size:34px;
                                                font-weight:900;
                                                color:#ffffff;
                                                line-height:1.1;
                                                letter-spacing:-0.5px;
                                            ">
                                                {site_name}
                                            </div>

                                            <div class="ar-header-text" style="
                                                padding-top:12px;
                                                font-size:18px;
                                                line-height:1.75;
                                                color:#d7e2ff;
                                            ">
                                                Premium marketplace updates, featured products, trusted vendors, and smart buying opportunities.
                                            </div>
                                        </td>
                                    </tr>

                                    <tr>
                                        <td class="ar-body" style="padding:34px 54px 46px 54px;">
                                            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                                                {test_banner}
                                            </table>

                                            <table class="ar-hero-table" role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:0 0 42px 0;">
                                                <tr>
                                                    {hero_image_block}

                                                    <td class="ar-stack" width="44%" valign="middle">
                                                        <div class="ar-eyebrow" style="
                                                            padding:0 0 16px 0;
                                                            font-size:15px;
                                                            color:#ff7a00;
                                                            font-weight:900;
                                                            letter-spacing:2.5px;
                                                            text-transform:uppercase;
                                                        ">
                                                            {eyebrow}
                                                        </div>

                                                        <div class="ar-headline" style="
                                                            padding:0 0 20px 0;
                                                            font-size:46px;
                                                            line-height:1.06;
                                                            color:#081738;
                                                            font-weight:900;
                                                            letter-spacing:-1.3px;
                                                        ">
                                                            {headline}
                                                        </div>

                                                        <div class="ar-subheadline" style="
                                                            padding:0 0 30px 0;
                                                            font-size:20px;
                                                            line-height:1.75;
                                                            color:#5b6a86;
                                                        ">
                                                            {subheadline}
                                                        </div>

                                                        <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                                                            <tr>
                                                                <td class="ar-button-cell" style="padding:0 16px 14px 0;">
                                                                    {primary_button_html}
                                                                </td>
                                                                <td class="ar-button-cell" style="padding:0 0 14px 0;">
                                                                    {secondary_button_html}
                                                                </td>
                                                            </tr>
                                                        </table>
                                                    </td>
                                                </tr>
                                            </table>

                                            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:0 0 42px 0;">
                                                <tr>
                                                    <td class="ar-content" style="
                                                        font-size:18px;
                                                        line-height:1.85;
                                                        color:#4f5f7a;
                                                        max-width:1180px;
                                                    ">
                                                        {content_html}
                                                    </td>
                                                </tr>
                                            </table>

                                            <table class="ar-product-card" role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="
                                                width:100%;
                                                background:#f7f9fc;
                                                border:1px solid #e5edf7;
                                                border-radius:30px;
                                            ">
                                                <tr>
                                                    <td class="ar-product-pad" style="padding:36px;">
                                                        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                                                            <tr>
                                                                {product_image_block}

                                                                <td class="ar-stack" width="{product_text_width}" valign="middle">
                                                                    <div style="
                                                                        font-size:15px;
                                                                        font-weight:900;
                                                                        color:#ff7a00;
                                                                        letter-spacing:2px;
                                                                        margin:0 0 14px 0;
                                                                        text-transform:uppercase;
                                                                    ">
                                                                        Featured Product
                                                                    </div>

                                                                    <div class="ar-product-title" style="
                                                                        font-size:36px;
                                                                        line-height:1.18;
                                                                        font-weight:900;
                                                                        color:#0b1736;
                                                                        margin:0 0 18px 0;
                                                                        letter-spacing:-0.6px;
                                                                    ">
                                                                        {product_title}
                                                                    </div>

                                                                    <div class="ar-product-desc" style="
                                                                        font-size:19px;
                                                                        line-height:1.85;
                                                                        color:#5d6d89;
                                                                        margin:0 0 22px 0;
                                                                    ">
                                                                        {product_description}
                                                                    </div>

                                                                    {price_html}

                                                                    <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                                                                        <tr>
                                                                            <td class="ar-button-cell" style="padding:0 16px 14px 0;">
                                                                                {primary_button_html}
                                                                            </td>
                                                                            <td class="ar-button-cell" style="padding:0 0 14px 0;">
                                                                                {secondary_button_html}
                                                                            </td>
                                                                        </tr>
                                                                    </table>
                                                                </td>
                                                            </tr>
                                                        </table>
                                                    </td>
                                                </tr>
                                            </table>

                                            {extra_html_content if extra_html_content else ""}
                                        </td>
                                    </tr>

                                    <tr>
                                        <td class="ar-footer" style="
                                            background:#061741;
                                            padding:24px 42px 22px 42px;
                                        ">
                                            <div class="ar-footer-title" style="
                                                font-size:20px;
                                                line-height:1.25;
                                                font-weight:900;
                                                color:#ffffff;
                                                margin:0 0 10px 0;
                                            ">
                                                {site_name}
                                            </div>

                                            <div class="ar-footer-note" style="
                                                font-size:14px;
                                                line-height:1.65;
                                                color:#d4def5;
                                                margin:0 0 10px 0;
                                            ">
                                                {footer_note}
                                            </div>

                                            <div class="ar-footer-small" style="
                                                font-size:13px;
                                                line-height:1.55;
                                                color:#9fb0d7;
                                                margin:0 0 8px 0;
                                            ">
                                                Official Arolana Marketplace communication · Products, vendors, and smart commerce updates.
                                            </div>

                                            <div class="ar-footer-small" style="font-size:13px;line-height:1.5;">
                                                <a href="{unsubscribe_link}" style="color:#ffd19d;text-decoration:underline;">Unsubscribe</a>
                                            </div>
                                        </td>
                                    </tr>
                                </table>

                                <div class="ar-copy" style="
                                    text-align:center;
                                    font-size:12px;
                                    color:#8695b1;
                                    padding:10px 10px 12px 10px;
                                ">
                                    © Arolana. All rights reserved.
                                </div>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def _render_luxury_campaign_html(campaign, recipient_email=None, is_test=False):
    if bool(getattr(campaign, "hero_only", False)):
        return _render_hero_only_html(
            campaign,
            recipient_email=recipient_email,
            is_test=is_test,
        )

    return _render_designed_html(
        campaign,
        recipient_email=recipient_email,
        is_test=is_test,
    )


def _send_single_email(subject, plain_text, html_body, recipient):
    from_email = getattr(
        settings,
        "NEWSLETTER_FROM_EMAIL",
        getattr(settings, "DEFAULT_FROM_EMAIL", "Arolana <support@arolana.com>"),
    )

    email = EmailMultiAlternatives(
        subject=subject,
        body=plain_text,
        from_email=from_email,
        to=[recipient],
    )
    email.attach_alternative(html_body, "text/html")
    email.send(fail_silently=False)
    return 1


def render_campaign_html(campaign, recipient_email=None, tracking=None, is_test=False):
    return _render_luxury_campaign_html(
        campaign=campaign,
        recipient_email=recipient_email,
        is_test=is_test,
    )


def send_test_campaign(campaign):
    test_email = _clean(getattr(campaign, "test_email", ""))
    if not test_email:
        return 0

    subject = _clean(getattr(campaign, "subject", ""), "Arolana Test Campaign")
    plain_text = _campaign_plain_text(campaign, is_test=True)
    html_body = _render_luxury_campaign_html(
        campaign=campaign,
        recipient_email=test_email,
        is_test=True,
    )

    _send_single_email(subject, plain_text, html_body, test_email)
    return 1


def send_campaign(campaign):
    recipients = campaign_recipient_emails(campaign)

    if not recipients:
        return 0

    subject = _clean(getattr(campaign, "subject", ""), "Arolana Newsletter")
    sent_count = 0
    failed_count = 0

    campaign.status = "sending"
    campaign.save(update_fields=["status", "updated_at"])

    for recipient in recipients:
        try:
            plain_text = _campaign_plain_text(campaign, is_test=False)
            html_body = _render_luxury_campaign_html(
                campaign=campaign,
                recipient_email=recipient,
                is_test=False,
            )

            _send_single_email(subject, plain_text, html_body, recipient)
            sent_count += 1
        except Exception:
            failed_count += 1

    campaign.sent_count = (campaign.sent_count or 0) + sent_count
    campaign.failed_count = (campaign.failed_count or 0) + failed_count
    campaign.status = "sent"
    campaign.sent_at = timezone.now()
    campaign.last_sent_at = campaign.sent_at

    campaign.save(
        update_fields=[
            "sent_count",
            "failed_count",
            "status",
            "sent_at",
            "last_sent_at",
            "updated_at",
        ]
    )

    return sent_count