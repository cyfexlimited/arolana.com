import json

from django.contrib.admin.views.decorators import staff_member_required
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import (
    LandingPage,
    LandingPageBenefit,
    LandingPageCTA,
    LandingPageCategoryCard,
    LandingPageComparisonItem,
    LandingPageContactOption,
    LandingPageFAQ,
    LandingPageOffer,
    LandingPageSection,
    LandingPageStep,
    LandingPageTestimonial,
    LandingPageVideoGuide,
)


def _active_queryset(model, *order_fields):
    """Reusable helper for active landing page child objects."""
    return model.objects.filter(is_active=True).order_by(*order_fields)


def _landing_page_queryset():
    """
    Optimized landing page queryset.

    This prefetches only active builder items and stores them as active_* attributes,
    so the detail page does not keep hitting the database section by section.
    """
    active_sections = _active_queryset(LandingPageSection, "sort_order", "id")

    return (
        LandingPage.objects
        .prefetch_related(
            Prefetch("sections", queryset=active_sections, to_attr="active_sections"),
            Prefetch(
                "benefits",
                queryset=_active_queryset(LandingPageBenefit, "sort_order", "id"),
                to_attr="active_benefits",
            ),
            Prefetch(
                "offers",
                queryset=_active_queryset(LandingPageOffer, "sort_order", "id"),
                to_attr="active_offers",
            ),
            Prefetch(
                "steps",
                queryset=_active_queryset(LandingPageStep, "sort_order", "step_number", "id"),
                to_attr="active_steps",
            ),
            Prefetch(
                "category_cards",
                queryset=(
                    LandingPageCategoryCard.objects
                    .filter(is_active=True)
                    .select_related("category")
                    .order_by("sort_order", "id")
                ),
                to_attr="active_category_cards",
            ),
            Prefetch(
                "comparison_items",
                queryset=_active_queryset(LandingPageComparisonItem, "side", "sort_order", "id"),
                to_attr="active_comparison_items",
            ),
            Prefetch(
                "testimonials",
                queryset=_active_queryset(LandingPageTestimonial, "sort_order", "id"),
                to_attr="active_testimonials",
            ),
            Prefetch(
                "faqs",
                queryset=_active_queryset(LandingPageFAQ, "sort_order", "id"),
                to_attr="active_faqs",
            ),
            Prefetch(
                "ctas",
                queryset=_active_queryset(LandingPageCTA, "sort_order", "id"),
                to_attr="active_ctas",
            ),
            Prefetch(
                "contact_options",
                queryset=_active_queryset(LandingPageContactOption, "sort_order", "id"),
                to_attr="active_contact_options",
            ),
            Prefetch(
                "video_guides",
                queryset=_active_queryset(LandingPageVideoGuide, "sort_order", "id"),
                to_attr="active_video_guides",
            ),
        )
    )


def _first_section(section_by_type, *section_types):
    """Return the first matching section object for multiple possible section types."""
    for section_type in section_types:
        section = section_by_type.get(section_type)
        if section:
            return section
    return None


def _json_dumps_safe(value):
    """Safely serialize schema markup for JSON-LD."""
    if not value:
        return ""
    try:
        return json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False)
    except TypeError:
        return ""


def _context_for_page(page, preview=False):
    """
    Build all landing page detail context in one place.

    Important:
    The nav anchors must match the section IDs in templates/landing_pages/detail.html.
    The previous category nav used "eligible-products" but the template section ID is "categories".
    That mismatch would make the mini nav fail, so it is corrected here.
    """
    sections = list(getattr(page, "active_sections", []))

    section_by_type = {}
    for section in sections:
        section_by_type.setdefault(section.section_type, section)

    benefits = list(getattr(page, "active_benefits", []))
    offers = list(getattr(page, "active_offers", []))
    steps = list(getattr(page, "active_steps", []))
    category_cards = list(getattr(page, "active_category_cards", []))
    comparison_items = list(getattr(page, "active_comparison_items", []))
    testimonials = list(getattr(page, "active_testimonials", []))
    faqs = list(getattr(page, "active_faqs", []))
    ctas = list(getattr(page, "active_ctas", []))
    contact_options = list(getattr(page, "active_contact_options", []))
    video_guides = list(getattr(page, "active_video_guides", []))

    benefits_section = _first_section(section_by_type, LandingPageSection.SECTION_BENEFITS)
    offers_section = _first_section(section_by_type, LandingPageSection.SECTION_OFFERS)
    steps_section = _first_section(section_by_type, LandingPageSection.SECTION_HOW_IT_WORKS)
    categories_section = _first_section(section_by_type, LandingPageSection.SECTION_ELIGIBLE_CATEGORIES)
    video_guides_section = _first_section(
        section_by_type,
        LandingPageSection.SECTION_VIDEO_GUIDES,
        LandingPageSection.SECTION_VIDEO,
    )
    comparison_section = _first_section(section_by_type, LandingPageSection.SECTION_COMPARISON)
    testimonials_section = _first_section(section_by_type, LandingPageSection.SECTION_TESTIMONIALS)
    faq_section = _first_section(section_by_type, LandingPageSection.SECTION_FAQ)
    contact_section = _first_section(section_by_type, LandingPageSection.SECTION_CONTACT)
    terms_section = _first_section(section_by_type, LandingPageSection.SECTION_TERMS)

    negative_comparison_items = [
        item for item in comparison_items
        if item.side == LandingPageComparisonItem.SIDE_NEGATIVE
    ]
    positive_comparison_items = [
        item for item in comparison_items
        if item.side == LandingPageComparisonItem.SIDE_POSITIVE
    ]

    nav_items = [
        ("benefits", benefits_section, "Benefits", bool(benefits)),
        ("offers", offers_section, "Offers", bool(offers)),
        ("how-it-works", steps_section, "How It Works", bool(steps)),

        # Must match detail.html: <section id="categories">
        ("categories", categories_section, "Categories", bool(category_cards)),

        ("video-guides", video_guides_section, "Video Guides", bool(video_guides)),
        ("comparison", comparison_section, "Compare", bool(comparison_items)),
        ("testimonials", testimonials_section, "Stories", bool(testimonials)),
        ("faq", faq_section, "FAQ", bool(faqs)),
        ("contact", contact_section, "Contact", bool(contact_options)),
    ]

    return {
        "page": page,
        "preview": preview,
        "schema_json": _json_dumps_safe(page.schema_markup),

        "sections": sections,
        "section_by_type": section_by_type,

        "benefits_section": benefits_section,
        "offers_section": offers_section,
        "steps_section": steps_section,
        "categories_section": categories_section,
        "video_guides_section": video_guides_section,
        "comparison_section": comparison_section,
        "testimonials_section": testimonials_section,
        "faq_section": faq_section,
        "contact_section": contact_section,
        "terms_section": terms_section,

        "custom_sections": [
            section for section in sections
            if section.section_type == LandingPageSection.SECTION_CUSTOM_HTML
        ],

        "benefits": benefits,
        "offers": offers,
        "steps": steps,
        "category_cards": category_cards,
        "negative_comparison_items": negative_comparison_items,
        "positive_comparison_items": positive_comparison_items,
        "testimonials": testimonials,
        "faqs": faqs,
        "ctas": ctas,
        "contact_options": contact_options,
        "video_guides": video_guides,

        "nav_items": [item for item in nav_items if item[3]],
    }


def landing_page_detail(request, slug):
    """Public published landing page detail."""
    if not slug:
        raise Http404("Landing page not found.")

    page = get_object_or_404(
        _landing_page_queryset(),
        slug=slug,
        status=LandingPage.STATUS_PUBLISHED,
        is_active=True,
    )
    return render(request, "landing_pages/detail.html", _context_for_page(page))


@staff_member_required
def landing_page_preview(request, slug):
    """Staff-only preview for draft, archived, inactive, and published landing pages."""
    if not slug:
        raise Http404("Landing page not found.")

    page = get_object_or_404(_landing_page_queryset(), slug=slug)
    return render(request, "landing_pages/detail.html", _context_for_page(page, preview=True))
