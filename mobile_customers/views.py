import json
import secrets

from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from accounts.utils.otp_utils import create_otp, verify_otp
from products.models import Product
from .models import MobileCustomer, MobileWishlistItem


# -------------------------------------------------------------------
# Shared helpers
# -------------------------------------------------------------------

def _clean_phone(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit() or ch == "+").strip()


def _clean_pin(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:6]


def _clean_text(value):
    return str(value or "").strip()


def _json_payload(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return None


def _json_error(message, status=400):
    return JsonResponse(
        {
            "success": False,
            "message": str(message),
            "error": str(message),
        },
        status=status,
    )


def _save_model(instance, fields):
    fields = [field for field in set(fields or []) if field]

    if hasattr(instance, "updated_at") and fields and "updated_at" not in fields:
        fields.append("updated_at")

    if fields:
        instance.save(update_fields=fields)
    else:
        instance.save()


def _split_name(full_name):
    parts = _clean_text(full_name).split()
    first_name = parts[0] if parts else ""
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
    return first_name, last_name


def _user_field_names(User):
    return {field.name for field in User._meta.fields}


def _find_existing_user(User, phone_number="", email=""):
    fields = _user_field_names(User)
    username_field = getattr(User, "USERNAME_FIELD", "username")
    mobile_username = f"mobile_{phone_number}"

    if email and "email" in fields:
        user = User.objects.filter(email__iexact=email).first()
        if user:
            return user

    if username_field in fields:
        user = User.objects.filter(**{username_field: mobile_username}).first()
        if user:
            return user

    if "username" in fields:
        user = User.objects.filter(username=mobile_username).first()
        if user:
            return user

    return None


def _safe_set_user_email(User, user, email):
    if not email or "email" not in _user_field_names(User):
        return False

    existing_email_user = (
        User.objects.filter(email__iexact=email)
        .exclude(pk=user.pk)
        .first()
    )

    if existing_email_user:
        return False

    if getattr(user, "email", "") != email:
        user.email = email
        return True

    return False


def _safe_set_username(User, user, phone_number):
    fields = _user_field_names(User)
    username_field = getattr(User, "USERNAME_FIELD", "username")
    mobile_username = f"mobile_{phone_number}"

    if username_field in fields and not getattr(user, username_field, ""):
        setattr(user, username_field, mobile_username)
        return True

    if "username" in fields and not getattr(user, "username", ""):
        user.username = mobile_username
        return True

    return False


def _product_image_url(request, product):
    for field_name in [
        "image",
        "main_image",
        "thumbnail",
        "photo",
        "featured_image",
        "product_image",
    ]:
        image = getattr(product, field_name, None)
        if image:
            try:
                return request.build_absolute_uri(image.url)
            except Exception:
                return str(image)

    try:
        first_image = product.images.first()
        if first_image:
            for attr in ["image", "url", "file", "photo"]:
                image = getattr(first_image, attr, None)
                if image:
                    try:
                        return request.build_absolute_uri(image.url)
                    except Exception:
                        return str(image)
    except Exception:
        pass

    return ""


def _product_category(product):
    category = getattr(product, "category", None)
    if category:
        return getattr(category, "name", None) or str(category)

    return getattr(product, "category_name", "") or "Arolana"


def _product_price(product):
    for field_name in ["price", "sale_price", "current_price", "amount", "final_price"]:
        value = getattr(product, field_name, None)
        if value not in [None, ""]:
            return value

    return ""


def _product_payload(request, product):
    title = getattr(product, "name", "") or getattr(product, "title", "")
    image_url = _product_image_url(request, product)

    return {
        "id": product.id,
        "name": title,
        "title": title,
        "slug": getattr(product, "slug", ""),
        "price": str(_product_price(product)),
        "category": _product_category(product),
        "category_name": _product_category(product),
        "image": image_url,
        "main_image": image_url,
    }


def _wishlist_payload(request, customer):
    items = []
    wishlist_items = (
        customer.wishlist_items.select_related("product", "product__category")
        .order_by("-created_at")
    )

    for item in wishlist_items:
        items.append(
            {
                "wishlist_id": item.id,
                "created_at": item.created_at.isoformat() if item.created_at else "",
                "product": _product_payload(request, item.product),
            }
        )

    return items


def _customer_payload(customer):
    return {
        "id": customer.id,
        "full_name": customer.full_name,
        "phone_number": customer.phone_number,
        "email": customer.email,
        "user_id": customer.user_id,
        "api_token": customer.api_token,
        "preferred_language": customer.preferred_language,
        "notification_preferences": customer.notification_preferences,
    }


CUSTOMER_LOGIN_CHALLENGE_SALT = "arolana.mobile-customer.login"
CUSTOMER_LOGIN_CHALLENGE_MAX_AGE = 10 * 60


def _clean_identifier(value):
    value = _clean_text(value)
    return value.lower() if "@" in value else value


def _authenticate_customer_user(request, identifier, password):
    User = get_user_model()
    identifier = _clean_identifier(identifier)
    candidates = []

    direct_user = authenticate(request, username=identifier, password=password)
    if direct_user:
        candidates.append(direct_user)

    lookup = Q(email__iexact=identifier) | Q(username__iexact=identifier)
    phone = _clean_phone(identifier)
    if phone:
        lookup |= Q(phone_number=phone)

    for user in User.objects.filter(lookup, is_active=True):
        if user not in candidates:
            candidates.append(user)

    for user in candidates:
        for username in [getattr(user, "email", ""), getattr(user, "username", "")]:
            if username:
                auth_user = authenticate(request, username=username, password=password)
                if auth_user:
                    return auth_user
        if user.check_password(password):
            return user
    return None


def _customer_login_challenge(user, phone_number, otp_type):
    return signing.dumps(
        {
            "user_id": user.id,
            "phone_number": _clean_phone(phone_number),
            "otp_type": otp_type,
        },
        salt=CUSTOMER_LOGIN_CHALLENGE_SALT,
        compress=True,
    )


def _load_customer_login_challenge(token):
    return signing.loads(
        token,
        salt=CUSTOMER_LOGIN_CHALLENGE_SALT,
        max_age=CUSTOMER_LOGIN_CHALLENGE_MAX_AGE,
    )


def _mask_email(email):
    value = _clean_text(email).lower()
    if "@" not in value:
        return "your registered email"
    local, domain = value.split("@", 1)
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(2, len(local) - len(visible))}@{domain}"


@transaction.atomic
def _mobile_customer_for_web_user(user, supplied_phone=""):
    customer = MobileCustomer.objects.filter(user=user).first()
    phone_number = (
        getattr(customer, "phone_number", "")
        or _clean_phone(getattr(user, "phone_number", ""))
        or _clean_phone(supplied_phone)
    )
    if not phone_number:
        raise ValueError(
            "Add a phone number to your Arolana web account or enter it here to finish mobile login."
        )

    phone_owner = MobileCustomer.objects.filter(phone_number=phone_number).exclude(user=user).first()
    if phone_owner:
        raise PermissionError(
            "This phone number is linked to another Arolana account. Contact Arolana support."
        )

    if not customer:
        customer = MobileCustomer(user=user, phone_number=phone_number)
    elif customer.phone_number != phone_number:
        customer.phone_number = phone_number

    full_name = user.get_full_name() or getattr(user, "username", "") or user.email
    customer.full_name = full_name
    customer.email = _clean_text(getattr(user, "email", "")).lower()
    customer.ensure_api_token()
    customer.last_login_at = timezone.now()
    customer.save()
    return customer


# -------------------------------------------------------------------
# Customer login / profile
# -------------------------------------------------------------------

@transaction.atomic
def _get_or_create_mobile_customer(
    full_name="",
    phone_number="",
    email="",
    pin="",
    api_token="",
):
    phone_number = _clean_phone(phone_number)
    email = _clean_text(email).lower()
    full_name = _clean_text(full_name)
    pin = _clean_pin(pin)
    api_token = _clean_text(api_token)

    if not phone_number:
        raise ValueError("Phone number is required.")

    User = get_user_model()
    first_name, last_name = _split_name(full_name)

    customer = (
        MobileCustomer.objects.filter(phone_number=phone_number)
        .select_related("user")
        .first()
    )

    if customer:
        if api_token and customer.api_token and api_token == customer.api_token:
            pass
        elif getattr(customer, "pin_hash", ""):
            if not pin:
                raise PermissionError("PIN is required.")
            if not customer.check_pin(pin):
                raise PermissionError("Incorrect PIN.")
        else:
            if len(pin) < 4:
                raise ValueError("Create a 4 to 6 digit PIN.")
            customer.set_pin(pin)
    else:
        if len(pin) < 4:
            raise ValueError("Create a 4 to 6 digit PIN.")

        user = _find_existing_user(User, phone_number=phone_number, email=email)

        if not user:
            user = User()
            _safe_set_username(User, user, phone_number)

            if hasattr(user, "set_unusable_password"):
                user.set_unusable_password()

        changed = False

        if _safe_set_username(User, user, phone_number):
            changed = True

        if _safe_set_user_email(User, user, email):
            changed = True

        if first_name and hasattr(user, "first_name") and getattr(user, "first_name", "") != first_name:
            user.first_name = first_name
            changed = True

        if hasattr(user, "last_name") and getattr(user, "last_name", "") != last_name:
            user.last_name = last_name
            changed = True

        username_field = getattr(User, "USERNAME_FIELD", "username")
        fields = _user_field_names(User)

        if username_field == "email" and "email" in fields and not getattr(user, "email", ""):
            user.email = email or f"mobile_{phone_number}@arolana.local"
            changed = True

        if user.pk is None or changed:
            user.save()

        existing_customer_for_user = MobileCustomer.objects.filter(user=user).first()

        if existing_customer_for_user:
            customer = existing_customer_for_user
            if customer.phone_number != phone_number:
                phone_taken = (
                    MobileCustomer.objects.filter(phone_number=phone_number)
                    .exclude(pk=customer.pk)
                    .exists()
                )
                if not phone_taken:
                    customer.phone_number = phone_number
        else:
            customer = MobileCustomer(user=user, phone_number=phone_number)

        customer.set_pin(pin)

    updated_fields = []

    if full_name and customer.full_name != full_name:
        customer.full_name = full_name
        updated_fields.append("full_name")

    if email and customer.email != email:
        customer.email = email
        updated_fields.append("email")

    customer.ensure_api_token()
    updated_fields.append("api_token")

    if getattr(customer, "pin_hash", ""):
        updated_fields.append("pin_hash")

    customer.last_login_at = timezone.now()
    updated_fields.append("last_login_at")

    if customer.pk is None:
        customer.save()
    elif updated_fields:
        _save_model(customer, updated_fields)

    return customer


def _auth_mobile_customer_from_request_data(data):
    phone_number = _clean_phone(
        data.get("phone_number") or data.get("phoneNumber") or data.get("phone")
    )
    api_token = _clean_text(data.get("api_token") or data.get("apiToken"))

    if not phone_number:
        raise ValueError("Phone number is required.")

    if not api_token:
        raise PermissionError("Login token is required. Login/register again.")

    customer = MobileCustomer.objects.filter(
        phone_number=phone_number,
        api_token=api_token,
    ).first()

    if not customer:
        raise PermissionError("Login expired or invalid. Login/register again.")

    return customer


@csrf_exempt
@require_POST
def mobile_customer_login_api(request):
    payload = _json_payload(request)

    if payload is None:
        return _json_error("Invalid JSON payload.", status=400)

    try:
        customer = _get_or_create_mobile_customer(
            full_name=payload.get("full_name") or payload.get("fullName") or "",
            phone_number=payload.get("phone_number") or payload.get("phoneNumber") or "",
            email=payload.get("email") or "",
            pin=payload.get("pin") or "",
            api_token=payload.get("api_token") or payload.get("apiToken") or "",
        )
    except PermissionError as error:
        return _json_error(error, status=403)
    except ValueError as error:
        return _json_error(error, status=400)
    except Exception as error:
        return _json_error(f"Could not login/register mobile customer: {error}", status=500)

    return JsonResponse(
        {
            "success": True,
            "message": "Customer logged in/registered successfully.",
            "customer": _customer_payload(customer),
            "api_token": customer.api_token,
            "wishlist_items": _wishlist_payload(request, customer),
        }
    )


@csrf_exempt
@require_POST
def mobile_customer_account_login_api(request):
    payload = _json_payload(request)
    if payload is None:
        return _json_error("Invalid JSON payload.")

    identifier = _clean_identifier(
        payload.get("identifier") or payload.get("email") or payload.get("phone") or payload.get("username")
    )
    password = str(payload.get("password") or "")
    phone_number = _clean_phone(payload.get("phone_number") or payload.get("phoneNumber"))
    if not identifier or not password:
        return _json_error("Email, phone, or username and password are required.")

    user = _authenticate_customer_user(request, identifier, password)
    if not user:
        return _json_error(
            "Invalid login details. Please check your email/phone and password.",
            status=403,
        )
    if not user.email:
        return _json_error(
            "This account has no email address for secure verification. Contact Arolana support.",
            status=403,
        )

    otp_type = "email" if not getattr(user, "email_verified", False) else "login"
    if not create_otp(user, user.email, otp_type):
        return _json_error(
            "We could not send your verification code. Please try again or contact Arolana support.",
            status=503,
        )

    return JsonResponse(
        {
            "success": True,
            "ok": True,
            "otp_required": True,
            "verification_type": otp_type,
            "challenge_token": _customer_login_challenge(user, phone_number, otp_type),
            "masked_email": _mask_email(user.email),
            "message": "Verification code sent to your email.",
        }
    )


@csrf_exempt
@require_POST
def mobile_customer_account_verify_otp_api(request):
    payload = _json_payload(request)
    if payload is None:
        return _json_error("Invalid JSON payload.")

    challenge_token = _clean_text(payload.get("challenge_token"))
    otp_code = _clean_text(payload.get("otp_code") or payload.get("code"))
    if not challenge_token or not otp_code:
        return _json_error("Challenge token and verification code are required.")

    try:
        challenge = _load_customer_login_challenge(challenge_token)
    except signing.SignatureExpired:
        return _json_error("Verification session expired. Please login again.", status=403)
    except signing.BadSignature:
        return _json_error("Invalid verification session. Please login again.", status=403)

    User = get_user_model()
    user = User.objects.filter(id=challenge.get("user_id"), is_active=True).first()
    if not user:
        return _json_error("Account is unavailable. Please login again.", status=403)

    otp_type = challenge.get("otp_type") or "login"
    success, message = verify_otp(user, otp_code, otp_type)
    if not success:
        return _json_error(message, status=403)

    if otp_type == "email" and not getattr(user, "email_verified", False):
        user.email_verified = True
        user.save(update_fields=["email_verified", "updated_at"])

    try:
        customer = _mobile_customer_for_web_user(user, challenge.get("phone_number", ""))
    except PermissionError as error:
        return _json_error(error, status=403)
    except ValueError as error:
        return _json_error(error)

    return JsonResponse(
        {
            "success": True,
            "ok": True,
            "otp_required": False,
            "message": "Arolana account verified successfully.",
            "customer": _customer_payload(customer),
            "api_token": customer.api_token,
            "wishlist_items": _wishlist_payload(request, customer),
        }
    )


@csrf_exempt
@require_POST
def mobile_customer_account_resend_otp_api(request):
    payload = _json_payload(request)
    challenge_token = _clean_text((payload or {}).get("challenge_token"))
    if not challenge_token:
        return _json_error("Verification session is required.")

    try:
        challenge = _load_customer_login_challenge(challenge_token)
    except signing.SignatureExpired:
        return _json_error("Verification session expired. Please login again.", status=403)
    except signing.BadSignature:
        return _json_error("Invalid verification session. Please login again.", status=403)

    User = get_user_model()
    user = User.objects.filter(id=challenge.get("user_id"), is_active=True).first()
    if not user or not user.email:
        return _json_error("Account is unavailable. Please login again.", status=403)

    otp_type = challenge.get("otp_type") or "login"
    if not create_otp(user, user.email, otp_type):
        return _json_error("We could not resend your verification code.", status=503)
    return JsonResponse(
        {
            "success": True,
            "ok": True,
            "otp_required": True,
            "message": "A new verification code was sent to your email.",
        }
    )


@require_GET
def mobile_customer_profile_api(request):
    try:
        customer = _auth_mobile_customer_from_request_data(request.GET)
    except PermissionError as error:
        return _json_error(error, status=403)
    except ValueError as error:
        return _json_error(error, status=400)

    return JsonResponse(
        {
            "success": True,
            "customer": _customer_payload(customer),
            "wishlist_items": _wishlist_payload(request, customer),
        }
    )


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def mobile_customer_settings_api(request):
    payload = request.GET if request.method == "GET" else _json_payload(request)
    if payload is None:
        return _json_error("Invalid JSON payload.")
    try:
        customer = _auth_mobile_customer_from_request_data(payload)
    except PermissionError as error:
        return _json_error(error, status=403)
    except ValueError as error:
        return _json_error(error)

    supported_languages = {"english", "pidgin", "yoruba", "igbo", "hausa", "french"}
    if request.method == "PATCH":
        preferred_language = _clean_text(payload.get("preferred_language")).lower()
        if preferred_language:
            if preferred_language not in supported_languages:
                return _json_error("Select a supported Arolana language.")
            customer.preferred_language = preferred_language
        preferences = payload.get("notification_preferences")
        if isinstance(preferences, dict):
            customer.notification_preferences = preferences
        customer.save(
            update_fields=[
                "preferred_language",
                "notification_preferences",
                "updated_at",
            ]
        )

    return JsonResponse(
        {
            "success": True,
            "preferred_language": customer.preferred_language,
            "notification_preferences": customer.notification_preferences,
            "supported_languages": sorted(supported_languages),
            "message": "Customer settings saved." if request.method == "PATCH" else "",
        }
    )


# -------------------------------------------------------------------
# Wishlist API
# -------------------------------------------------------------------

def _find_product(payload):
    product_id = payload.get("product_id") or payload.get("id")
    slug = _clean_text(payload.get("slug"))

    if product_id:
        try:
            return Product.objects.filter(id=product_id).first()
        except Exception:
            pass

    if slug:
        return Product.objects.filter(slug=slug).first()

    return None


@require_GET
def mobile_wishlist_list_api(request):
    try:
        customer = _auth_mobile_customer_from_request_data(request.GET)
    except PermissionError as error:
        return _json_error(error, status=403)
    except ValueError as error:
        return _json_error(error, status=400)

    wishlist_items = _wishlist_payload(request, customer)

    return JsonResponse(
        {
            "success": True,
            "wishlist_items": wishlist_items,
            "count": len(wishlist_items),
        }
    )


@csrf_exempt
@require_POST
def mobile_wishlist_sync_api(request):
    payload = _json_payload(request)

    if payload is None:
        return _json_error("Invalid JSON payload.", status=400)

    try:
        customer = _auth_mobile_customer_from_request_data(payload)
    except PermissionError as error:
        return _json_error(error, status=403)
    except ValueError as error:
        return _json_error(error, status=400)

    items = payload.get("items") or []
    clear_first = bool(payload.get("clear_first"))

    if clear_first:
        customer.wishlist_items.all().delete()

    for item in items:
        product = _find_product(item)
        if product:
            MobileWishlistItem.objects.get_or_create(customer=customer, product=product)

    wishlist_items = _wishlist_payload(request, customer)

    return JsonResponse(
        {
            "success": True,
            "message": "Wishlist synced successfully.",
            "customer": _customer_payload(customer),
            "wishlist_items": wishlist_items,
            "count": len(wishlist_items),
        }
    )


@csrf_exempt
@require_POST
def mobile_wishlist_toggle_api(request):
    payload = _json_payload(request)

    if payload is None:
        return _json_error("Invalid JSON payload.", status=400)

    try:
        customer = _auth_mobile_customer_from_request_data(payload)
    except PermissionError as error:
        return _json_error(error, status=403)
    except ValueError as error:
        return _json_error(error, status=400)

    product_payload = payload.get("product") or payload
    product = _find_product(product_payload)
    action = _clean_text(payload.get("action") or "toggle").lower()

    if not product:
        return _json_error("Product not found.", status=404)

    wishlist_item = MobileWishlistItem.objects.filter(
        customer=customer,
        product=product,
    ).first()

    if action == "add":
        MobileWishlistItem.objects.get_or_create(customer=customer, product=product)
        wishlisted = True
    elif action == "remove":
        if wishlist_item:
            wishlist_item.delete()
        wishlisted = False
    else:
        if wishlist_item:
            wishlist_item.delete()
            wishlisted = False
        else:
            MobileWishlistItem.objects.create(customer=customer, product=product)
            wishlisted = True

    wishlist_items = _wishlist_payload(request, customer)

    return JsonResponse(
        {
            "success": True,
            "message": "Wishlist updated.",
            "wishlisted": wishlisted,
            "customer": _customer_payload(customer),
            "wishlist_items": wishlist_items,
            "count": len(wishlist_items),
        }
    )


# -------------------------------------------------------------------
# Settings API
# -------------------------------------------------------------------

def _pin_field_name():
    for field_name in ["pin_hash", "hashed_pin", "pin_password", "pin"]:
        try:
            MobileCustomer._meta.get_field(field_name)
            return field_name
        except Exception:
            continue

    return None


def _customer_check_pin(customer, pin):
    pin = _clean_pin(pin)

    if not pin:
        return False

    if hasattr(customer, "check_pin"):
        try:
            return customer.check_pin(pin)
        except Exception:
            pass

    field_name = _pin_field_name()

    if not field_name:
        return True

    stored = getattr(customer, field_name, "") or ""

    if not stored:
        return True

    try:
        if check_password(str(pin), stored):
            return True
    except Exception:
        pass

    return str(pin) == str(stored)


def _customer_set_pin(customer, pin):
    pin = _clean_pin(pin)

    if len(pin) < 4:
        raise ValueError("PIN must be 4 to 6 digits.")

    if hasattr(customer, "set_pin"):
        customer.set_pin(pin)
        _save_model(customer, ["pin_hash"] if hasattr(customer, "pin_hash") else [])
        return

    field_name = _pin_field_name()

    if not field_name:
        raise RuntimeError("No PIN field found on MobileCustomer model.")

    setattr(customer, field_name, make_password(str(pin)))
    _save_model(customer, [field_name])


@csrf_exempt
@require_POST
def mobile_customer_update_api(request):
    payload = _json_payload(request)

    if payload is None:
        return _json_error("Invalid JSON payload.", status=400)

    try:
        customer = _auth_mobile_customer_from_request_data(payload)
    except PermissionError as error:
        return _json_error(error, status=403)
    except Exception as error:
        return _json_error(error, status=400)

    changed_fields = []

    full_name = _clean_text(payload.get("full_name") or payload.get("fullName"))
    phone_number = _clean_phone(
        payload.get("new_phone_number")
        or payload.get("newPhoneNumber")
        or payload.get("phone_number")
        or payload.get("phoneNumber")
    )
    email = _clean_text(payload.get("email")).lower()

    if full_name and hasattr(customer, "full_name") and customer.full_name != full_name:
        customer.full_name = full_name
        changed_fields.append("full_name")

    if phone_number and hasattr(customer, "phone_number") and customer.phone_number != phone_number:
        existing = (
            MobileCustomer.objects.filter(phone_number=phone_number)
            .exclude(id=customer.id)
            .exists()
        )
        if existing:
            return _json_error("This phone number is already used by another customer.", status=400)

        customer.phone_number = phone_number
        changed_fields.append("phone_number")

    if email and hasattr(customer, "email") and customer.email != email:
        existing = (
            MobileCustomer.objects.filter(email__iexact=email)
            .exclude(id=customer.id)
            .exists()
        )
        if existing:
            return _json_error("This email is already used by another customer.", status=400)

        customer.email = email
        changed_fields.append("email")

    if changed_fields:
        _save_model(customer, changed_fields)

    return JsonResponse(
        {
            "success": True,
            "message": "Customer profile updated.",
            "customer": _customer_payload(customer),
        }
    )


@csrf_exempt
@require_POST
def mobile_customer_change_pin_api(request):
    payload = _json_payload(request)

    if payload is None:
        return _json_error("Invalid JSON payload.", status=400)

    try:
        customer = _auth_mobile_customer_from_request_data(payload)
    except PermissionError as error:
        return _json_error(error, status=403)
    except Exception as error:
        return _json_error(error, status=400)

    old_pin = _clean_pin(payload.get("old_pin") or payload.get("oldPin"))
    new_pin = _clean_pin(payload.get("new_pin") or payload.get("newPin"))

    if len(new_pin) < 4:
        return _json_error("New PIN must be 4 to 6 digits.", status=400)

    if not old_pin:
        return _json_error("Current PIN is required.", status=400)

    if not _customer_check_pin(customer, old_pin):
        return _json_error("Current PIN is incorrect.", status=403)

    try:
        _customer_set_pin(customer, new_pin)
    except Exception as error:
        return _json_error(error, status=400)

    if hasattr(customer, "api_token"):
        customer.api_token = secrets.token_urlsafe(32)
        _save_model(customer, ["api_token"])

    return JsonResponse(
        {
            "success": True,
            "message": "PIN changed successfully. Please login again with your new PIN.",
            "customer": _customer_payload(customer),
            "api_token": customer.api_token,
        }
    )


@csrf_exempt
@require_POST
def mobile_customer_delete_api(request):
    payload = _json_payload(request)

    if payload is None:
        return _json_error("Invalid JSON payload.", status=400)

    try:
        customer = _auth_mobile_customer_from_request_data(payload)
    except PermissionError as error:
        return _json_error(error, status=403)
    except Exception as error:
        return _json_error(error, status=400)

    if hasattr(customer, "is_active"):
        customer.is_active = False
        if hasattr(customer, "api_token"):
            customer.api_token = ""
            _save_model(customer, ["is_active", "api_token"])
        else:
            _save_model(customer, ["is_active"])
    else:
        customer.delete()

    return JsonResponse(
        {
            "success": True,
            "message": "Customer account removed successfully.",
        }
    )


def _photo_customer_payload(request, customer):
    profile_image_url = ""

    if getattr(customer, "profile_image", None):
        try:
            profile_image_url = request.build_absolute_uri(customer.profile_image.url)
        except Exception:
            profile_image_url = str(customer.profile_image)

    return {
        "id": customer.id,
        "full_name": getattr(customer, "full_name", ""),
        "phone_number": getattr(customer, "phone_number", ""),
        "email": getattr(customer, "email", ""),
        "api_token": getattr(customer, "api_token", ""),
        "profile_image_url": profile_image_url,
        "profile_image": profile_image_url,
    }


@csrf_exempt
@require_POST
def mobile_customer_profile_photo_api(request):
    try:
        customer = _settings_auth_customer(request.POST)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    if not hasattr(customer, "profile_image"):
        return JsonResponse(
            {
                "success": False,
                "message": "MobileCustomer.profile_image field is missing. Add the ImageField and run migrations.",
            },
            status=500,
        )

    image_file = request.FILES.get("profile_photo") or request.FILES.get("profile_image") or request.FILES.get("image")

    if not image_file:
        return JsonResponse({"success": False, "message": "Profile photo is required."}, status=400)

    customer.profile_image = image_file
    customer.save(update_fields=["profile_image", "updated_at"] if hasattr(customer, "updated_at") else ["profile_image"])

    return JsonResponse(
        {
            "success": True,
            "message": "Profile photo uploaded successfully.",
            "customer": _photo_customer_payload(request, customer),
        }
    )


def _profile_photo_auth_customer(request):
    """
    Reuses your existing settings auth helper when available.
    Works with multipart/form-data request.POST.
    """
    if "_settings_auth_customer" in globals():
        return _settings_auth_customer(request.POST)

    if "_auth_mobile_customer_from_request_data" in globals():
        return _auth_mobile_customer_from_request_data(request.POST)

    raise RuntimeError("No mobile customer auth helper found in mobile_customers/views.py")


def _profile_photo_url(request, customer):
    if getattr(customer, "profile_image", None):
        try:
            return request.build_absolute_uri(customer.profile_image.url)
        except Exception:
            try:
                return customer.profile_image.url
            except Exception:
                return str(customer.profile_image)
    return ""


def _profile_photo_customer_payload(request, customer):
    image_url = _profile_photo_url(request, customer)

    return {
        "id": customer.id,
        "full_name": getattr(customer, "full_name", ""),
        "phone_number": getattr(customer, "phone_number", ""),
        "email": getattr(customer, "email", ""),
        "api_token": getattr(customer, "api_token", ""),
        "profile_image_url": image_url,
        "profile_image": image_url,
    }


@csrf_exempt
@require_POST
def mobile_customer_profile_photo_api(request):
    try:
        customer = _profile_photo_auth_customer(request)
    except PermissionError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except Exception as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)

    if not hasattr(customer, "profile_image"):
        return JsonResponse(
            {
                "success": False,
                "message": "MobileCustomer.profile_image field is missing. Add it to models.py and run migrations.",
            },
            status=500,
        )

    image_file = (
        request.FILES.get("profile_photo")
        or request.FILES.get("profile_image")
        or request.FILES.get("image")
        or request.FILES.get("file")
    )

    if not image_file:
        return JsonResponse(
            {
                "success": False,
                "message": "Profile photo is required. No uploaded file was received by Django.",
                "received_file_keys": list(request.FILES.keys()),
                "received_post_keys": list(request.POST.keys()),
            },
            status=400,
        )

    # Optional simple safety check
    if getattr(image_file, "size", 0) and image_file.size > 6 * 1024 * 1024:
        return JsonResponse(
            {"success": False, "message": "Profile photo is too large. Use an image under 6MB."},
            status=400,
        )

    customer.profile_image = image_file
    save_fields = ["profile_image"]

    if hasattr(customer, "updated_at"):
        save_fields.append("updated_at")

    customer.save(update_fields=save_fields)

    image_url = _profile_photo_url(request, customer)

    return JsonResponse(
        {
            "success": True,
            "message": "Profile photo uploaded successfully.",
            "profile_image_url": image_url,
            "customer": _profile_photo_customer_payload(request, customer),
        }
    )
