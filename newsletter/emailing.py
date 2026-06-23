from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from django.utils.html import strip_tags

from accounts.models import User

from .models import EmailAudienceMember, NewsletterSubscriber


def get_site_url():
    return getattr(settings, "SITE_URL", "https://arolana.com").rstrip("/")


def absolute_url(url):
    if not url:
        return ""

    url = str(url).strip()

    if url.startswith("https://") or url.startswith("http://"):
        return url

    if not url.startswith("/"):
        url = f"/{url}"

    return f"{get_site_url()}{url}"


def file_field_url(file_field):
    """
    Email images must be public HTTPS URLs.
    This converts uploaded admin images to full https://arolana.com/media/... URLs.
    """
    try:
        if file_field and file_field.url:
            return absolute_url(file_field.url)
    except Exception:
        return ""
    return ""


def campaign_image_url(campaign, upload_field_name, url_field_name):
    """
    Priority:
    1. Uploaded image in admin
    2. Manual image URL field
    """
    uploaded = file_field_url(getattr(campaign, upload_field_name, None))
    if uploaded:
        return uploaded

    manual = str(getattr(campaign, url_field_name, "") or "").strip()
    if manual:
        return absolute_url(manual)

    return ""


def upsert_email_audience(email, name="", source="manual", user=None, subscriber=None, accepts_promos=None):
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


def _is_public_image(url):
    url = _clean(url)
    return url.startswith("https://") or url.startswith("http://")


def _paragraphs(text):
    text = _clean(text)
    if not text:
        return ""

    parts = [p.strip() for p in text.split("\n") if p.strip()]
    html = ""

    for paragraph in parts[:4]:
        html += f"""
        <p style="margin:0 0 18px 0;font-size:16px;line-height:1.75;color:#516179;">
            {paragraph}
        </p>
        """

    return html


def _button(url, text, filled=True):
    url = absolute_url(url)
    text = _clean(text)

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
            font-size:15px;
            padding:15px 28px;
            border-radius:999px;
            border:1px solid #ff7a00;
        ">
            {text}
        </a>
        """

    return f"""
    <a href="{url}" style="
        display:inline-block;
        background:#ffffff;
        color:#0f3fff;
        text-decoration:none;
        font-weight:900;
        font-size:15px;
        padding:14px 24px;
        border-radius:999px;
        border:2px solid #0f3fff;
    ">
        {text}
    </a>
    """


def _render_luxury_campaign_html(campaign, recipient_email=None, is_test=False):
    site_url = get_site_url()

    subject = _clean(getattr(campaign, "subject", ""), "Arolana Update")
    preheader = _clean(
        getattr(campaign, "preheader", ""),
        "Premium products, trusted vendors, and smarter shopping on Arolana.",
    )

    eyebrow = _clean(getattr(campaign, "eyebrow", ""), "PREMIUM PRODUCT DROP")
    headline = _clean(getattr(campaign, "headline", ""), subject)
    subheadline = _clean(
        getattr(campaign, "subheadline", ""),
        "Curated technology and marketplace updates for serious buyers.",
    )

    content = _clean(getattr(campaign, "content", ""))
    html_content = _clean(getattr(campaign, "html_content", ""))

    hero_image_url = campaign_image_url(campaign, "hero_image", "hero_image_url")
    product_image_url = campaign_image_url(campaign, "product_image", "product_image_url")

    product_title = _clean(getattr(campaign, "product_title", ""), "Featured Product")
    product_price_text = _clean(getattr(campaign, "product_price_text", ""))
    product_description = _clean(
        getattr(campaign, "product_description", ""),
        "A premium product selected for modern teams, institutions, and business spaces.",
    )

    button_text = _clean(getattr(campaign, "button_text", ""), "View Product")
    button_url = _clean(getattr(campaign, "button_url", ""), site_url)

    secondary_button_text = _clean(getattr(campaign, "secondary_button_text", ""), "Visit Arolana")
    secondary_button_url = _clean(getattr(campaign, "secondary_button_url", ""), site_url)

    footer_note = _clean(
        getattr(campaign, "footer_note", ""),
        "You are receiving this email because you subscribed to Arolana updates.",
    )

    unsubscribe_email = quote(recipient_email or "")
    unsubscribe_link = f"{site_url}/newsletter/unsubscribe/{unsubscribe_email}/" if recipient_email else site_url

    hero_block = ""
    if _is_public_image(hero_image_url):
        hero_block = f"""
        <tr>
            <td>
                <img src="{hero_image_url}" alt="{headline}" width="680" style="
                    width:100%;
                    max-width:680px;
                    display:block;
                    border:0;
                    border-radius:26px;
                ">
            </td>
        </tr>
        """

    product_image_block = ""
    if _is_public_image(product_image_url):
        product_image_block = f"""
        <tr>
            <td align="center" style="padding:0 0 22px 0;">
                <img src="{product_image_url}" alt="{product_title}" width="420" style="
                    width:100%;
                    max-width:420px;
                    display:block;
                    border:0;
                    border-radius:22px;
                    background:#ffffff;
                ">
            </td>
        </tr>
        """

    price_block = ""
    if product_price_text:
        price_block = f"""
        <div style="font-size:24px;line-height:1.2;font-weight:900;color:#0a1433;margin-top:14px;">
            {product_price_text}
        </div>
        """

    test_banner = ""
    if is_test:
        test_banner = """
        <tr>
            <td style="padding:0 0 18px 0;">
                <div style="
                    background:#fff7ed;
                    color:#9a3412;
                    border:1px solid #fdba74;
                    border-radius:16px;
                    padding:14px 18px;
                    font-size:14px;
                    font-weight:900;
                    letter-spacing:0.2px;
                ">
                    TEST EMAIL — not sent to subscribers yet.
                </div>
            </td>
        </tr>
        """

    content_html = _paragraphs(content)

    if not content_html:
        content_html = """
        <p style="margin:0 0 18px 0;font-size:16px;line-height:1.75;color:#516179;">
            Discover a more refined way to shop premium products from trusted vendors on Arolana.
        </p>
        """

    html = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width">
    <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#eef2f8;font-family:Arial,Helvetica,sans-serif;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
        {preheader}
    </div>

    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f8;padding:24px 10px;">
        <tr>
            <td align="center">

                <table role="presentation" width="680" cellpadding="0" cellspacing="0" style="
                    width:100%;
                    max-width:680px;
                    background:#ffffff;
                    border-radius:30px;
                    overflow:hidden;
                    box-shadow:0 18px 50px rgba(8,18,45,0.10);
                ">

                    <tr>
                        <td style="
                            background:#08142f;
                            padding:30px 28px;
                            border-bottom:4px solid #ff7a00;
                        ">
                            <div style="font-size:30px;font-weight:900;color:#ffffff;letter-spacing:-0.5px;">
                                Arolana
                            </div>
                            <div style="font-size:14px;line-height:1.7;color:#cbd7f5;margin-top:8px;">
                                Premium marketplace updates, featured products, trusted vendors, and smart buying opportunities.
                            </div>
                        </td>
                    </tr>

                    <tr>
                        <td style="padding:28px;">
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                                {test_banner}
                                {hero_block}

                                <tr>
                                    <td style="padding:{'26px 0 0 0' if hero_block else '0'};">
                                        <div style="
                                            color:#ff7a00;
                                            font-size:13px;
                                            font-weight:900;
                                            letter-spacing:2px;
                                            text-transform:uppercase;
                                            margin-bottom:12px;
                                        ">
                                            {eyebrow}
                                        </div>

                                        <h1 style="
                                            margin:0 0 14px 0;
                                            color:#07122d;
                                            font-size:38px;
                                            line-height:1.12;
                                            font-weight:900;
                                            letter-spacing:-1px;
                                        ">
                                            {headline}
                                        </h1>

                                        <div style="
                                            color:#60708a;
                                            font-size:17px;
                                            line-height:1.65;
                                            margin-bottom:24px;
                                        ">
                                            {subheadline}
                                        </div>

                                        {content_html}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding:10px 0 26px 0;">
                                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="
                                            background:#f7f9fd;
                                            border:1px solid #e3eaf5;
                                            border-radius:26px;
                                        ">
                                            <tr>
                                                <td style="padding:26px;">
                                                    {product_image_block}

                                                    <div style="font-size:24px;line-height:1.25;font-weight:900;color:#07122d;margin-bottom:12px;">
                                                        {product_title}
                                                    </div>

                                                    <div style="font-size:16px;line-height:1.75;color:#60708a;">
                                                        {product_description}
                                                    </div>

                                                    {price_block}
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding:0 0 24px 0;">
                                        <table role="presentation" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td style="padding:0 12px 12px 0;">
                                                    {_button(button_url, button_text, filled=True)}
                                                </td>
                                                <td style="padding:0 0 12px 0;">
                                                    {_button(secondary_button_url, secondary_button_text, filled=False)}
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>

                                {html_content if html_content else ""}
                            </table>
                        </td>
                    </tr>

                    <tr>
                        <td style="background:#07122d;padding:30px 28px;">
                            <div style="font-size:22px;font-weight:900;color:#ffffff;margin-bottom:12px;">
                                Arolana
                            </div>

                            <div style="font-size:15px;line-height:1.75;color:#d6def3;margin-bottom:14px;">
                                {footer_note}
                            </div>

                            <div style="font-size:14px;line-height:1.7;color:#9fb0d7;margin-bottom:12px;">
                                Arolana Marketplace · Products, vendors, and smart commerce updates.
                            </div>

                            <a href="{unsubscribe_link}" style="font-size:14px;color:#ffd19d;text-decoration:underline;">
                                Unsubscribe
                            </a>
                        </td>
                    </tr>
                </table>

                <div style="font-size:12px;color:#8b98b3;text-align:center;padding:18px 8px 0;">
                    © Arolana. All rights reserved.
                </div>
            </td>
        </tr>
    </table>
</body>
</html>"""

    return html


def render_campaign_html(campaign, recipient_email=None, tracking=None, is_test=False):
    return _render_luxury_campaign_html(
        campaign=campaign,
        recipient_email=recipient_email,
        is_test=is_test,
    )


def _campaign_plain_text(campaign, is_test=False):
    subject = _clean(getattr(campaign, "subject", ""), "Arolana Update")
    headline = _clean(getattr(campaign, "headline", ""), subject)
    subheadline = _clean(getattr(campaign, "subheadline", ""))
    content = _clean(getattr(campaign, "content", ""))
    product_title = _clean(getattr(campaign, "product_title", ""))
    product_description = _clean(getattr(campaign, "product_description", ""))
    product_price_text = _clean(getattr(campaign, "product_price_text", ""))
    button_text = _clean(getattr(campaign, "button_text", "View Product"))
    button_url = absolute_url(_clean(getattr(campaign, "button_url", ""), get_site_url()))

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

    return "\n".join(lines).strip()


def _send_single_email(subject, plain_text, html_body, recipient):
    from_email = getattr(
        settings,
        "DEFAULT_FROM_EMAIL",
        "Arolana <support@arolana.com>",
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

    if hasattr(campaign, "failed_count"):
        campaign.failed_count = (campaign.failed_count or 0) + failed_count

    campaign.status = "sent"
    campaign.sent_at = timezone.now()
    campaign.last_sent_at = campaign.sent_at

    update_fields = ["sent_count", "status", "sent_at", "last_sent_at", "updated_at"]
    if hasattr(campaign, "failed_count"):
        update_fields.append("failed_count")

    campaign.save(update_fields=update_fields)

    return sent_count