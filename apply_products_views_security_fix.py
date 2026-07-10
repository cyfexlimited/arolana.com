#!/usr/bin/env python3
# Arolana products/views.py secure review + Q&A patcher.
# Run from project root:
#     python apply_products_views_security_fix.py

from pathlib import Path
from datetime import datetime
import re

TARGET = Path("products/views.py")

if not TARGET.exists():
    raise SystemExit(
        "ERROR: products/views.py was not found. "
        "Run this script from the Django project root."
    )

source = TARGET.read_text(encoding="utf-8")
original = source


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly 1 match, found {count}. "
            "No changes written."
        )
    return text.replace(old, new, 1)


def replace_function_block(text, function_name, replacement):
    """Replace a top-level function block, including contiguous decorators."""
    def_match = re.search(
        rf"(?m)^def {re.escape(function_name)}\s*\(",
        text,
    )
    if not def_match:
        raise RuntimeError(f"Function {function_name}() not found.")

    start = def_match.start()
    line_start = text.rfind("\n", 0, start) + 1
    cursor = line_start

    while True:
        prev_line_end = cursor - 1
        if prev_line_end <= 0:
            break
        prev_line_start = text.rfind("\n", 0, prev_line_end) + 1
        prev_line = text[prev_line_start:prev_line_end].strip()
        if prev_line.startswith("@"):
            start = prev_line_start
            cursor = prev_line_start
            continue
        break

    after_def = def_match.end()
    next_match = re.search(
        r"(?m)^(?=@[A-Za-z_]|def [A-Za-z_]|# ================================)",
        text[after_def:],
    )

    end = len(text) if not next_match else after_def + next_match.start()

    return (
        text[:start]
        + replacement.rstrip()
        + "\n\n\n"
        + text[end:].lstrip("\n")
    )


# ---------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------

if "from django.core.exceptions import ValidationError" not in source:
    source = replace_once(
        source,
        "from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger\n",
        "from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger\n"
        "from django.core.exceptions import ValidationError\n",
        "ValidationError import",
    )

if "from django.db import IntegrityError, transaction" not in source:
    source = replace_once(
        source,
        "from django.db import transaction\n",
        "from django.db import IntegrityError, transaction\n",
        "IntegrityError import",
    )


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

HELPERS = r'''
def _first_validation_error(error, default="The submitted information is invalid."):
    """Convert Django ValidationError structures to one safe message."""
    if hasattr(error, "message_dict"):
        for field_name, field_errors in error.message_dict.items():
            if not field_errors:
                continue

            first_error = field_errors[0]

            if field_name == "video_review":
                return str(first_error)

            label = str(field_name).replace("_", " ").title()
            return f"{label}: {first_error}"

    if getattr(error, "messages", None):
        return str(error.messages[0])

    return str(error) or default


def _review_video_url(review):
    """Return the configured protected media URL for a review video."""
    if not review or not review.video_review:
        return ""

    try:
        return review.video_review.url
    except Exception:
        return ""


def _refresh_product_review_stats(product_id):
    """Recalculate rating aggregates without invoking Product.save()."""
    review_stats = ProductReview.objects.filter(
        product_id=product_id,
    ).aggregate(
        average=Avg("rating"),
        total=Count("id"),
    )

    average = Decimal(str(review_stats["average"] or 0))
    total = int(review_stats["total"] or 0)

    Product.objects.filter(
        pk=product_id,
    ).update(
        rating_avg=average,
        rating_count=total,
    )
'''.strip()

if "def _first_validation_error(" not in source:
    marker = "# ================================\n# 🔥 REVIEW VIEWS\n# ================================"
    if marker not in source:
        raise RuntimeError("Review section marker not found. No changes written.")
    source = source.replace(marker, HELPERS + "\n\n\n" + marker, 1)


# ---------------------------------------------------------------------
# add_review()
# ---------------------------------------------------------------------

ADD_REVIEW = r'''
@login_required
@require_http_methods(["POST"])
@transaction.atomic
def add_review(request, slug):
    """Add a web product review with optional validated video evidence."""
    product = get_object_or_404(
        Product,
        slug=slug,
        is_active=True,
        approval_status="approved",
    )

    if ProductReview.objects.filter(
        product=product,
        user=request.user,
    ).exists():
        messages.warning(request, "You have already reviewed this product.")
        return redirect("products:detail", slug=product.slug)

    try:
        rating = int(request.POST.get("rating", 3))
    except (TypeError, ValueError):
        messages.error(request, "Please select a valid rating between 1 and 5.")
        return redirect("products:detail", slug=product.slug)

    if rating not in {1, 2, 3, 4, 5}:
        messages.error(request, "Please select a valid rating between 1 and 5.")
        return redirect("products:detail", slug=product.slug)

    title = str(request.POST.get("title", "")).strip()
    review_text = str(request.POST.get("review", "")).strip()

    if not title or not review_text:
        messages.error(request, "Title and review are required.")
        return redirect("products:detail", slug=product.slug)

    if len(title) < 5:
        messages.error(request, "Title must be at least 5 characters.")
        return redirect("products:detail", slug=product.slug)

    if len(title) > 200:
        messages.error(request, "Review title cannot exceed 200 characters.")
        return redirect("products:detail", slug=product.slug)

    if len(review_text) < 20:
        messages.error(request, "Review must be at least 20 characters.")
        return redirect("products:detail", slug=product.slug)

    uploaded_video = request.FILES.get("video_review")

    review = ProductReview(
        product=product,
        user=request.user,
        rating=rating,
        title=title,
        review=review_text,
        verified_purchase=False,
    )

    if uploaded_video:
        review.video_review = uploaded_video

    try:
        review.full_clean()
        review.save()

    except ValidationError as error:
        messages.error(
            request,
            _first_validation_error(
                error,
                default="The review could not be submitted.",
            ),
        )
        transaction.set_rollback(True)
        return redirect("products:detail", slug=product.slug)

    except IntegrityError:
        messages.warning(request, "You have already reviewed this product.")
        transaction.set_rollback(True)
        return redirect("products:detail", slug=product.slug)

    _refresh_product_review_stats(product.id)

    messages.success(request, "Review added successfully!")
    return redirect("products:detail", slug=product.slug)
'''.strip()

source = replace_function_block(source, "add_review", ADD_REVIEW)


# ---------------------------------------------------------------------
# answer_question()
# ---------------------------------------------------------------------

ANSWER_QUESTION = r'''
@login_required
@require_http_methods(["POST"])
def answer_question(request, qna_id):
    """Answer a product question as the product vendor or staff."""
    qna = get_object_or_404(
        ProductQuestion.objects.select_related(
            "product",
            "product__vendor",
        ),
        id=qna_id,
    )

    is_product_vendor = request.user_id == qna.product.vendor_id

    if not (is_product_vendor or request.user.is_staff):
        return JsonResponse(
            {
                "success": False,
                "error": "You do not have permission.",
            },
            status=403,
        )

    answer_text = str(request.POST.get("answer", "")).strip()

    if not answer_text:
        messages.error(request, "Please enter an answer.")
        return redirect("products:detail", slug=qna.product.slug)

    if len(answer_text) < 10:
        messages.error(request, "Answer must be at least 10 characters.")
        return redirect("products:detail", slug=qna.product.slug)

    qna.answer = answer_text
    qna.answered_by = request.user
    qna.answered_at = timezone.now()

    qna.save(
        update_fields=[
            "answer",
            "answered_by",
            "answered_at",
            "updated_at",
        ]
    )

    messages.success(request, "Answer posted successfully!")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "success": True,
                "answer": answer_text,
                "answered_by": (
                    request.user.get_full_name()
                    or request.user.username
                ),
                "answered_at": qna.answered_at.strftime(
                    "%b %d, %Y at %I:%M %p"
                ),
            }
        )

    return redirect("products:detail", slug=qna.product.slug)
'''.strip()

source = replace_function_block(source, "answer_question", ANSWER_QUESTION)


# ---------------------------------------------------------------------
# edit_answer()
# ---------------------------------------------------------------------

EDIT_ANSWER = r'''
@login_required
@require_http_methods(["POST"])
def edit_answer(request, qna_id):
    """Edit an answer as the product vendor or staff."""
    qna = get_object_or_404(
        ProductQuestion.objects.select_related(
            "product",
            "product__vendor",
        ),
        id=qna_id,
    )

    is_product_vendor = request.user_id == qna.product.vendor_id

    if not (is_product_vendor or request.user.is_staff):
        return JsonResponse(
            {
                "success": False,
                "error": "Permission denied.",
            },
            status=403,
        )

    answer_text = str(request.POST.get("answer", "")).strip()

    if not answer_text or len(answer_text) < 10:
        messages.error(request, "Answer must be at least 10 characters.")
        return redirect("products:detail", slug=qna.product.slug)

    qna.answer = answer_text
    qna.answered_by = request.user
    qna.answered_at = timezone.now()

    qna.save(
        update_fields=[
            "answer",
            "answered_by",
            "answered_at",
            "updated_at",
        ]
    )

    messages.success(request, "Answer updated successfully!")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "success": True,
                "answer": answer_text,
                "answered_by": (
                    request.user.get_full_name()
                    or request.user.username
                ),
                "answered_at": qna.answered_at.strftime(
                    "%b %d, %Y at %I:%M %p"
                ),
            }
        )

    return redirect("products:detail", slug=qna.product.slug)
'''.strip()

source = replace_function_block(source, "edit_answer", EDIT_ANSWER)


# ---------------------------------------------------------------------
# mobile_product_review_api()
# ---------------------------------------------------------------------

MOBILE_REVIEW = r'''
@csrf_exempt
@require_http_methods(["POST"])
@transaction.atomic
def mobile_product_review_api(request, slug):
    """
    Create or update a mobile customer product review.

    Supports JSON for text reviews and multipart/form-data for optional
    video_review uploads.
    """
    if _auth_mobile_customer_from_request_data is None:
        return JsonResponse(
            {
                "success": False,
                "message": "Mobile customer app is not available.",
            },
            status=500,
        )

    content_type = str(request.content_type or "").lower()

    if content_type.startswith("multipart/form-data"):
        payload = request.POST.dict()
    else:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse(
                {
                    "success": False,
                    "message": "Invalid JSON payload.",
                },
                status=400,
            )

        if not isinstance(payload, dict):
            return JsonResponse(
                {
                    "success": False,
                    "message": "Invalid request payload.",
                },
                status=400,
            )

    try:
        customer = _auth_mobile_customer_from_request_data(payload)

    except PermissionError as error:
        return JsonResponse(
            {
                "success": False,
                "message": str(error),
            },
            status=403,
        )

    except ValueError as error:
        return JsonResponse(
            {
                "success": False,
                "message": str(error),
            },
            status=400,
        )

    product = get_object_or_404(
        Product,
        slug=slug,
        is_active=True,
        approval_status="approved",
    )

    user = getattr(customer, "user", None)

    if not user:
        return JsonResponse(
            {
                "success": False,
                "message": "Customer account is not linked to a user yet.",
            },
            status=400,
        )

    try:
        rating = int(payload.get("rating") or 5)
    except (TypeError, ValueError):
        return JsonResponse(
            {
                "success": False,
                "message": "Rating must be between 1 and 5.",
            },
            status=400,
        )

    if rating not in {1, 2, 3, 4, 5}:
        return JsonResponse(
            {
                "success": False,
                "message": "Rating must be between 1 and 5.",
            },
            status=400,
        )

    title = str(payload.get("title") or "").strip()
    review_text = str(
        payload.get("review")
        or payload.get("message")
        or ""
    ).strip()

    if len(title) < 3:
        return JsonResponse(
            {
                "success": False,
                "message": "Please add a short review title.",
            },
            status=400,
        )

    if len(title) > 200:
        return JsonResponse(
            {
                "success": False,
                "message": "Review title cannot exceed 200 characters.",
            },
            status=400,
        )

    if len(review_text) < 10:
        return JsonResponse(
            {
                "success": False,
                "message": "Please write a little more about the product.",
            },
            status=400,
        )

    uploaded_video = request.FILES.get("video_review")

    review = (
        ProductReview.objects
        .select_for_update()
        .filter(
            product=product,
            user=user,
        )
        .first()
    )

    created = review is None

    if review is None:
        review = ProductReview(
            product=product,
            user=user,
            verified_purchase=False,
        )

    review.rating = rating
    review.title = title
    review.review = review_text

    if uploaded_video:
        if review.pk and review.video_review:
            return JsonResponse(
                {
                    "success": False,
                    "message": (
                        "The original review video cannot be replaced. "
                        "Please contact Arolana support if the original "
                        "upload was incorrect."
                    ),
                },
                status=400,
            )

        review.video_review = uploaded_video

    try:
        review.full_clean()
        review.save()

    except ValidationError as error:
        transaction.set_rollback(True)

        return JsonResponse(
            {
                "success": False,
                "message": _first_validation_error(
                    error,
                    default="The review could not be saved.",
                ),
            },
            status=400,
        )

    except IntegrityError:
        transaction.set_rollback(True)

        return JsonResponse(
            {
                "success": False,
                "message": (
                    "A review for this product already exists. "
                    "Refresh the product page and try again."
                ),
            },
            status=409,
        )

    _refresh_product_review_stats(product.id)

    return JsonResponse(
        {
            "success": True,
            "created": created,
            "message": (
                "Review submitted successfully."
                if created
                else "Review updated successfully."
            ),
            "review": {
                "id": review.id,
                "rating": review.rating,
                "title": review.title,
                "review": review.review,
                "customer_name": (
                    getattr(customer, "full_name", "")
                    or user.get_full_name()
                    or user.username
                    or "Arolana customer"
                ),
                "verified_purchase": review.verified_purchase,
                "has_video": bool(review.video_review),
                "video_url": _review_video_url(review),
            },
        },
        status=201 if created else 200,
    )
'''.strip()

source = replace_function_block(
    source,
    "mobile_product_review_api",
    MOBILE_REVIEW,
)


# ---------------------------------------------------------------------
# Final safety checks
# ---------------------------------------------------------------------

required_fragments = [
    "from django.core.exceptions import ValidationError",
    "from django.db import IntegrityError, transaction",
    "def _first_validation_error(",
    "def _refresh_product_review_stats(",
    "review.full_clean()",
    "select_for_update()",
    "request.user_id == qna.product.vendor_id",
]

for fragment in required_fragments:
    if fragment not in source:
        raise RuntimeError(
            f"Safety verification failed: missing {fragment!r}. "
            "No changes written."
        )

if source == original:
    raise RuntimeError("No changes were made. No file written.")

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"views.py.backup_{timestamp}")

backup.write_text(original, encoding="utf-8")
TARGET.write_text(source, encoding="utf-8")

print("SUCCESS")
print(f"Updated: {TARGET}")
print(f"Backup:  {backup}")
print()
print("Next commands:")
print("  python manage.py check")
print("  python manage.py test_private_upload_validation")
print("  python manage.py audit_private_media_authorization --fail-on-error")
