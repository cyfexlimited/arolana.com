from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from django.utils.html import strip_tags

from accounts.models import User

from .models import EmailAudienceMember, NewsletterSubscriber


def upsert_email_audience(email, name='', source='manual', user=None, subscriber=None, accepts_promos=None):
    if not email:
        return None

    email = str(email).strip().lower()

    member, created = EmailAudienceMember.objects.get_or_create(
        email=email,
        defaults={
            'name': name,
            'source': source,
            'user': user,
            'subscriber': subscriber,
            'accepts_promos': bool(accepts_promos),
            'last_synced_at': timezone.now(),
            'is_active': True,
        },
    )

    if not created:
        sources = {member.source, source}
        if 'registered' in sources and 'newsletter' in sources:
            member.source = 'both'
        elif source != 'manual' and member.source == 'manual':
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

    for user in User.objects.filter(is_active=True).exclude(email=''):
        try:
            profile = user.profile
        except Exception:
            profile = None

        accepts_promos = bool(
            getattr(profile, 'newsletter_subscription', False)
            or getattr(profile, 'promo_emails', False)
            or getattr(profile, 'marketing_emails', False)
        )

        if upsert_email_audience(
            user.email,
            name=user.get_full_name() or user.username,
            source='registered',
            user=user,
            accepts_promos=accepts_promos,
        ):
            synced += 1

    for subscriber in NewsletterSubscriber.objects.filter(is_active=True):
        if upsert_email_audience(
            subscriber.email,
            name=subscriber.name,
            source='newsletter',
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

    recipient_scope = getattr(campaign, 'recipient_scope', 'all')

    if recipient_scope == 'subscribers':
        audience = audience.filter(source__in=['newsletter', 'both'])
    elif recipient_scope == 'registered':
        audience = audience.filter(source__in=['registered', 'both'])

    return sorted(audience.values_list('email', flat=True).distinct())


def _clean(value, default=''):
    if value is None:
        return default
    return str(value).strip()


def _is_public_image(url):
    url = _clean(url)
    if not url:
        return False
    return url.startswith('https://') or url.startswith('http://')


def _render_button(url, text, filled=True):
    url = _clean(url)
    text = _clean(text)

    if not url or not text:
        return ''

    if filled:
        return f'''
        <a href="{url}" style="
            display:inline-block;
            background:#ff7a00;
            color:#ffffff;
            text-decoration:none;
            font-weight:700;
            font-size:16px;
            line-height:1;
            padding:16px 28px;
            border-radius:999px;
            border:1px solid #ff7a00;
            box-shadow:0 8px 24px rgba(255,122,0,0.25);
        ">{text}</a>
        '''

    return f'''
    <a href="{url}" style="
        display:inline-block;
        background:#ffffff;
        color:#2457ff;
        text-decoration:none;
        font-weight:700;
        font-size:16px;
        line-height:1;
        padding:16px 28px;
        border-radius:999px;
        border:2px solid #2457ff;
    ">{text}</a>
    '''


def _render_luxury_campaign_html(campaign, recipient_email=None, is_test=False):
    site_name = "Arolana"
    site_url = getattr(settings, 'SITE_URL', 'https://arolana.com').rstrip('/')

    subject = _clean(getattr(campaign, 'subject', ''), 'Arolana Update')
    preheader = _clean(
        getattr(campaign, 'preheader', ''),
        'Premium products, trusted vendors, and smarter shopping on Arolana.'
    )

    eyebrow = _clean(
        getattr(campaign, 'eyebrow', ''),
        'PREMIUM MARKETPLACE UPDATE'
    )

    headline = _clean(
        getattr(campaign, 'headline', ''),
        subject
    )

    subheadline = _clean(
        getattr(campaign, 'subheadline', ''),
        'Discover premium products, trusted vendors, and a better buying experience on Arolana.'
    )

    content = _clean(getattr(campaign, 'content', ''))
    extra_html_content = _clean(getattr(campaign, 'html_content', ''))

    hero_image_url = _clean(getattr(campaign, 'hero_image_url', ''))
    product_image_url = _clean(getattr(campaign, 'product_image_url', ''))

    product_title = _clean(getattr(campaign, 'product_title', ''), 'Featured Product')
    product_price_text = _clean(getattr(campaign, 'product_price_text', ''))
    product_description = _clean(
        getattr(campaign, 'product_description', ''),
        'A premium product selected to help you work smarter, sell better, and shop with confidence on Arolana.'
    )

    button_text = _clean(getattr(campaign, 'button_text', ''), 'View Product')
    button_url = _clean(getattr(campaign, 'button_url', ''), f'{site_url}/')

    secondary_button_text = _clean(getattr(campaign, 'secondary_button_text', ''), 'Visit Arolana')
    secondary_button_url = _clean(getattr(campaign, 'secondary_button_url', ''), f'{site_url}/')

    footer_note = _clean(
        getattr(campaign, 'footer_note', ''),
        'You are receiving this email because you subscribed to Arolana updates.'
    )

    unsubscribe_link = f"{site_url}/newsletter/unsubscribe/{recipient_email}/" if recipient_email else f"{site_url}/"

    hero_block = ''
    if _is_public_image(hero_image_url):
        hero_block = f'''
        <tr>
            <td style="padding:0 0 24px 0;">
                <img src="{hero_image_url}" alt="{headline}" style="
                    width:100%;
                    max-width:100%;
                    display:block;
                    border:0;
                    outline:none;
                    text-decoration:none;
                    border-radius:26px;
                ">
            </td>
        </tr>
        '''

    product_image_block = ''
    if _is_public_image(product_image_url):
        product_image_block = f'''
        <td valign="top" style="width:44%; padding:0 18px 0 0;">
            <img src="{product_image_url}" alt="{product_title}" style="
                width:100%;
                max-width:100%;
                display:block;
                border:0;
                border-radius:22px;
                background:#f7f8fb;
            ">
        </td>
        '''

    if content:
        paragraphs = []
        for paragraph in [p.strip() for p in content.split('\n') if p.strip()]:
            paragraphs.append(
                f'<p style="margin:0 0 22px 0; font-size:18px; line-height:1.8; color:#4b5b75;">{paragraph}</p>'
            )
        content_html = ''.join(paragraphs)
    else:
        content_html = '''
        <p style="margin:0 0 22px 0; font-size:18px; line-height:1.8; color:#4b5b75;">
            Discover a more refined shopping experience on Arolana with premium products,
            trusted vendors, and curated marketplace updates designed for serious buyers.
        </p>
        '''

    test_banner = ''
    if is_test:
        test_banner = '''
        <tr>
            <td style="padding:0 0 20px 0;">
                <div style="
                    background:#fff7ed;
                    color:#9a3412;
                    border:1px solid #fdba74;
                    border-radius:18px;
                    padding:16px 20px;
                    font-size:15px;
                    font-weight:700;
                    letter-spacing:0.2px;
                ">
                    TEST EMAIL — not sent to subscribers yet.
                </div>
            </td>
        </tr>
        '''

    primary_button_html = _render_button(button_url, button_text, filled=True)
    secondary_button_html = _render_button(secondary_button_url, secondary_button_text, filled=False)

    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{subject}</title>
    </head>
    <body style="margin:0; padding:0; background:#edf1f7; font-family:Arial, Helvetica, sans-serif;">
        <div style="display:none; max-height:0; overflow:hidden; opacity:0; color:transparent;">
            {preheader}
        </div>

        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#edf1f7; margin:0; padding:28px 0;">
            <tr>
                <td align="center">
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:720px; margin:0 auto;">
                        <tr>
                            <td style="padding:0 14px;">
                                <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="
                                    background:#ffffff;
                                    border-radius:32px;
                                    overflow:hidden;
                                    box-shadow:0 18px 54px rgba(6,19,43,0.08);
                                ">
                                    <tr>
                                        <td style="
                                            background:linear-gradient(135deg, #071531 0%, #0a1b48 60%, #132c74 100%);
                                            padding:30px 34px;
                                        ">
                                            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                                                <tr>
                                                    <td align="left" style="font-size:15px; color:#c7d4ff; letter-spacing:0.4px;">
                                                        <span style="display:inline-block; font-size:30px; font-weight:800; color:#ffffff; letter-spacing:-0.5px;">
                                                            {site_name}
                                                        </span>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td style="padding-top:10px; font-size:14px; color:#dbe5ff; line-height:1.7;">
                                                        Premium marketplace updates, featured products, and trusted vendor opportunities.
                                                    </td>
                                                </tr>
                                            </table>
                                        </td>
                                    </tr>

                                    <tr>
                                        <td style="padding:28px 34px 36px 34px;">
                                            {test_banner}

                                            {hero_block}

                                            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                                                <tr>
                                                    <td style="padding:0 0 8px 0; font-size:14px; color:#ff7a00; font-weight:800; letter-spacing:2px;">
                                                        {eyebrow}
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td style="padding:0 0 12px 0; font-size:52px; line-height:1.08; color:#0b1736; font-weight:800; letter-spacing:-1px;">
                                                        {headline}
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td style="padding:0 0 26px 0; font-size:18px; line-height:1.7; color:#5d6d89;">
                                                        {subheadline}
                                                    </td>
                                                </tr>
                                            </table>

                                            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="padding:0 0 10px 0;">
                                                <tr>
                                                    <td>
                                                        {content_html}
                                                    </td>
                                                </tr>
                                            </table>

                                            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="
                                                background:#f7f9fc;
                                                border:1px solid #e6edf8;
                                                border-radius:28px;
                                                margin:8px 0 30px 0;
                                            ">
                                                <tr>
                                                    <td style="padding:28px;">
                                                        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                                                            <tr>
                                                                {product_image_block}
                                                                <td valign="top" style="width:{'56%' if product_image_block else '100%'};">
                                                                    <div style="font-size:18px; line-height:1.35; font-weight:800; color:#0b1736; margin:0 0 12px 0;">
                                                                        {product_title}
                                                                    </div>
                                                                    <div style="font-size:17px; line-height:1.8; color:#5d6d89; margin:0 0 16px 0;">
                                                                        {product_description}
                                                                    </div>
                                                                    {'<div style="font-size:21px; line-height:1.3; font-weight:900; color:#0b1736;">' + product_price_text + '</div>' if product_price_text else ''}
                                                                </td>
                                                            </tr>
                                                        </table>
                                                    </td>
                                                </tr>
                                            </table>

                                            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                                                <tr>
                                                    <td align="left" style="padding:0 0 30px 0;">
                                                        <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                                                            <tr>
                                                                <td style="padding:0 14px 14px 0;">
                                                                    {primary_button_html}
                                                                </td>
                                                                <td style="padding:0 0 14px 0;">
                                                                    {secondary_button_html}
                                                                </td>
                                                            </tr>
                                                        </table>
                                                    </td>
                                                </tr>
                                            </table>

                                            {extra_html_content if extra_html_content else ''}
                                        </td>
                                    </tr>

                                    <tr>
                                        <td style="
                                            background:#071531;
                                            padding:34px;
                                            border-radius:0 0 32px 32px;
                                        ">
                                            <div style="font-size:18px; line-height:1.3; font-weight:800; color:#ffffff; margin:0 0 14px 0;">
                                                {site_name}
                                            </div>

                                            <div style="font-size:16px; line-height:1.8; color:#d4dcf3; margin:0 0 16px 0;">
                                                {footer_note}
                                            </div>

                                            <div style="font-size:15px; line-height:1.8; color:#9fb0d7; margin:0 0 14px 0;">
                                                Arolana Marketplace · Products, vendors, and smart commerce updates.
                                            </div>

                                            <div style="font-size:15px; line-height:1.8;">
                                                <a href="{unsubscribe_link}" style="color:#ffd19d; text-decoration:underline;">Unsubscribe</a>
                                            </div>
                                        </td>
                                    </tr>
                                </table>

                                <div style="text-align:center; font-size:13px; color:#8b98b3; padding:20px 10px 0 10px;">
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
    '''

    return html


def _campaign_plain_text(campaign, is_test=False):
    subject = _clean(getattr(campaign, 'subject', ''), 'Arolana Update')
    headline = _clean(getattr(campaign, 'headline', ''), subject)
    subheadline = _clean(getattr(campaign, 'subheadline', ''))
    content = _clean(getattr(campaign, 'content', ''))
    product_title = _clean(getattr(campaign, 'product_title', ''))
    product_description = _clean(getattr(campaign, 'product_description', ''))
    product_price_text = _clean(getattr(campaign, 'product_price_text', ''))
    button_text = _clean(getattr(campaign, 'button_text', 'View Product'))
    button_url = _clean(getattr(campaign, 'button_url', ''), 'https://arolana.com/')
    secondary_button_text = _clean(getattr(campaign, 'secondary_button_text', 'Visit Arolana'))
    secondary_button_url = _clean(getattr(campaign, 'secondary_button_url', ''), 'https://arolana.com/')

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


def _send_single_email(subject, plain_text, html_body, recipient):
    from_email = getattr(
        settings,
        'DEFAULT_FROM_EMAIL',
        'Arolana <support@arolana.com>',
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
    test_email = _clean(getattr(campaign, 'test_email', ''))
    if not test_email:
        return 0

    subject = _clean(getattr(campaign, 'subject', ''), 'Arolana Test Campaign')
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

    subject = _clean(getattr(campaign, 'subject', ''), 'Arolana Newsletter')
    sent_count = 0

    for email in recipients:
        plain_text = _campaign_plain_text(campaign, is_test=False)
        html_body = _render_luxury_campaign_html(
            campaign=campaign,
            recipient_email=email,
            is_test=False,
        )

        try:
            _send_single_email(subject, plain_text, html_body, email)
            sent_count += 1
        except Exception:
            continue

    campaign.sent_count = (campaign.sent_count or 0) + sent_count
    campaign.status = 'sent'
    campaign.sent_at = timezone.now()
    campaign.last_sent_at = campaign.sent_at
    campaign.save(update_fields=['sent_count', 'status', 'sent_at', 'last_sent_at', 'updated_at'])

    return sent_count