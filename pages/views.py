from django.contrib import messages
from django.db.models import F
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.content_i18n import translated_field
from .models import (
    CareerCategory,
    ContactPageSettings,
    ContactQuickAction,
    FAQ,
    HelpCenterHero,
    JobApplication,
    JobPosition,
    Page,
    SupportArticle,
    SupportTopic,
)

try:
    from core.media_optimization import get_optimized_image_url
except Exception:
    get_optimized_image_url = None


def _localize(instance, request, *field_names):
    if not instance:
        return instance
    for field_name in field_names:
        setattr(
            instance,
            field_name,
            translated_field(instance, field_name, request=request),
        )
    return instance


def help_center(request):
    """Public Help Center page."""

    topics = SupportTopic.objects.filter(is_active=True).order_by("order", "title")

    featured_faqs = list(FAQ.objects.filter(
        is_active=True,
        is_featured=True,
    ).order_by("order", "question")[:6])

    if not featured_faqs:
        featured_faqs = list(
            FAQ.objects.filter(is_active=True).order_by("order", "question")[:6]
        )
    featured_faqs = [
        _localize(faq, request, "question", "answer")
        for faq in featured_faqs
    ]

    # Prefer an active hero that actually has an uploaded background image.
    hero = (
        HelpCenterHero.objects
        .filter(is_active=True)
        .exclude(background_image="")
        .order_by("-updated_at", "-id")
        .first()
    )

    # Fallback to any active hero if no image-backed hero exists.
    if not hero:
        hero = (
            HelpCenterHero.objects
            .filter(is_active=True)
            .order_by("-updated_at", "-id")
            .first()
        )

    hero_background_url = ""

    if hero and hero.background_image:
        try:
            hero_background_url = hero.background_image.url
        except Exception:
            hero_background_url = ""

    context = {
        "topics": topics,
        "featured_faqs": featured_faqs,
        "hero": hero,
        "hero_background_url": hero_background_url,
        "page_title": "Help Center",
    }

    return render(request, "pages/help_center.html", context)


def faq_page(request):
    """Public FAQ page grouped by category."""

    faqs = list(
        FAQ.objects.filter(is_active=True).order_by("category", "order", "question")
    )
    faqs = [_localize(faq, request, "question", "answer") for faq in faqs]

    categories = {}
    for faq in faqs:
        category_display = faq.get_category_display()
        categories.setdefault(category_display, []).append(faq)

    context = {
        "categories": categories,
        "total_faqs": len(faqs),
        "page_title": "Frequently Asked Questions",
    }
    return render(request, "pages/faq.html", context)


def article_detail(request, slug):
    """Support article detail page."""

    article = get_object_or_404(
        SupportArticle.objects.select_related("category"),
        slug=slug,
        is_active=True,
    )

    SupportArticle.objects.filter(pk=article.pk).update(views=F("views") + 1)
    article.refresh_from_db(fields=["views"])
    _localize(article, request, "title", "content")

    related_articles = list(
        SupportArticle.objects.filter(
            category=article.category,
            is_active=True,
        )
        .exclude(pk=article.pk)
        .select_related("category")[:5]
    )
    related_articles = [
        _localize(item, request, "title", "content")
        for item in related_articles
    ]

    context = {
        "article": article,
        "related_articles": related_articles,
        "page_title": article.title,
    }
    return render(request, "pages/article_detail.html", context)


def page_detail(request, slug):
    """Generic editable page detail."""

    page = get_object_or_404(Page, slug=slug, is_active=True)
    _localize(page, request, "title", "content", "sidebar_content", "meta_description")

    context = {
        "page": page,
        "page_title": page.title,
    }
    return render(request, "pages/page_detail.html", context)


def page_by_slug(request, slug):
    """Render public editable pages by root slug."""

    page = get_object_or_404(Page, slug=slug, is_active=True)
    _localize(page, request, "title", "content", "sidebar_content", "meta_description")

    context = {
        "page": page,
        "public_slug": slug,
        "page_title": page.title,
    }
    return render(request, "pages/page_detail.html", context)


def support_redirect(request):
    """Redirect support URL to Help Center."""

    return HttpResponseRedirect(reverse("pages:help_center"))


def article_helpful(request, article_id):
    """Mark support article as helpful or not helpful."""

    article = get_object_or_404(SupportArticle, id=article_id, is_active=True)

    if request.method == "POST":
        helpful = request.POST.get("helpful") == "true"

        if helpful:
            SupportArticle.objects.filter(pk=article.pk).update(helpful_count=F("helpful_count") + 1)
        else:
            SupportArticle.objects.filter(pk=article.pk).update(not_helpful_count=F("not_helpful_count") + 1)

        messages.success(request, "Thank you for your feedback!")

    return redirect("pages:article_detail", slug=article.slug)


def contact_page(request):
    """Contact page with support guidance."""

    page = Page.objects.filter(slug="contact", is_active=True).first()
    contact_settings = ContactPageSettings.objects.filter(is_active=True).order_by("-updated_at").first()
    quick_actions = ContactQuickAction.objects.filter(is_active=True).order_by("order", "label")

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        subject = request.POST.get("subject", "").strip()
        message = request.POST.get("message", "").strip()

        if not all([name, email, subject, message]):
            messages.error(request, "Please complete all required fields before sending your message.")
            return redirect("pages:contact")

        messages.success(request, "Thank you for contacting Arolana. We will get back to you soon.")
        return redirect("pages:contact")

    context = {
        "page": page,
        "contact_settings": contact_settings,
        "quick_actions": quick_actions,
        "page_title": "Contact Arolana",
    }
    return render(request, "support/contact.html", context)


def careers_page(request):
    """Careers page powered from database."""

    open_positions = JobPosition.objects.filter(is_active=True).select_related("category")
    featured_positions = open_positions.filter(is_featured=True)[:3]
    categories = CareerCategory.objects.filter(is_active=True).order_by("order", "name")

    positions_by_category = {}
    for category in categories:
        positions = open_positions.filter(category=category)
        if positions.exists():
            positions_by_category[category.name] = positions

    context = {
        "page_title": "Careers at Arolana",
        "page": Page.objects.filter(slug="careers", is_active=True).first(),
        "open_positions": open_positions,
        "featured_positions": featured_positions,
        "positions_by_category": positions_by_category,
        "categories": categories,
        "total_positions": open_positions.count(),
    }
    return render(request, "pages/careers.html", context)


def job_detail(request, slug):
    """Individual job position details."""

    position = get_object_or_404(
        JobPosition.objects.select_related("category"),
        slug=slug,
        is_active=True,
    )

    related_positions = (
        JobPosition.objects.filter(
            category=position.category,
            is_active=True,
        )
        .exclude(pk=position.pk)
        .select_related("category")[:3]
    )

    context = {
        "position": position,
        "related_positions": related_positions,
        "page_title": position.title,
    }
    return render(request, "pages/job_detail.html", context)


def apply_for_job(request, position_id):
    """Handle job applications."""

    position = get_object_or_404(JobPosition, id=position_id, is_active=True)

    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip()

        if not all([first_name, last_name, email]):
            messages.error(request, "Please fill in your first name, last name, and email address.")
            return redirect("pages:job_detail", slug=position.slug)

        application = JobApplication.objects.create(
            position=position,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=request.POST.get("phone", "").strip(),
            cover_letter=request.POST.get("cover_letter", "").strip(),
            portfolio_url=request.POST.get("portfolio_url", "").strip(),
            linkedin_url=request.POST.get("linkedin_url", "").strip(),
        )

        if request.FILES.get("resume"):
            application.resume = request.FILES["resume"]
            application.save(update_fields=["resume", "updated_at"])

        messages.success(
            request,
            f"Thank you for applying for {position.title}. We will review your application and get back to you soon.",
        )
        return redirect("pages:careers")

    return render(
        request,
        "pages/apply_form.html",
        {
            "position": position,
            "page_title": f"Apply for {position.title}",
        },
    )


def help_center_redirect(request, invalid_path=None):
    """Redirect invalid Help Center paths to main Help Center."""

    return redirect("pages:help_center")
