from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from django.utils.html import strip_tags

from accounts.models import User

from .models import EmailAudienceMember, NewsletterSubscriber, NewsletterTracking


def site_url():
    return getattr(settings, "SITE_URL", "https://arolana.com").rstrip("/")


def absolute_url(url):
    if not url:
        return ""

    url = str(url).strip()

    if url.startswith("http://") or url.startswith("https://"):
        return url

    if not url.startswith("/"):
        url = f"/{url}"

    return f"{site_url()}{url}"


def field_file_url(file_field):
    try:
        if file_field and file_field.url:
            return absolute_url(file_field.url)
    except Exception:
        return ""
    return ""


def get_unsubscribe_url(email):
    return f"{site_url()}/newsletter/unsubscribe/{quote(email)}/"


def get_tracking_open_url(tracking):
    if not tracking:
        return ""

    return f"{site_url()}/newsletter/track/open/{tracking.id}/"


def get_tracking_click_url(tracking, fallback_url="/"):
    if not tracking:
        return absolute_url(fallback_url or "/")

    return f"{site_url()}/newsletter/track/click/{tracking.id}/"


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
        },
    )

    if not created:
        sources = {member.source, source}

        if "registered" in sources and "newsletter" in sources:
            member.source = "both"
        elif source != "manual" and member.source == "manual":
            member.source = source

        member.name = member.name or name
        member.user = member.user or user
        member.subscriber = member.subscriber or subscriber

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


def campaign_audience_members(campaign):
    sync_email_audience()

    audience = EmailAudienceMember.objects.filter(
        is_active=True,
        accepts_promos=True,
    )

    if campaign.recipient_scope == "subscribers":
        audience = audience.filter(source__in=["newsletter", "both"])
    elif campaign.recipient_scope == "registered":
        audience = audience.filter(source__in=["registered", "both"])

    return audience.order_by("email").distinct("email") if hasattr(audience, "distinct") else audience


def campaign_recipient_emails(campaign):
    audience = campaign_audience_members(campaign)
    return sorted(set(audience.values_list("email", flat=True)))


def get_campaign_main_button_url(campaign):
    if campaign.button_url:
        return absolute_url(campaign.button_url)

    product = getattr(campaign, "related_product", None)
    if product:
        try:
            return absolute_url(product.get_absolute_url())
        except Exception:
            return site_url()

    return site_url()


def get_campaign_hero_image(campaign):
    uploaded_url = field_file_url(campaign.hero_image)
    if uploaded_url:
        return uploaded_url

    if campaign.hero_image_url:
        return campaign.hero_image_url

    return ""


def get_campaign_product_image(campaign):
    uploaded_url = field_file_url(campaign.product_image)
    if uploaded_url:
        return uploaded_url

    if campaign.product_image_url:
        return campaign.product_image_url

    product = getattr(campaign, "related_product", None)
    if product:
        for field_name in ["main_image", "image", "featured_image", "thumbnail"]:
            image = getattr(product, field_name, None)
            uploaded = field_file_url(image)
            if uploaded:
                return uploaded

    return ""


def get_campaign_product_title(campaign):
    if campaign.product_title:
        return campaign.product_title

    product = getattr(campaign, "related_product", None)
    if product:
        return getattr(product, "name", "") or str(product)

    return ""


def render_campaign_html(campaign, recipient_email="", tracking=None, is_test=False):
    base_url = site_url()
    hero_image = get_campaign_hero_image(campaign)
    product_image = get_campaign_product_image(campaign)
    product_title = get_campaign_product_title(campaign)
    main_button_url = get_campaign_main_button_url(campaign)
    unsubscribe_url = get_unsubscribe_url(recipient_email) if recipient_email else f"{base_url}/newsletter/"
    open_tracking_url = get_tracking_open_url(tracking)

    headline = campaign.headline or campaign.subject
    preheader = campaign.preheader or campaign.subheadline or ""
    eyebrow = campaign.eyebrow or campaign.get_campaign_type_display()
    button_text = campaign.button_text or "Shop now"

    product_price = campaign.product_price_text or ""
    product_description = campaign.product_description or ""

    extra_html = campaign.html_content or ""
    plain_content_as_html = (campaign.content or "").replace("\n", "<br>")

    if is_test:
        test_badge = """
        <div style="background:#fff7ed;color:#9a3412;border:1px solid #fed7aa;border-radius:10px;padding:10px 14px;margin-bottom:16px;font-size:13px;font-weight:700;">
            TEST EMAIL — not sent to subscribers yet.
        </div>
        """
    else:
        test_badge = ""

    hero_block = ""
    if hero_image:
        hero_block = f"""
        <tr>
            <td>
                <img src="{hero_image}" alt="{headline}" width="640" style="width:100%;max-width:640px;display:block;border-radius:22px 22px 0 0;object-fit:cover;">
            </td>
        </tr>
        """

    product_block = ""
    if product_image or product_title or product_description or product_price:
        image_html = ""
        if product_image:
            image_html = f"""
            <td width="180" style="padding:0 18px 0 0;vertical-align:top;">
                <img src="{product_image}" alt="{product_title or 'Arolana product'}" width="180" style="width:180px;max-width:180px;border-radius:16px;display:block;border:1px solid #e5e7eb;">
            </td>
            """

        price_html = ""
        if product_price:
            price_html = f"""
            <div style="font-size:18px;font-weight:800;color:#111827;margin:8px 0 0;">
                {product_price}
            </div>
            """

        product_block = f"""
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:22px 0;background:#f8fafc;border:1px solid #e5e7eb;border-radius:18px;padding:18px;">
            <tr>
                {image_html}
                <td style="vertical-align:top;">
                    <div style="font-size:18px;font-weight:800;color:#111827;margin-bottom:8px;">
                        {product_title}
                    </div>
                    <div style="font-size:14px;line-height:1.7;color:#4b5563;">
                        {product_description}
                    </div>
                    {price_html}
                </td>
            </tr>
        </table>
        """

    secondary_button = ""
    if campaign.secondary_button_text and campaign.secondary_button_url:
        secondary_button = f"""
        <a href="{absolute_url(campaign.secondary_button_url)}" style="display:inline-block;margin-left:10px;padding:14px 20px;border-radius:999px;border:1px solid #2563eb;color:#2563eb;text-decoration:none;font-weight:800;font-size:14px;">
            {campaign.secondary_button_text}
        </a>
        """

    tracking_pixel = ""
    if open_tracking_url:
        tracking_pixel = f'<img src="{open_tracking_url}" width="1" height="1" alt="" style="display:none;">'

    html = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width">
    <title>{campaign.subject}</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;color:#111827;">
    <div style="display:none;max-height:0;overflow:hidden;color:transparent;">
        {preheader}
    </div>

    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f4f6;padding:24px 12px;">
        <tr>
            <td align="center">
                <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:100%;max-width:640px;background:#ffffff;border-radius:24px;overflow:hidden;box-shadow:0 18px 45px rgba(15,23,42,0.10);">
                    {hero_block}

                    <tr>
                        <td style="padding:28px 28px 10px;">
                            {test_badge}

                            <div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#ff7a00;font-weight:900;margin-bottom:10px;">
                                {eyebrow}
                            </div>

                            <h1 style="font-size:30px;line-height:1.15;margin:0 0 12px;color:#0f172a;">
                                {headline}
                            </h1>

                            <div style="font-size:16px;line-height:1.7;color:#475569;margin-bottom:18px;">
                                {campaign.subheadline or ""}
                            </div>

                            <div style="font-size:15px;line-height:1.8;color:#374151;">
                                {plain_content_as_html}
                            </div>

                            {product_block}

                            <div style="font-size:15px;line-height:1.8;color:#374151;margin-top:18px;">
                                {extra_html}
                            </div>

                            <div style="margin:28px 0 18px;">
                                <a href="{main_button_url}" style="display:inline-block;background:#ff7a00;color:#ffffff;text-decoration:none;padding:15px 24px;border-radius:999px;font-weight:900;font-size:15px;">
                                    {button_text}
                                </a>
                                {secondary_button}
                            </div>
                        </td>
                    </tr>

                    <tr>
                        <td style="padding:20px 28px 28px;background:#0f172a;color:#cbd5e1;">
                            <div style="font-size:18px;font-weight:900;color:#ffffff;margin-bottom:8px;">
                                Arolana
                            </div>

                            <div style="font-size:13px;line-height:1.7;">
                                {campaign.footer_note or "You are receiving this email because you subscribed to Arolana updates."}
                            </div>

                            <div style="font-size:12px;line-height:1.7;margin-top:14px;color:#94a3b8;">
                                Arolana Marketplace · Products, vendors, and smart commerce updates.
                                <br>
                                <a href="{unsubscribe_url}" style="color:#fed7aa;text-decoration:underline;">Unsubscribe</a>
                            </div>
                        </td>
                    </tr>
                </table>

                <div style="font-size:11px;color:#94a3b8;margin-top:16px;">
                    © Arolana. All rights reserved.
                </div>
            </td>
        </tr>
    </table>

    {tracking_pixel}
</body>
</html>"""

    return html


def send_one_campaign_email(campaign, recipient_email, recipient_name="", subscriber=None, is_test=False):
    tracking = None

    if subscriber and not is_test:
        tracking, _ = NewsletterTracking.objects.get_or_create(
            campaign=campaign,
            subscriber=subscriber,
        )

    html_body = render_campaign_html(
        campaign,
        recipient_email=recipient_email,
        tracking=tracking,
        is_test=is_test,
    )

    plain_text = strip_tags(campaign.content or campaign.subject)

    email = EmailMultiAlternatives(
        subject=campaign.subject,
        body=plain_text,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "Arolana <noreply@arolana.com>"),
        to=[recipient_email],
    )
    email.attach_alternative(html_body, "text/html")
    email.send(fail_silently=False)


def send_test_campaign(campaign):
    if not campaign.test_email:
        return 0

    send_one_campaign_email(
        campaign=campaign,
        recipient_email=campaign.test_email,
        recipient_name="Test Recipient",
        subscriber=None,
        is_test=True,
    )
    return 1


def send_campaign(campaign):
    audience = campaign_audience_members(campaign)

    sent_count = 0
    failed_count = 0

    campaign.status = "sending"
    campaign.save(update_fields=["status", "updated_at"])

    seen_emails = set()

    for member in audience:
        recipient_email = (member.email or "").strip().lower()

        if not recipient_email or recipient_email in seen_emails:
            continue

        seen_emails.add(recipient_email)

        try:
            send_one_campaign_email(
                campaign=campaign,
                recipient_email=recipient_email,
                recipient_name=member.name,
                subscriber=member.subscriber,
                is_test=False,
            )
            sent_count += 1
        except Exception:
            failed_count += 1

    campaign.sent_count += sent_count
    campaign.failed_count += failed_count
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