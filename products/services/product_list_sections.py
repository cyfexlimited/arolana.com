import random

from django.db.models import Prefetch

from blog.models import BlogPost
from installers.models import (
    ProviderService,
    ServiceProviderProfile,
)
from products.models import (
    ProductArticleLink,
    ProductListLowerSection,
)
from products.services.recommendation_engine import (
    RecommendationEngine,
)


def _buying_guides(section):
    links = (
        ProductArticleLink.objects
        .filter(
            is_active=True,
            article__is_published=True,
            product__is_active=True,
            product__approval_status="approved",
        )
        .select_related(
            "article",
            "product",
        )
        .order_by(
            "sort_order",
            "-article__published_at",
        )
    )

    guides = []
    used_articles = set()

    for link in links:
        if link.article_id in used_articles:
            continue

        used_articles.add(link.article_id)
        guides.append(link)

        if len(guides) >= section.maximum_items:
            break

    return guides


def _recently_viewed(request, section):
    return RecommendationEngine.recent_products(
        request=request,
        limit=section.maximum_items,
    )


def _recommended_products(
    request,
    section,
    recent_products,
):
    return RecommendationEngine.for_user(
        request=request,
        limit=section.maximum_items,
        exclude_ids=[
            product.id
            for product in recent_products
        ],
    )


def _verified_providers(section):
    limit = min(
        section.maximum_items,
        40,
    )

    providers = (
        ServiceProviderProfile.objects
        .public()
        .filter(
            is_verified=True,
        )
        .select_related(
            "user",
        )
        .prefetch_related(
            Prefetch(
                "services",
                queryset=(
                    ProviderService.objects
                    .filter(is_active=True)
                    .select_related("category")
                    .order_by("id")
                ),
                to_attr="featured_services",
            )
        )
        .order_by(
            "-average_rating",
            "-total_completed_jobs",
            "-total_reviews",
            "business_name",
        )[:limit]
    )

    return list(providers)


def _blog_posts(section):
    limit = min(
        section.maximum_items,
        38,
    )

    posts = list(
        BlogPost.objects
        .filter(
            is_published=True,
        )
        .order_by(
            "-published_at",
        )[:100]
    )

    featured = [
        post
        for post in posts
        if post.is_featured
    ]

    regular = [
        post
        for post in posts
        if not post.is_featured
    ]

    if section.shuffle_on_refresh:
        random.shuffle(regular)

    return (
        featured + regular
    )[:limit]


def get_product_list_sections(request):
    sections = list(
        ProductListLowerSection.objects
        .filter(is_active=True)
        .prefetch_related(
            "trust_benefits",
        )
        .order_by(
            "display_order",
            "id",
        )
    )

    recent_products = []

    for section in sections:
        section.items = []

        if section.section_type == "buying_guides":
            section.items = _buying_guides(
                section,
            )

        elif section.section_type == "recently_viewed":
            recent_products = _recently_viewed(
                request,
                section,
            )

            section.items = recent_products

        elif section.section_type == "recommendations":
            section.items = _recommended_products(
                request,
                section,
                recent_products,
            )

        elif section.section_type == "verified_providers":
            section.items = _verified_providers(
                section,
            )

        elif section.section_type == "blog":
            section.items = _blog_posts(
                section,
            )

    return {
        "product_lower_sections": sections,
    }