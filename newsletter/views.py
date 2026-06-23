import csv
import json
import re
from urllib.parse import unquote

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .emailing import send_campaign, send_test_campaign, upsert_email_audience
from .models import NewsletterCampaign, NewsletterSubscriber, NewsletterTracking


def validate_email(email):
    """Simple email validation."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(pattern, email or "") is not None


def clean_email(email):
    return str(email or "").strip().lower()


def clean_source(source):
    source = str(source or "homepage").strip().lower()
    allowed_sources = {choice[0] for choice in NewsletterSubscriber.SOURCE_CHOICES}
    return source if source in allowed_sources else "other"


def subscribe(request):
    """Handle newsletter subscription form submission."""
    if request.method != "POST":
        return redirect("/")

    email = clean_email(request.POST.get("email", ""))
    name = request.POST.get("name", "").strip()
    source = clean_source(request.POST.get("source", "homepage"))
    next_url = request.POST.get("next", "/") or "/"

    if not email:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": "Email is required"},
                status=400,
            )
        messages.error(request, "Please enter a valid email address.")
        return redirect(next_url)

    if not validate_email(email):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": "Invalid email format"},
                status=400,
            )
        messages.error(request, "Please enter a valid email address.")
        return redirect(next_url)

    subscriber, created = NewsletterSubscriber.objects.get_or_create(
        email=email,
        defaults={
            "name": name,
            "source": source,
            "is_active": True,
        },
    )

    if not created:
        changed = False

        if name and not subscriber.name:
            subscriber.name = name
            changed = True

        if source and subscriber.source != source:
            subscriber.source = source
            changed = True

        if subscriber.is_active:
            upsert_email_audience(
                email,
                name=name or subscriber.name,
                source="newsletter",
                subscriber=subscriber,
                accepts_promos=True,
            )

            if changed:
                subscriber.save(update_fields=["name", "source", "updated_at"])

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "success": False,
                        "error": "This email is already subscribed.",
                        "already_subscribed": True,
                    },
                    status=400,
                )

            messages.info(request, f"{email} is already subscribed.")
            return redirect(next_url)

        subscriber.is_active = True
        subscriber.unsubscribed_at = None

        if changed:
            subscriber.save(update_fields=["name", "source", "is_active", "unsubscribed_at", "updated_at"])
        else:
            subscriber.save(update_fields=["is_active", "unsubscribed_at", "updated_at"])

        upsert_email_audience(
            email,
            name=name or subscriber.name,
            source="newsletter",
            subscriber=subscriber,
            accepts_promos=True,
        )

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "success": True,
                    "message": "Welcome back! You have been re-subscribed.",
                    "already_subscribed": True,
                }
            )

        messages.success(request, f"Welcome back! {email} has been re-subscribed.")
        return redirect(next_url)

    upsert_email_audience(
        email,
        name=name,
        source="newsletter",
        subscriber=subscriber,
        accepts_promos=True,
    )

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "success": True,
                "message": f"Successfully subscribed with {email}! Thank you.",
                "email": email,
            }
        )

    messages.success(request, f"Successfully subscribed with {email}! Thank you.")
    return redirect(next_url)


@csrf_exempt
@require_http_methods(["POST"])
def api_subscribe(request):
    """AJAX/API endpoint for newsletter subscription."""
    try:
        if request.content_type == "application/json":
            data = json.loads(request.body or "{}")
            email = clean_email(data.get("email", ""))
            name = str(data.get("name", "")).strip()
            source = clean_source(data.get("source", "api"))
        else:
            email = clean_email(request.POST.get("email", ""))
            name = request.POST.get("name", "").strip()
            source = clean_source(request.POST.get("source", "api"))

        if not email:
            return JsonResponse(
                {"success": False, "error": "Email is required"},
                status=400,
            )

        if not validate_email(email):
            return JsonResponse(
                {"success": False, "error": "Invalid email format"},
                status=400,
            )

        subscriber, created = NewsletterSubscriber.objects.get_or_create(
            email=email,
            defaults={
                "name": name,
                "source": source,
                "is_active": True,
            },
        )

        if not created:
            changed = False

            if name and not subscriber.name:
                subscriber.name = name
                changed = True

            if source and subscriber.source != source:
                subscriber.source = source
                changed = True

            if subscriber.is_active:
                if changed:
                    subscriber.save(update_fields=["name", "source", "updated_at"])

                upsert_email_audience(
                    email,
                    name=name or subscriber.name,
                    source="newsletter",
                    subscriber=subscriber,
                    accepts_promos=True,
                )

                return JsonResponse(
                    {
                        "success": False,
                        "error": "This email is already subscribed.",
                        "already_subscribed": True,
                    },
                    status=400,
                )

            subscriber.is_active = True
            subscriber.unsubscribed_at = None

            if changed:
                subscriber.save(update_fields=["name", "source", "is_active", "unsubscribed_at", "updated_at"])
            else:
                subscriber.save(update_fields=["is_active", "unsubscribed_at", "updated_at"])

            upsert_email_audience(
                email,
                name=name or subscriber.name,
                source="newsletter",
                subscriber=subscriber,
                accepts_promos=True,
            )

            return JsonResponse(
                {
                    "success": True,
                    "message": "Welcome back! You have been re-subscribed.",
                    "already_subscribed": True,
                    "email": email,
                }
            )

        upsert_email_audience(
            email,
            name=name,
            source="newsletter",
            subscriber=subscriber,
            accepts_promos=True,
        )

        return JsonResponse(
            {
                "success": True,
                "message": "Successfully subscribed to our newsletter!",
                "email": email,
            }
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": "Invalid JSON"},
            status=400,
        )
    except Exception as error:
        return JsonResponse(
            {"success": False, "error": str(error)},
            status=500,
        )


def unsubscribe(request, email):
    """Unsubscribe from newsletter."""
    email = clean_email(unquote(email))

    try:
        subscriber = NewsletterSubscriber.objects.get(email=email, is_active=True)
        subscriber.is_active = False
        subscriber.unsubscribed_at = timezone.now()
        subscriber.save(update_fields=["is_active", "unsubscribed_at", "updated_at"])

        upsert_email_audience(
            email,
            name=subscriber.name,
            source="newsletter",
            subscriber=subscriber,
            accepts_promos=False,
        )

        messages.success(request, f"Successfully unsubscribed {email} from our newsletter.")
    except NewsletterSubscriber.DoesNotExist:
        messages.info(request, f"{email} was not found in our active subscriber list.")

    return redirect("/")


def unsubscribe_token(request, token):
    """Placeholder for token-based unsubscribe."""
    messages.info(request, "This unsubscribe link is no longer active.")
    return redirect("/")


def track_open(request, tracking_id):
    """Track email opens."""
    try:
        tracking = NewsletterTracking.objects.select_related("campaign").get(id=tracking_id)

        if not tracking.opened_at:
            tracking.opened_at = timezone.now()
            tracking.ip_address = request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("REMOTE_ADDR")
            tracking.user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]
            tracking.save(update_fields=["opened_at", "ip_address", "user_agent", "updated_at"])

        campaign = tracking.campaign
        campaign.open_count = campaign.tracking.filter(opened_at__isnull=False).count()
        campaign.save(update_fields=["open_count", "updated_at"])

    except Exception:
        pass

    pixel = (
        b"GIF89a\x01\x00\x01\x00\x00\xff\x00\x00\x00\x00\x00!"
        b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00"
        b"\x01\x00\x00\x02\x02D\x01\x00;"
    )
    return HttpResponse(pixel, content_type="image/gif")


def track_click(request, tracking_id):
    """Track email clicks, then redirect to campaign CTA if available."""
    redirect_url = "/"

    try:
        tracking = NewsletterTracking.objects.select_related("campaign").get(id=tracking_id)

        if not tracking.clicked_at:
            tracking.clicked_at = timezone.now()
            tracking.ip_address = request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("REMOTE_ADDR")
            tracking.user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]
            tracking.save(update_fields=["clicked_at", "ip_address", "user_agent", "updated_at"])

        campaign = tracking.campaign
        campaign.click_count = campaign.tracking.filter(clicked_at__isnull=False).count()
        campaign.save(update_fields=["click_count", "updated_at"])

        if campaign.button_url:
            redirect_url = campaign.button_url

    except Exception:
        pass

    return redirect(redirect_url)


@staff_member_required
def campaign_list(request):
    campaigns = NewsletterCampaign.objects.all().order_by("-created_at")
    return render(request, "newsletter/campaign_list.html", {"campaigns": campaigns})


@staff_member_required
def campaign_create(request):
    """
    Staff campaign create page.

    Admin is still the recommended way:
    Admin → Newsletter → Newsletter campaigns.
    """
    if request.method == "POST":
        campaign = NewsletterCampaign.objects.create(
            name=request.POST.get("name", "").strip(),
            campaign_type=request.POST.get("campaign_type", "general"),
            hero_only=bool(request.POST.get("hero_only")),
            subject=request.POST.get("subject", "").strip(),
            preheader=request.POST.get("preheader", "").strip(),
            eyebrow=request.POST.get("eyebrow", "").strip(),
            headline=request.POST.get("headline", "").strip(),
            subheadline=request.POST.get("subheadline", "").strip(),
            content=request.POST.get("content", "").strip(),
            html_content=request.POST.get("html_content", "").strip(),
            hero_image_url=request.POST.get("hero_image_url", "").strip(),
            product_image_url=request.POST.get("product_image_url", "").strip(),
            product_title=request.POST.get("product_title", "").strip(),
            product_price_text=request.POST.get("product_price_text", "").strip(),
            product_description=request.POST.get("product_description", "").strip(),
            button_text=request.POST.get("button_text", "Shop now").strip() or "Shop now",
            button_url=request.POST.get("button_url", "").strip(),
            secondary_button_text=request.POST.get("secondary_button_text", "").strip(),
            secondary_button_url=request.POST.get("secondary_button_url", "").strip(),
            footer_note=request.POST.get("footer_note", "").strip(),
            test_email=request.POST.get("test_email", "").strip(),
            recipient_scope=request.POST.get("recipient_scope", "all"),
            send_frequency=request.POST.get("send_frequency", "once"),
            scheduled_at=request.POST.get("scheduled_at") or None,
            status="draft",
        )

        messages.success(request, f'Campaign "{campaign.name}" created.')
        return redirect("newsletter:campaign_detail", campaign_id=campaign.id)

    return render(request, "newsletter/campaign_form.html")


@staff_member_required
def campaign_detail(request, campaign_id):
    campaign = get_object_or_404(NewsletterCampaign, id=campaign_id)
    return render(request, "newsletter/campaign_detail.html", {"campaign": campaign})


@staff_member_required
def campaign_send(request, campaign_id):
    campaign = get_object_or_404(NewsletterCampaign, id=campaign_id)

    if request.method == "POST":
        send_type = request.POST.get("send_type", "live")

        if send_type == "test":
            sent_count = send_test_campaign(campaign)
            if sent_count:
                messages.success(request, f'Test campaign "{campaign.name}" sent.')
            else:
                messages.error(request, "Test email is empty. Add a test email before sending.")
        else:
            sent_count = send_campaign(campaign)
            messages.success(
                request,
                f'Campaign "{campaign.name}" sent to {sent_count} email address(es).',
            )

        return redirect("newsletter:campaign_detail", campaign_id=campaign.id)

    return render(request, "newsletter/campaign_send.html", {"campaign": campaign})


@staff_member_required
def subscriber_list(request):
    subscribers = NewsletterSubscriber.objects.all().order_by("-subscribed_at")
    return render(request, "newsletter/subscriber_list.html", {"subscribers": subscribers})


@staff_member_required
def subscriber_detail(request, subscriber_id):
    subscriber = get_object_or_404(NewsletterSubscriber, id=subscriber_id)
    return render(request, "newsletter/subscriber_detail.html", {"subscriber": subscriber})


@staff_member_required
def subscriber_export(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="subscribers.csv"'

    writer = csv.writer(response)
    writer.writerow(["Email", "Name", "Source", "Subscribed At", "Status"])

    for sub in NewsletterSubscriber.objects.all():
        writer.writerow([
            sub.email,
            sub.name,
            sub.source,
            sub.subscribed_at,
            "Active" if sub.is_active else "Inactive",
        ])

    return response