import json
from decimal import Decimal

from django.db.models import Count, F, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from mobile_customers.models import MobileCustomer
from orders.models import OrderItem
from products.models import Product

from .models import PriceAlert, ProductInteraction


def _clean_phone(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit() or ch == "+").strip()


def _clean_text(value):
    return str(value or "").strip()


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _auth_customer(data):
    phone_number = _clean_phone(data.get("phone") or data.get("phone_number") or data.get("phoneNumber"))
    api_token = _clean_text(data.get("api_token") or data.get("apiToken"))

    if not phone_number:
        raise ValueError("Phone number is required.")
    if not api_token:
        raise PermissionError("Login token is required.")

    customer = MobileCustomer.objects.filter(phone_number=phone_number, api_token=api_token, is_active=True).first()
    if not customer:
        raise PermissionError("Invalid login token. Login/register again.")
    return customer


def _product_price(product):
    for field_name in ["price", "sale_price", "current_price", "amount", "final_price"]:
        value = getattr(product, field_name, None)
        if value not in [None, ""]:
            return value
    return 0


def _product_image_url(request, product):
    for field_name in ["image", "main_image", "thumbnail", "photo", "featured_image", "product_image"]:
        image = getattr(product, field_name, None)
        if image:
            try:
                return request.build_absolute_uri(image.url)
            except Exception:
                return str(image)
    try:
        first_image = product.images.first()
        if first_image:
            image = getattr(first_image, "image", None)
            if image:
                return request.build_absolute_uri(image.url)
    except Exception:
        pass
    return ""


def _product_payload(request, product):
    category = getattr(product, "category", None)
    brand = getattr(product, "brand", None)
    return {
        "id": product.id,
        "name": getattr(product, "name", "") or getattr(product, "title", ""),
        "title": getattr(product, "name", "") or getattr(product, "title", ""),
        "slug": getattr(product, "slug", ""),
        "price": str(_product_price(product)),
        "category": getattr(category, "name", "") if category else "",
        "brand": getattr(brand, "name", "") if brand else "",
        "image": _product_image_url(request, product),
        "main_image": _product_image_url(request, product),
        "rating_avg": str(getattr(product, "rating_avg", "0") or "0"),
        "rating_count": getattr(product, "rating_count", 0),
        "sales_count": getattr(product, "sales_count", 0),
        "views_count": getattr(product, "views_count", 0),
        "is_featured": bool(getattr(product, "is_featured", False)),
        "is_new": bool(getattr(product, "is_new", False)),
        "is_bestseller": bool(getattr(product, "is_bestseller", False)),
    }


def _find_product(data):
    product_id = data.get("product_id") or data.get("id")
    slug = _clean_text(data.get("slug"))

    if product_id:
        return Product.objects.filter(id=product_id).first()
    if slug:
        return Product.objects.filter(slug=slug).first()
    return None


def _decimal(value, fallback=0):
    try:
        return Decimal(str(value or fallback).replace(",", "")).quantize(Decimal("0.01"))
    except Exception:
        return Decimal(str(fallback)).quantize(Decimal("0.01"))


def _active_products():
    return Product.objects.filter(
        is_active=True,
        approval_status="approved",
    ).select_related("category", "brand", "vendor")


def _add_score(scores, product_id, amount, reason=""):
    if not product_id:
        return
    entry = scores.setdefault(product_id, {"score": 0, "reasons": set()})
    entry["score"] += int(amount)
    if reason:
        entry["reasons"].add(reason)


def _order_product_ids_for_customer(customer):
    return list(
        OrderItem.objects.filter(order__user=customer.user, product_id__isnull=False)
        .exclude(order__status__in=["cancelled", "refunded"])
        .values_list("product_id", flat=True)
        .distinct()[:80]
    )


def _ranked_products_from_scores(request, scores, limit=24):
    if not scores:
        return []

    ids = list(scores.keys())
    products = {
        product.id: product
        for product in _active_products().filter(id__in=ids)
    }

    ranked = []
    for product_id, meta in scores.items():
        product = products.get(product_id)
        if not product:
            continue

        quality_score = 0
        if getattr(product, "is_bestseller", False):
            quality_score += 12
        if getattr(product, "is_featured", False):
            quality_score += 8
        if getattr(product, "is_new", False):
            quality_score += 5
        quality_score += min(int(getattr(product, "sales_count", 0) or 0), 80) // 4
        quality_score += min(int(getattr(product, "views_count", 0) or 0), 200) // 20
        try:
            quality_score += int(Decimal(str(getattr(product, "rating_avg", 0) or 0)) * 3)
        except Exception:
            pass

        ranked.append((meta["score"] + quality_score, product, meta["reasons"]))

    ranked.sort(key=lambda item: (item[0], getattr(item[1], "created_at", None)), reverse=True)

    payloads = []
    seen = set()
    for score, product, reasons in ranked:
        if product.id in seen:
            continue
        payload = _product_payload(request, product)
        payload["recommendation_score"] = score
        payload["recommendation_reasons"] = sorted(reasons)
        payloads.append(payload)
        seen.add(product.id)
        if len(payloads) >= limit:
            break
    return payloads


def _build_recommendation_scores(customer):
    scores = {}

    interactions = list(
        customer.product_interactions.select_related("product", "product__category", "product__brand", "product__vendor")
        .filter(product__is_active=True, product__approval_status="approved")
        .order_by("-last_viewed_at")[:80]
    )
    wishlist_product_ids = list(customer.wishlist_items.values_list("product_id", flat=True)[:80])
    alert_product_ids = list(customer.price_alerts.filter(is_active=True).values_list("product_id", flat=True)[:80])
    order_product_ids = _order_product_ids_for_customer(customer)

    seed_ids = []
    seed_category_ids = []
    seed_brand_ids = []
    seed_vendor_ids = []

    for index, interaction in enumerate(interactions):
        product = interaction.product
        recency_boost = max(0, 30 - index)
        view_boost = min(int(interaction.view_count or 1), 20) * 8
        _add_score(scores, product.id, 34 + view_boost + recency_boost, "frequently_viewed")
        seed_ids.append(product.id)
        if product.category_id:
            seed_category_ids.append(product.category_id)
        if product.brand_id:
            seed_brand_ids.append(product.brand_id)
        if product.vendor_id:
            seed_vendor_ids.append(product.vendor_id)

    for product_id in wishlist_product_ids:
        _add_score(scores, product_id, 45, "wishlist")
        seed_ids.append(product_id)

    for product_id in alert_product_ids:
        _add_score(scores, product_id, 36, "price_alert")
        seed_ids.append(product_id)

    for product_id in order_product_ids:
        _add_score(scores, product_id, 48, "previous_order")
        seed_ids.append(product_id)

    seed_products = _active_products().filter(id__in=list(dict.fromkeys(seed_ids)))
    for product in seed_products:
        if product.category_id:
            seed_category_ids.append(product.category_id)
        if product.brand_id:
            seed_brand_ids.append(product.brand_id)
        if product.vendor_id:
            seed_vendor_ids.append(product.vendor_id)

    for product in _active_products().filter(category_id__in=list(set(seed_category_ids))).exclude(id__in=seed_ids)[:160]:
        _add_score(scores, product.id, 28, "same_category")

    for product in _active_products().filter(brand_id__in=list(set(seed_brand_ids))).exclude(id__in=seed_ids)[:120]:
        _add_score(scores, product.id, 22, "same_brand")

    for product in _active_products().filter(vendor_id__in=list(set(seed_vendor_ids))).exclude(id__in=seed_ids)[:80]:
        _add_score(scores, product.id, 14, "same_supplier")

    if seed_ids:
        order_ids = (
            OrderItem.objects.filter(product_id__in=seed_ids)
            .exclude(order__status__in=["cancelled", "refunded"])
            .values_list("order_id", flat=True)
        )
        bought_together = (
            OrderItem.objects.filter(order_id__in=order_ids, product_id__isnull=False)
            .exclude(product_id__in=seed_ids)
            .values("product_id")
            .annotate(times=Count("id"))
            .order_by("-times")[:60]
        )
        for row in bought_together:
            _add_score(scores, row["product_id"], 42 + int(row["times"] or 0) * 5, "frequently_bought_together")

    if len(scores) < 24:
        for product in _active_products().order_by("-is_bestseller", "-is_featured", "-sales_count", "-rating_avg", "-created_at")[:80]:
            _add_score(scores, product.id, 8, "popular")

    return scores


@csrf_exempt
@require_POST
def mobile_product_view_api(request):
    data = _json_body(request)

    try:
        customer = _auth_customer(data)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    product = _find_product(data)
    if not product:
        return JsonResponse({"success": False, "message": "Product not found."}, status=404)

    interaction, _created = ProductInteraction.objects.get_or_create(
        customer=customer,
        product=product,
        defaults={"view_count": 0, "last_viewed_at": timezone.now()},
    )
    ProductInteraction.objects.filter(pk=interaction.pk).update(
        view_count=F("view_count") + 1,
        last_viewed_at=timezone.now(),
        updated_at=timezone.now(),
    )

    try:
        Product.objects.filter(pk=product.pk).update(views_count=F("views_count") + 1)
    except Exception:
        pass

    try:
        from products.models import RecentlyViewed

        RecentlyViewed.objects.update_or_create(
            user=customer.user,
            product=product,
            defaults={"viewed_at": timezone.now()},
        )
    except Exception:
        pass

    interaction.refresh_from_db()
    return JsonResponse({
        "success": True,
        "message": "Product view saved.",
        "view_count": interaction.view_count,
        "product": _product_payload(request, product),
    })


@require_GET
def mobile_product_history_api(request):
    try:
        customer = _auth_customer(request.GET)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    history = []
    interactions = (
        customer.product_interactions.select_related("product", "product__category", "product__brand")
        .filter(product__is_active=True, product__approval_status="approved")
        .order_by("-last_viewed_at")[:60]
    )
    for item in interactions:
        history.append({
            "historyId": str(item.product_id),
            "viewedAt": item.last_viewed_at.isoformat() if item.last_viewed_at else "",
            "view_count": item.view_count,
            "product": _product_payload(request, item.product),
        })

    return JsonResponse({"success": True, "history": history, "count": len(history)})


@require_GET
def mobile_recommendations_api(request):
    try:
        customer = _auth_customer(request.GET)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    scores = _build_recommendation_scores(customer)
    products = _ranked_products_from_scores(request, scores, limit=32)

    recently_viewed = []
    frequently_viewed = []
    for interaction in customer.product_interactions.select_related("product", "product__category", "product__brand").filter(
        product__is_active=True,
        product__approval_status="approved",
    ).order_by("-last_viewed_at")[:12]:
        recently_viewed.append(_product_payload(request, interaction.product))

    for interaction in customer.product_interactions.select_related("product", "product__category", "product__brand").filter(
        product__is_active=True,
        product__approval_status="approved",
    ).order_by("-view_count", "-last_viewed_at")[:12]:
        payload = _product_payload(request, interaction.product)
        payload["view_count"] = interaction.view_count
        frequently_viewed.append(payload)

    return JsonResponse({
        "success": True,
        "products": products,
        "recommendations": products,
        "recently_viewed": recently_viewed,
        "frequently_viewed": frequently_viewed,
    })


@require_GET
def mobile_price_alerts_api(request):
    try:
        customer = _auth_customer(request.GET)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    alerts = []
    for alert in customer.price_alerts.select_related("product").filter(is_active=True):
        alerts.append({
            "id": alert.id,
            "alert_id": alert.id,
            "target_price": str(alert.target_price or ""),
            "current_price": str(_product_price(alert.product)),
            "last_seen_price": str(alert.last_seen_price or ""),
            "triggered_at": alert.triggered_at.isoformat() if alert.triggered_at else "",
            "product": _product_payload(request, alert.product),
        })

    return JsonResponse({"success": True, "alerts": alerts, "count": len(alerts)})


@csrf_exempt
@require_POST
def mobile_price_alert_create_api(request):
    data = _json_body(request)

    try:
        customer = _auth_customer(data)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    product = _find_product(data)
    if not product:
        return JsonResponse({"success": False, "message": "Product not found."}, status=404)

    current_price = _decimal(_product_price(product))
    target_price = _decimal(data.get("target_price") or current_price)

    alert, _created = PriceAlert.objects.update_or_create(
        customer=customer,
        product=product,
        defaults={
            "target_price": target_price,
            "last_seen_price": current_price,
            "is_active": True,
        },
    )

    return JsonResponse({
        "success": True,
        "message": "Price alert saved.",
        "alert": {
            "id": alert.id,
            "target_price": str(alert.target_price),
            "current_price": str(current_price),
            "product": _product_payload(request, product),
        },
    })


@csrf_exempt
@require_POST
def mobile_price_alert_delete_api(request):
    data = _json_body(request)

    try:
        customer = _auth_customer(data)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    alert_id = data.get("alert_id") or data.get("id")
    deleted, _details = PriceAlert.objects.filter(customer=customer, id=alert_id).delete()

    return JsonResponse({"success": True, "message": "Price alert removed.", "deleted": deleted})
