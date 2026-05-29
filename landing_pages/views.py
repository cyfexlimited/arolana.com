import json

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Prefetch
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


def _landing_page_queryset():
    active_sections = LandingPageSection.objects.filter(is_active=True).order_by("sort_order", "id")
    return LandingPage.objects.prefetch_related(
        Prefetch("sections", queryset=active_sections, to_attr="active_sections"),
        Prefetch("benefits", queryset=LandingPageBenefit.objects.filter(is_active=True).order_by("sort_order", "id"), to_attr="active_benefits"),
        Prefetch("offers", queryset=LandingPageOffer.objects.filter(is_active=True).order_by("sort_order", "id"), to_attr="active_offers"),
        Prefetch("steps", queryset=LandingPageStep.objects.filter(is_active=True).order_by("sort_order", "step_number", "id"), to_attr="active_steps"),
        Prefetch("category_cards", queryset=LandingPageCategoryCard.objects.filter(is_active=True).select_related("category").order_by("sort_order", "id"), to_attr="active_category_cards"),
        Prefetch("comparison_items", queryset=LandingPageComparisonItem.objects.filter(is_active=True).order_by("side", "sort_order", "id"), to_attr="active_comparison_items"),
        Prefetch("testimonials", queryset=LandingPageTestimonial.objects.filter(is_active=True).order_by("sort_order", "id"), to_attr="active_testimonials"),
        Prefetch("faqs", queryset=LandingPageFAQ.objects.filter(is_active=True).order_by("sort_order", "id"), to_attr="active_faqs"),
        Prefetch("ctas", queryset=LandingPageCTA.objects.filter(is_active=True).order_by("sort_order", "id"), to_attr="active_ctas"),
        Prefetch("contact_options", queryset=LandingPageContactOption.objects.filter(is_active=True).order_by("sort_order", "id"), to_attr="active_contact_options"),
        Prefetch("video_guides", queryset=LandingPageVideoGuide.objects.filter(is_active=True).order_by("sort_order", "id"), to_attr="active_video_guides"),
    )


def _context_for_page(page, preview=False):
    sections = list(getattr(page, "active_sections", []))
    section_by_type = {}
    for section in sections:
        section_by_type.setdefault(section.section_type, section)

    comparison_items = list(getattr(page, "active_comparison_items", []))
    nav_items = [
        ("benefits", section_by_type.get("benefits"), "Benefits", bool(getattr(page, "active_benefits", []))),
        ("offers", section_by_type.get("offers"), "Offers", bool(getattr(page, "active_offers", []))),
        ("how-it-works", section_by_type.get("how_it_works"), "How It Works", bool(getattr(page, "active_steps", []))),
        ("categories", section_by_type.get("eligible_categories"), "Categories", bool(getattr(page, "active_category_cards", []))),
        ("video-guides", section_by_type.get("video_guides") or section_by_type.get("video"), "Video Guides", bool(getattr(page, "active_video_guides", []))),
        ("comparison", section_by_type.get("comparison"), "Compare", bool(comparison_items)),
        ("testimonials", section_by_type.get("testimonials"), "Stories", bool(getattr(page, "active_testimonials", []))),
        ("faq", section_by_type.get("faq"), "FAQ", bool(getattr(page, "active_faqs", []))),
        ("contact", section_by_type.get("contact"), "Contact", bool(getattr(page, "active_contact_options", []))),
    ]

    return {
        "page": page,
        "preview": preview,
        "schema_json": json.dumps(page.schema_markup) if page.schema_markup else "",
        "sections": sections,
        "section_by_type": section_by_type,
        "benefits_section": section_by_type.get("benefits"),
        "offers_section": section_by_type.get("offers"),
        "steps_section": section_by_type.get("how_it_works"),
        "categories_section": section_by_type.get("eligible_categories"),
        "video_guides_section": section_by_type.get("video_guides") or section_by_type.get("video"),
        "comparison_section": section_by_type.get("comparison"),
        "testimonials_section": section_by_type.get("testimonials"),
        "faq_section": section_by_type.get("faq"),
        "contact_section": section_by_type.get("contact"),
        "terms_section": section_by_type.get("terms"),
        "custom_sections": [section for section in sections if section.section_type == "custom_html"],
        "benefits": list(getattr(page, "active_benefits", [])),
        "offers": list(getattr(page, "active_offers", [])),
        "steps": list(getattr(page, "active_steps", [])),
        "category_cards": list(getattr(page, "active_category_cards", [])),
        "negative_comparison_items": [item for item in comparison_items if item.side == "negative"],
        "positive_comparison_items": [item for item in comparison_items if item.side == "positive"],
        "testimonials": list(getattr(page, "active_testimonials", [])),
        "faqs": list(getattr(page, "active_faqs", [])),
        "ctas": list(getattr(page, "active_ctas", [])),
        "contact_options": list(getattr(page, "active_contact_options", [])),
        "video_guides": list(getattr(page, "active_video_guides", [])),
        "nav_items": [item for item in nav_items if item[3]],
    }


def landing_page_detail(request, slug):
    page = get_object_or_404(
        _landing_page_queryset(),
        slug=slug,
        status=LandingPage.STATUS_PUBLISHED,
        is_active=True,
    )
    return render(request, "landing_pages/detail.html", _context_for_page(page))


@staff_member_required
def landing_page_preview(request, slug):
    page = get_object_or_404(_landing_page_queryset(), slug=slug)
    return render(request, "landing_pages/detail.html", _context_for_page(page, preview=True))
