from catalog_imports.models import ImportMediaCandidate


class MediaPromptHold(ValueError):
    """Raised when verified evidence is insufficient for an exact-product view."""


def _payload(item):
    return item.normalized_payload or {}


def _identity(item):
    payload = _payload(item)
    brand = str(payload.get("brand") or payload.get("manufacturer") or "").strip()
    name = str(payload.get("name") or "").strip()
    model = str(payload.get("model") or payload.get("manufacturer_sku") or "").strip()
    return brand, name, model


def _specifications(item):
    specs = _payload(item).get("specifications") or {}
    return specs if isinstance(specs, dict) else {}


def _package_contents(item):
    values = _payload(item).get("package_contents") or []
    if not isinstance(values, (list, tuple)):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _port_evidence(specs):
    tokens = (
        "port", "hdmi", "usb", "ethernet", "network", "input", "output",
        "bluetooth", "wi-fi", "wifi", "connector", "interface",
    )
    matched = []
    for key, value in specs.items():
        label = f"{key} {value}".lower()
        if any(token in label for token in tokens):
            matched.append(f"{key}: {value}")
    return matched


def _candidate_metadata(candidate):
    data = getattr(candidate, "metadata", None) or {}
    return data if isinstance(data, dict) else {}


def view_instruction(item, view_role, candidate=None):
    metadata = _candidate_metadata(candidate) if candidate is not None else {}

    if metadata:
        generation_policy = str(metadata.get("generation_policy") or "")
        if generation_policy == "actual_only":
            raise MediaPromptHold(
                "This category-profile slot requires actual seller/verified documentary media. "
                "AI generation is deliberately disabled."
            )

        slot_prompt = str(metadata.get("slot_prompt") or "").strip()
        if slot_prompt:
            return slot_prompt

    specs = _specifications(item)
    package_contents = _package_contents(item)

    mapping = {
        ImportMediaCandidate.VIEW_MAIN: "Create a clean primary ecommerce hero image of the exact verified item.",
        ImportMediaCandidate.VIEW_FRONT: "Show the exact verified item clearly from its primary factual view.",
        ImportMediaCandidate.VIEW_LEFT: "Create a useful alternate presentation grounded in the exact item identity.",
        ImportMediaCandidate.VIEW_RIGHT: "Create a useful alternate presentation grounded in the exact item identity.",
        ImportMediaCandidate.VIEW_SIDE: "Create a useful side/alternate presentation without inventing hidden detail.",
        ImportMediaCandidate.VIEW_BACK: "Show rear/back detail only when it is directly supported by evidence.",
        ImportMediaCandidate.VIEW_TOP: "Create a useful top/detail presentation grounded in verified evidence.",
        ImportMediaCandidate.VIEW_LIFESTYLE: "Place the exact verified item naturally in an appropriate usage environment.",
        ImportMediaCandidate.VIEW_CLOSEUP: "Create a close detail using only features visible or verified in the evidence.",
    }

    if view_role == ImportMediaCandidate.VIEW_PORTS:
        ports = _port_evidence(specs)
        if not ports:
            raise MediaPromptHold(
                "Technical detail was held because no verified interface/control evidence is available."
            )
        return (
            "Create a technical detail view using only these verified interfaces/controls: "
            + "; ".join(ports[:12])
            + ". Do not add extra ports, labels, or controls."
        )

    if view_role == ImportMediaCandidate.VIEW_PACKAGE:
        if not package_contents:
            raise MediaPromptHold(
                "Package/contents image was held because verified package contents are not available."
            )
        return (
            "Create a package/contents image showing only these verified included items: "
            + "; ".join(package_contents[:20])
            + ". Do not invent accessories or bundles."
        )

    return mapping.get(
        view_role,
        "Create a clean marketplace image of the exact verified item without inventing factual details.",
    )


def build_generation_prompt(item, candidate):
    if not getattr(item, "identity_verified", False):
        raise MediaPromptHold("Exact item identity must be verified before image generation.")

    metadata = _candidate_metadata(candidate)
    if metadata:
        requires_specs = bool(metadata.get("requires_specifications"))
        if requires_specs and not getattr(item, "specifications_verified", False):
            raise MediaPromptHold(
                "This media slot requires verified specifications before generation."
            )
    elif not getattr(item, "specifications_verified", False):
        # Backward compatibility for legacy plans created before Phase 5.1.
        raise MediaPromptHold("Specifications must be verified before image generation.")

    brand, name, model = _identity(item)
    if not name:
        raise MediaPromptHold("Verified item name is missing.")

    identity = name
    if brand and brand.lower() not in identity.lower():
        identity = f"{brand} {identity}"
    model_clause = f" Exact model/identifier: {model}." if model else ""

    instruction = view_instruction(item, candidate.view_role, candidate=candidate)
    profile_label = str(metadata.get("media_profile_label") or "").strip()
    display_label = str(metadata.get("display_label") or "").strip()
    category_clause = (
        f" Media profile: {profile_label}. Slot: {display_label}."
        if profile_label or display_label
        else ""
    )

    return (
        f"Create an Arolana marketplace image of the exact verified item: {identity}.{model_clause}"
        f"{category_clause} {instruction} "
        "Use supplied verified references as identity evidence. Preserve visible shape, proportions, color, "
        "pattern, finish, material appearance, branding, and other directly supported identity cues. "
        "Do not copy or include retailer identity, retailer watermarks, seller overlays, prices, promotional "
        "banners, website UI, or source-store text. Do not invent ports, buttons, accessories, package "
        "contents, garment labels, fabric composition, shoe construction, watch engravings, eyewear hardware, "
        "furniture dimensions, property rooms/amenities, land boundaries, location facts, measurements, title "
        "status, certifications, or other unsupported claims. Where a detail is uncertain, simplify, obscure, "
        "or de-emphasize it rather than guessing. Use a professional marketplace presentation and no text overlay. "
        "Human review is mandatory before Product use."
    )
