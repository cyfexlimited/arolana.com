ROLE_ADMIN = "admin"
ROLE_CUSTOMER = "customer"
ROLE_VENDOR = "vendor"
ROLE_PROVIDER = "provider"
ROLE_RIDER = "rider"
ROLE_GUEST = "guest"

KNOWN_ROLES = {
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ROLE_VENDOR,
    ROLE_PROVIDER,
    ROLE_RIDER,
    ROLE_GUEST,
}


def role_for_user(user=None, *, staff_session=None, mobile_customer=None, provider=None, rider=None):
    if staff_session is not None:
        role = getattr(staff_session, "role", "")
        if role in KNOWN_ROLES:
            return role
    if user is not None and getattr(user, "is_authenticated", False):
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return ROLE_ADMIN
        if getattr(user, "user_type", "") == "vendor" or hasattr(user, "vendor_profile"):
            return ROLE_VENDOR
        if hasattr(user, "service_provider_profile") or provider is not None:
            return ROLE_PROVIDER
        if hasattr(user, "rider_profile") or rider is not None:
            return ROLE_RIDER
        return ROLE_CUSTOMER
    if mobile_customer is not None:
        return ROLE_CUSTOMER
    return ROLE_GUEST


def role_allowed(role, allowed_roles):
    allowed = set(allowed_roles or [])
    return "all" in allowed or role in allowed


def require_role(role, allowed_roles, message="AI access is not allowed for this role."):
    if not role_allowed(role, allowed_roles):
        raise PermissionError(message)
    return True
