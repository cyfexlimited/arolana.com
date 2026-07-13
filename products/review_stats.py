"""Authoritative product review aggregation helpers.

ProductReview rows are the source of truth. Product.rating_avg and
Product.rating_count are denormalized cache fields used for fast product-card
sorting and display.
"""

from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Avg, Count, Q

from .models import Product, ProductReview


ZERO_RATING = Decimal("0.00")
RATING_QUANTUM = Decimal("0.01")


def _normalise_average(value):
    """Return a safe two-decimal rating between 0.00 and 5.00."""

    try:
        average = Decimal(str(value or 0))
    except (ArithmeticError, TypeError, ValueError):
        average = ZERO_RATING

    average = max(ZERO_RATING, min(Decimal("5.00"), average))

    return average.quantize(
        RATING_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def calculate_product_review_stats(product_id):
    """Calculate review statistics directly from ProductReview rows."""

    if not product_id:
        return {
            "count": 0,
            "average": ZERO_RATING,
            "verified_count": 0,
            "five_star_count": 0,
            "four_star_count": 0,
            "three_star_count": 0,
            "two_star_count": 0,
            "one_star_count": 0,
            "five_star_percent": 0,
            "four_star_percent": 0,
            "three_star_percent": 0,
            "two_star_percent": 0,
            "one_star_percent": 0,
        }

    row = (
        ProductReview.objects
        .filter(product_id=product_id)
        .aggregate(
            average=Avg("rating"),
            total=Count("id"),
            verified_count=Count(
                "id",
                filter=Q(verified_purchase=True),
            ),
            five_star_count=Count("id", filter=Q(rating=5)),
            four_star_count=Count("id", filter=Q(rating=4)),
            three_star_count=Count("id", filter=Q(rating=3)),
            two_star_count=Count("id", filter=Q(rating=2)),
            one_star_count=Count("id", filter=Q(rating=1)),
        )
    )

    count = int(row.get("total") or 0)
    denominator = count or 1

    stats = {
        "count": count,
        "average": _normalise_average(row.get("average")),
        "verified_count": int(row.get("verified_count") or 0),
    }

    for label in ("five", "four", "three", "two", "one"):
        count_key = f"{label}_star_count"
        percent_key = f"{label}_star_percent"
        star_count = int(row.get(count_key) or 0)

        stats[count_key] = star_count
        stats[percent_key] = int((star_count / denominator) * 100)

    return stats


def refresh_product_review_stats(product_id):
    """Refresh one product's denormalized rating cache fields."""

    stats = calculate_product_review_stats(product_id)

    if product_id:
        Product.objects.filter(pk=product_id).update(
            rating_avg=stats["average"],
            rating_count=stats["count"],
        )

    return stats
