from __future__ import annotations

import logging
import posixpath
from dataclasses import dataclass
from typing import Iterator

from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist


logger = logging.getLogger("arolana.private_media")


# ============================================================================
# ROLE GROUP NAMES
# ============================================================================


PRIVATE_MEDIA_ADMIN_GROUP = "Private Media Admins"

COMPLIANCE_GROUPS = (
    "Compliance Reviewers",
    PRIVATE_MEDIA_ADMIN_GROUP,
)

FINANCE_GROUPS = (
    "Finance Reviewers",
    PRIVATE_MEDIA_ADMIN_GROUP,
)

SUPPORT_GROUPS = (
    "Support Team",
    PRIVATE_MEDIA_ADMIN_GROUP,
)

DELIVERY_GROUPS = (
    "Delivery Operations",
    PRIVATE_MEDIA_ADMIN_GROUP,
)

HR_GROUPS = (
    "HR Reviewers",
    PRIVATE_MEDIA_ADMIN_GROUP,
)

MODERATION_GROUPS = (
    "Review Moderators",
    PRIVATE_MEDIA_ADMIN_GROUP,
)


# ============================================================================
# PRIVATE MEDIA RULES
# ============================================================================


@dataclass(frozen=True)
class PrivateMediaRule:
    key: str
    model_label: str
    field_name: str
    prefixes: tuple[str, ...]
    scope: str

    # Attribute paths that ultimately resolve to:
    # - a User object, or
    # - an object with a user_id field.
    owner_paths: tuple[str, ...] = ()

    # Optional session-key ownership.
    # Used for guest SmartChat conversations.
    session_path: str = ""

    # Role groups allowed to access this media category.
    staff_groups: tuple[str, ...] = ()


PRIVATE_MEDIA_RULES: tuple[PrivateMediaRule, ...] = (
    # ========================================================================
    # VENDOR VERIFICATION
    # ========================================================================
    PrivateMediaRule(
        key="vendor_verification_document",
        model_label="vendors.VendorProfile",
        field_name="verification_documents",
        prefixes=(
            "vendors/documents",
        ),
        scope="kyc",
        owner_paths=(
            "user",
        ),
        staff_groups=COMPLIANCE_GROUPS,
    ),

    # ========================================================================
    # CENTRAL VENDOR KYC
    # ========================================================================
    PrivateMediaRule(
        key="vendor_kyc_document",
        model_label="kyc.KYCDocument",
        field_name="document_file",
        prefixes=(
            "kyc/documents",
        ),
        scope="kyc",
        owner_paths=(
            "vendor",
            "vendor.user",
        ),
        staff_groups=COMPLIANCE_GROUPS,
    ),

    # ========================================================================
    # SERVICE PROVIDER VERIFICATION
    # ========================================================================
    PrivateMediaRule(
        key="provider_cac_certificate",
        model_label="installers.ServiceProviderProfile",
        field_name="cac_certificate_upload",
        prefixes=(
            "installers/verification",
        ),
        scope="kyc",
        owner_paths=(
            "user",
        ),
        staff_groups=COMPLIANCE_GROUPS,
    ),

    PrivateMediaRule(
        key="provider_government_id",
        model_label="installers.ServiceProviderProfile",
        field_name="government_id_upload",
        prefixes=(
            "installers/verification",
        ),
        scope="kyc",
        owner_paths=(
            "user",
        ),
        staff_groups=COMPLIANCE_GROUPS,
    ),

    PrivateMediaRule(
        key="provider_profile_change_file",
        model_label="installers.ProviderProfileChangeRequest",
        field_name="proposed_file",
        prefixes=(
            "installers/profile-change-requests",
        ),
        scope="kyc",
        owner_paths=(
            "provider.user",
            "provider_profile.user",
            "profile.user",
            "service_provider.user",
            "user",
        ),
        staff_groups=COMPLIANCE_GROUPS,
    ),

    PrivateMediaRule(
        key="provider_kyc_document",
        model_label="installers.ProviderKYCDocument",
        field_name="file",
        prefixes=(
            "installers/kyc",
        ),
        scope="kyc",
        owner_paths=(
            "provider.user",
            "provider_profile.user",
            "profile.user",
            "service_provider.user",
            "user",
        ),
        staff_groups=COMPLIANCE_GROUPS,
    ),

    # ========================================================================
    # PAYMENT EVIDENCE
    # ========================================================================
    PrivateMediaRule(
        key="payment_manual_proof",
        model_label="arolana_payments.PaymentTransaction",
        field_name="manual_proof",
        prefixes=(
            "payment_proofs",
        ),
        scope="payment",
        owner_paths=(
            "user",
        ),
        staff_groups=FINANCE_GROUPS,
    ),

    # ========================================================================
    # STANDARD CHAT ATTACHMENTS
    # ========================================================================
    PrivateMediaRule(
        key="chat_attachment",
        model_label="chat.ChatMessage",
        field_name="attachment",
        prefixes=(
            "chat/attachments",
        ),
        scope="chat",
        owner_paths=(
            "sender",
            "room.order.user",
            "room.product.vendor",
        ),
        staff_groups=SUPPORT_GROUPS,
    ),

    # ========================================================================
    # CUSTOMER ↔ VENDOR CHAT
    #
    # VendorChatRoom has explicit vendor/customer participants.
    # ========================================================================
    PrivateMediaRule(
        key="vendor_chat_attachment",
        model_label="chat.VendorChatMessage",
        field_name="attachment",
        prefixes=(
            "chat/vendor_attachments",
        ),
        scope="chat",
        owner_paths=(
            "sender",
            "room.vendor",
            "room.customer",
        ),
        staff_groups=SUPPORT_GROUPS,
    ),

    # ========================================================================
    # SMART CHAT
    # ========================================================================
    PrivateMediaRule(
        key="smartchat_image",
        model_label="smartchat.SmartChatMessage",
        field_name="image",
        prefixes=(
            "smartchat/images",
        ),
        scope="chat",
        owner_paths=(
            "user",
            "conversation.user",
            "conversation.assigned_admin",
            "conversation.vendor_profile.user",
            "conversation.rider_profile.user",
        ),
        session_path="conversation.session_key",
        staff_groups=SUPPORT_GROUPS,
    ),

    # AIMessage may be a proxy/alias over SmartChatMessage in parts
    # of the project. Keeping an explicit rule makes the registry complete.
    PrivateMediaRule(
        key="smartchat_ai_image",
        model_label="smartchat.AIMessage",
        field_name="image",
        prefixes=(
            "smartchat/images",
        ),
        scope="chat",
        owner_paths=(
            "user",
            "conversation.user",
            "conversation.assigned_admin",
            "conversation.vendor_profile.user",
            "conversation.rider_profile.user",
        ),
        session_path="conversation.session_key",
        staff_groups=SUPPORT_GROUPS,
    ),

    # ========================================================================
    # DELIVERY PROOF
    # ========================================================================
    PrivateMediaRule(
        key="delivery_proof",
        model_label="deliveries.DeliveryRequest",
        field_name="proof_of_delivery",
        prefixes=(
            "delivery/proofs",
        ),
        scope="delivery",
        owner_paths=(
            "order.user",
            "rider.user",
        ),
        staff_groups=DELIVERY_GROUPS,
    ),

    # ========================================================================
    # RIDER DOCUMENTS
    # ========================================================================
    PrivateMediaRule(
        key="rider_id_document",
        model_label="deliveries.RiderProfile",
        field_name="id_document",
        prefixes=(
            "delivery/riders/id_documents",
        ),
        scope="delivery",
        owner_paths=(
            "user",
        ),
        staff_groups=DELIVERY_GROUPS,
    ),

    PrivateMediaRule(
        key="rider_driver_license",
        model_label="deliveries.RiderProfile",
        field_name="driver_license",
        prefixes=(
            "delivery/riders/licenses",
        ),
        scope="delivery",
        owner_paths=(
            "user",
        ),
        staff_groups=DELIVERY_GROUPS,
    ),

    PrivateMediaRule(
        key="rider_vehicle_document",
        model_label="deliveries.RiderProfile",
        field_name="vehicle_document",
        prefixes=(
            "delivery/riders/vehicle_documents",
        ),
        scope="delivery",
        owner_paths=(
            "user",
        ),
        staff_groups=DELIVERY_GROUPS,
    ),

    PrivateMediaRule(
        key="rider_profile_photo",
        model_label="deliveries.RiderProfile",
        field_name="profile_photo",
        prefixes=(
            "delivery/riders/photos",
        ),
        scope="delivery",
        owner_paths=(
            "user",
        ),
        staff_groups=DELIVERY_GROUPS,
    ),

    PrivateMediaRule(
        key="rider_dashboard_image",
        model_label="deliveries.RiderProfile",
        field_name="dashboard_image",
        prefixes=(
            "delivery/riders/banners",
        ),
        scope="delivery",
        owner_paths=(
            "user",
        ),
        staff_groups=DELIVERY_GROUPS,
    ),

    # ========================================================================
    # SERVICE COMPLETION EVIDENCE
    # ========================================================================
    PrivateMediaRule(
        key="service_completion_photo",
        model_label="installers.ServiceQuoteRequest",
        field_name="completion_photo",
        prefixes=(
            "installers/completions",
        ),
        scope="delivery",
        owner_paths=(
            "user",
            "customer",
            "customer.user",
            "requester",
            "requester.user",
            "provider.user",
            "assigned_provider.user",
            "service_provider.user",
        ),
        staff_groups=DELIVERY_GROUPS,
    ),

    # ========================================================================
    # JOB APPLICATIONS
    # ========================================================================
    PrivateMediaRule(
        key="job_application_resume",
        model_label="pages.JobApplication",
        field_name="resume",
        prefixes=(
            "job_applications/resumes",
        ),
        scope="hr",
        owner_paths=(
            "user",
            "applicant",
            "applicant.user",
        ),
        staff_groups=HR_GROUPS,
    ),

    # ========================================================================
    # PRODUCT REVIEW MEDIA
    #
    # Kept private until Arolana adds explicit moderated-public publishing.
    # ========================================================================
    PrivateMediaRule(
        key="product_review_video",
        model_label="products.ProductReview",
        field_name="video_review",
        prefixes=(
            "reviews/videos",
        ),
        scope="review",
        owner_paths=(
            "user",
        ),
        staff_groups=MODERATION_GROUPS,
    ),

    PrivateMediaRule(
        key="review_video_file",
        model_label="products.ReviewVideo",
        field_name="video_file",
        prefixes=(
            "reviews/videos",
        ),
        scope="review",
        owner_paths=(
            "user",
            "review.user",
            "product_review.user",
        ),
        staff_groups=MODERATION_GROUPS,
    ),

    PrivateMediaRule(
        key="review_video_thumbnail",
        model_label="products.ReviewVideo",
        field_name="thumbnail",
        prefixes=(
            "reviews/thumbs",
            "reviews/thumbnails",
        ),
        scope="review",
        owner_paths=(
            "user",
            "review.user",
            "product_review.user",
        ),
        staff_groups=MODERATION_GROUPS,
    ),

    # ========================================================================
    # MOBILE CUSTOMER PRIVATE PROFILE PHOTO
    # ========================================================================
    PrivateMediaRule(
        key="mobile_customer_profile_image",
        model_label="mobile_customers.MobileCustomer",
        field_name="profile_image",
        prefixes=(
            "mobile_customers/profile_pictures",
        ),
        scope="customer",
        owner_paths=(
            "user",
        ),
        staff_groups=SUPPORT_GROUPS,
    ),
)


# ============================================================================
# DECISION OBJECTS
# ============================================================================


@dataclass(frozen=True)
class PrivateMediaResource:
    rule: PrivateMediaRule
    obj: object
    path: str


@dataclass(frozen=True)
class PrivateMediaDecision:
    allowed: bool
    reason: str
    rule_key: str = ""
    model_label: str = ""
    object_id: object = None
    principal_user_id: object = None


# ============================================================================
# PATH SAFETY
# ============================================================================


def normalize_private_media_path(path) -> str:
    """
    Normalize a media path without changing filename case.

    Reject:
    - empty paths
    - NUL bytes
    - traversal segments
    """
    raw = str(path or "").strip()

    if not raw:
        return ""

    if "\x00" in raw:
        return ""

    raw = raw.replace("\\", "/")

    if any(
        segment == ".."
        for segment in raw.split("/")
    ):
        return ""

    normalized = posixpath.normpath(raw).lstrip("/")

    if (
        not normalized
        or normalized == "."
        or normalized.startswith("../")
        or "/../" in normalized
        or normalized.endswith("/..")
    ):
        return ""

    if normalized.startswith("media/"):
        normalized = normalized[len("media/"):]

    return normalized


def _path_matches_prefix(
    path: str,
    prefix: str,
) -> bool:
    clean_path = normalize_private_media_path(path)
    clean_prefix = normalize_private_media_path(prefix)

    if not clean_path or not clean_prefix:
        return False

    path_lower = clean_path.lower()
    prefix_lower = clean_prefix.lower()

    return (
        path_lower == prefix_lower
        or path_lower.startswith(
            f"{prefix_lower}/"
        )
    )


def _rule_matches_path(
    rule: PrivateMediaRule,
    path: str,
) -> bool:
    return any(
        _path_matches_prefix(
            path,
            prefix,
        )
        for prefix in rule.prefixes
    )


# ============================================================================
# ATTRIBUTE / OWNER RESOLUTION
# ============================================================================


def _read_attr_path(
    obj,
    dotted_path: str,
):
    current = obj

    for part in str(dotted_path or "").split("."):
        if not part:
            continue

        if current is None:
            return None

        try:
            current = getattr(
                current,
                part,
            )
        except (
            AttributeError,
            ObjectDoesNotExist,
        ):
            return None
        except Exception:
            return None

    return current


def _value_to_user_id(value):
    """
    Convert a relation value into an auth-user primary key.

    Supports:
    - direct User objects;
    - related objects with user_id;
    - direct integer IDs.
    """
    if value is None:
        return None

    if isinstance(value, int):
        return value

    meta = getattr(
        value,
        "_meta",
        None,
    )

    if meta:
        auth_label = str(
            settings.AUTH_USER_MODEL
        ).lower()

        if meta.label_lower == auth_label:
            return value.pk

    direct_user_id = getattr(
        value,
        "user_id",
        None,
    )

    if direct_user_id is not None:
        return direct_user_id

    return None


def resource_owner_user_ids(
    resource: PrivateMediaResource,
) -> set:
    user_ids = set()

    for owner_path in resource.rule.owner_paths:
        value = _read_attr_path(
            resource.obj,
            owner_path,
        )

        user_id = _value_to_user_id(
            value
        )

        if user_id is not None:
            user_ids.add(
                user_id
            )

    return user_ids


# ============================================================================
# MOBILE / WEB PRINCIPAL RESOLUTION
# ============================================================================


def _bearer_token_from_request(
    request,
) -> str:
    try:
        header = request.headers.get(
            "Authorization",
            "",
        )
    except Exception:
        header = request.META.get(
            "HTTP_AUTHORIZATION",
            "",
        )

    header = str(
        header or ""
    ).strip()

    if not header.lower().startswith(
        "bearer "
    ):
        return ""

    return header[7:].strip()


def _user_from_staff_mobile_token(
    token: str,
):
    if not token:
        return None

    try:
        TokenModel = apps.get_model(
            "staff_mobile",
            "StaffMobileToken",
        )
    except LookupError:
        return None

    try:
        session = (
            TokenModel.objects
            .select_related(
                "user",
                "rider",
            )
            .filter(
                token=token,
                is_active=True,
            )
            .first()
        )
    except Exception:
        return None

    if not session:
        return None

    user = getattr(
        session,
        "user",
        None,
    )

    if (
        user
        and getattr(
            user,
            "is_active",
            True,
        )
    ):
        return user

    rider = getattr(
        session,
        "rider",
        None,
    )

    rider_user = getattr(
        rider,
        "user",
        None,
    )

    if (
        rider_user
        and getattr(
            rider_user,
            "is_active",
            True,
        )
    ):
        return rider_user

    return None


def _user_from_mobile_customer_token(
    token: str,
):
    if not token:
        return None

    try:
        MobileCustomer = apps.get_model(
            "mobile_customers",
            "MobileCustomer",
        )
    except LookupError:
        return None

    try:
        customer = (
            MobileCustomer.objects
            .select_related(
                "user"
            )
            .filter(
                api_token=token,
            )
            .first()
        )
    except Exception:
        return None

    if not customer:
        return None

    user = getattr(
        customer,
        "user",
        None,
    )

    if (
        user
        and getattr(
            user,
            "is_active",
            True,
        )
    ):
        return user

    return None


def request_principal_user(
    request,
):
    """
    Resolve the user making the private-media request.

    Priority:
    1. Normal authenticated Django session.
    2. Staff-mobile Bearer token.
    3. Mobile-customer Bearer token.

    Query-string tokens are intentionally not accepted.
    """
    request_user = getattr(
        request,
        "user",
        None,
    )

    if (
        request_user
        and getattr(
            request_user,
            "is_authenticated",
            False,
        )
    ):
        return request_user

    token = _bearer_token_from_request(
        request
    )

    if not token:
        return None

    user = _user_from_staff_mobile_token(
        token
    )

    if user:
        return user

    return _user_from_mobile_customer_token(
        token
    )


# ============================================================================
# ROLE / PERMISSION AUTHORIZATION
# ============================================================================


def _user_group_names(
    user,
) -> set[str]:
    if not user:
        return set()

    try:
        return {
            str(name).casefold()
            for name in user.groups.values_list(
                "name",
                flat=True,
            )
        }
    except Exception:
        return set()


def _role_or_permission_access(
    user,
    rule: PrivateMediaRule,
    model,
) -> bool:
    if not user:
        return False

    if getattr(
        user,
        "is_superuser",
        False,
    ):
        return True

    permission_name = (
        f"{model._meta.app_label}."
        f"view_{model._meta.model_name}"
    )

    try:
        if user.has_perm(
            permission_name
        ):
            return True
    except Exception:
        pass

    allowed_groups = {
        str(group).casefold()
        for group in rule.staff_groups
    }

    if not allowed_groups:
        return False

    user_groups = _user_group_names(
        user
    )

    return bool(
        allowed_groups.intersection(
            user_groups
        )
    )


# ============================================================================
# RESOURCE RESOLUTION
# ============================================================================


def iter_private_media_resources(
    path: str,
) -> Iterator[PrivateMediaResource]:
    """
    Yield database records that own the exact private storage path.

    An orphaned storage object that has no matching DB record receives no grant.
    """
    normalized_path = normalize_private_media_path(
        path
    )

    if not normalized_path:
        return

    # Private optimized derivatives are intentionally not served.
    # Private documents should be accessed only through their original object.
    if normalized_path.lower().startswith(
        "optimized/"
    ):
        return

    for rule in PRIVATE_MEDIA_RULES:
        if not _rule_matches_path(
            rule,
            normalized_path,
        ):
            continue

        try:
            model = apps.get_model(
                rule.model_label
            )
        except LookupError:
            continue

        if not model:
            continue

        try:
            model._meta.get_field(
                rule.field_name
            )
        except FieldDoesNotExist:
            continue

        try:
            queryset = model._default_manager.filter(
                **{
                    rule.field_name: normalized_path,
                }
            )
        except Exception:
            continue

        # A reused exact file path can theoretically appear on multiple
        # records. Evaluate up to 50 matching ownership records.
        try:
            objects = queryset[:50]
        except Exception:
            continue

        for obj in objects:
            yield PrivateMediaResource(
                rule=rule,
                obj=obj,
                path=normalized_path,
            )


# ============================================================================
# SESSION AUTHORIZATION
# ============================================================================


def _session_access(
    request,
    resource: PrivateMediaResource,
) -> bool:
    session_path = resource.rule.session_path

    if not session_path:
        return False

    expected_session_key = _read_attr_path(
        resource.obj,
        session_path,
    )

    if not expected_session_key:
        return False

    request_session = getattr(
        request,
        "session",
        None,
    )

    if not request_session:
        return False

    actual_session_key = getattr(
        request_session,
        "session_key",
        None,
    )

    return bool(
        actual_session_key
        and actual_session_key
        == expected_session_key
    )


# ============================================================================
# DELIVERY VENDOR ACCESS
# ============================================================================


def _delivery_vendor_access(
    user,
    resource: PrivateMediaResource,
) -> bool:
    """
    Allow a vendor involved in an order to inspect that order's delivery proof.

    This is an additional rule beyond customer and rider ownership.
    """
    if (
        not user
        or resource.rule.scope != "delivery"
    ):
        return False

    if resource.rule.model_label.lower() != (
        "deliveries.deliveryrequest"
    ):
        return False

    order = _read_attr_path(
        resource.obj,
        "order",
    )

    if not order:
        return False

    for manager_name in (
        "items",
        "order_items",
    ):
        manager = getattr(
            order,
            manager_name,
            None,
        )

        if manager is None:
            continue

        try:
            if manager.filter(
                product__vendor_id=user.pk
            ).exists():
                return True
        except Exception:
            continue

    return False


# ============================================================================
# AUTHORIZATION
# ============================================================================


def _resource_access_allowed(
    request,
    principal_user,
    resource: PrivateMediaResource,
) -> tuple[bool, str]:
    model = resource.obj.__class__

    # 1. Superuser / explicit model permission / authorised role group.
    if _role_or_permission_access(
        principal_user,
        resource.rule,
        model,
    ):
        return True, "role_or_permission"

    # 2. Direct owner / participant access.
    if principal_user:
        owner_ids = resource_owner_user_ids(
            resource
        )

        if principal_user.pk in owner_ids:
            return True, "owner_or_participant"

    # 3. Order vendor access to proof-of-delivery.
    if _delivery_vendor_access(
        principal_user,
        resource,
    ):
        return True, "order_vendor"

    # 4. Guest SmartChat session ownership.
    if _session_access(
        request,
        resource,
    ):
        return True, "matching_session"

    return False, "not_authorized"


def authorize_private_media_request(
    request,
    path: str,
) -> PrivateMediaDecision:
    """
    Resolve a private storage path to its database owner and authorize access.

    Fail-closed behavior:
    - unsafe path -> deny;
    - private optimized derivative -> deny;
    - no matching registry rule -> deny;
    - no matching DB record -> deny;
    - matching record but wrong user -> deny.
    """
    normalized_path = normalize_private_media_path(
        path
    )

    principal_user = request_principal_user(
        request
    )

    principal_user_id = getattr(
        principal_user,
        "pk",
        None,
    )

    if not normalized_path:
        return PrivateMediaDecision(
            allowed=False,
            reason="unsafe_path",
            principal_user_id=principal_user_id,
        )

    if normalized_path.lower().startswith(
        "optimized/"
    ):
        return PrivateMediaDecision(
            allowed=False,
            reason="private_derivative_denied",
            principal_user_id=principal_user_id,
        )

    matched_resource = False
    last_resource = None

    for resource in iter_private_media_resources(
        normalized_path
    ):
        matched_resource = True
        last_resource = resource

        allowed, reason = _resource_access_allowed(
            request,
            principal_user,
            resource,
        )

        if allowed:
            decision = PrivateMediaDecision(
                allowed=True,
                reason=reason,
                rule_key=resource.rule.key,
                model_label=resource.rule.model_label,
                object_id=getattr(
                    resource.obj,
                    "pk",
                    None,
                ),
                principal_user_id=principal_user_id,
            )

            logger.info(
                (
                    "Private media access allowed "
                    "rule=%s model=%s object_id=%s user_id=%s reason=%s"
                ),
                decision.rule_key,
                decision.model_label,
                decision.object_id,
                decision.principal_user_id,
                decision.reason,
            )

            return decision

    if matched_resource and last_resource:
        decision = PrivateMediaDecision(
            allowed=False,
            reason="not_authorized",
            rule_key=last_resource.rule.key,
            model_label=last_resource.rule.model_label,
            object_id=getattr(
                last_resource.obj,
                "pk",
                None,
            ),
            principal_user_id=principal_user_id,
        )

        logger.warning(
            (
                "Private media access denied "
                "rule=%s model=%s object_id=%s user_id=%s"
            ),
            decision.rule_key,
            decision.model_label,
            decision.object_id,
            decision.principal_user_id,
        )

        return decision

    logger.warning(
        (
            "Private media access denied because no registered "
            "database resource owns the requested private path. "
            "user_id=%s"
        ),
        principal_user_id,
    )

    return PrivateMediaDecision(
        allowed=False,
        reason="unregistered_or_orphaned_private_media",
        principal_user_id=principal_user_id,
    )