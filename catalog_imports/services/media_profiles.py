"""Universal category-aware media profiles for Arolana.

This module intentionally does not add database fields.  Phase 5.1 stores the
profile/taxonomy data in ImportMediaCandidate.metadata so the existing Product,
ProductImage, Vendor and importer schema remain compatible.

A media profile answers three separate questions:
1. What job does this image perform in the gallery?        -> universal_role
2. What kind of visual is it?                              -> media_type
3. How much factual trust does this slot require/allow?    -> trust_policy

The legacy ImportMediaCandidate.view_role remains only as a compatibility bridge
for existing reference discovery/generation infrastructure.
"""

from dataclasses import dataclass
from typing import Iterable, Tuple

from catalog_imports.models import ImportMediaCandidate


TRUST_EXACT = "verified_exact"
TRUST_SUPPORTING = "verified_supporting"
TRUST_CREATIVE = "creative_allowed"
TRUST_ACTUAL = "actual_media_required"

POLICY_VERIFIED = "verified_preferred"
POLICY_CREATIVE = "creative"
POLICY_ACTUAL_ONLY = "actual_only"

TYPE_PRODUCT = "product_only"
TYPE_TECHNICAL = "technical"
TYPE_CLOSEUP = "closeup"
TYPE_SCENE = "scene"
TYPE_PACKAGING = "packaging"
TYPE_MODEL_WORN = "model_worn"
TYPE_PROPERTY = "property_photo"
TYPE_FLOORPLAN = "floorplan"
TYPE_MAP = "map"
TYPE_AERIAL = "aerial"
TYPE_CONCEPT = "concept_visualization"


@dataclass(frozen=True)
class MediaSlot:
    key: str
    label: str
    universal_role: str
    media_type: str
    trust_policy: str
    generation_policy: str
    legacy_view_role: str
    prompt: str
    creative_prompt: str = ""
    creative_allowed: bool = False
    requires_specifications: bool = False
    representation_rule: str = "product"


@dataclass(frozen=True)
class MediaProfile:
    key: str
    label: str
    slots: Tuple[MediaSlot, ...]
    notes: str = ""


def _slot(
    key,
    label,
    universal_role,
    media_type,
    trust_policy,
    generation_policy,
    legacy_view_role,
    prompt,
    *,
    creative_prompt="",
    creative_allowed=False,
    requires_specifications=False,
    representation_rule="product",
):
    return MediaSlot(
        key=key,
        label=label,
        universal_role=universal_role,
        media_type=media_type,
        trust_policy=trust_policy,
        generation_policy=generation_policy,
        legacy_view_role=legacy_view_role,
        prompt=prompt,
        creative_prompt=creative_prompt,
        creative_allowed=creative_allowed,
        requires_specifications=requires_specifications,
        representation_rule=representation_rule,
    )


GENERIC = MediaProfile(
    key="generic",
    label="Generic product",
    notes="Balanced default for products without a specialized category profile.",
    slots=(
        _slot(
            "hero", "Main / hero", "hero", TYPE_PRODUCT, TRUST_EXACT, POLICY_VERIFIED,
            ImportMediaCandidate.VIEW_MAIN,
            "Create a clean primary ecommerce hero image of the exact item, centered and visually dominant.",
        ),
        _slot(
            "primary", "Primary factual view", "factual_primary", TYPE_PRODUCT, TRUST_EXACT, POLICY_VERIFIED,
            ImportMediaCandidate.VIEW_FRONT,
            "Show the exact item clearly as the primary factual product view.",
        ),
        _slot(
            "detail", "Detail", "detail", TYPE_CLOSEUP, TRUST_SUPPORTING, POLICY_VERIFIED,
            ImportMediaCandidate.VIEW_CLOSEUP,
            "Show a useful close detail that is supported by the references; do not invent hidden features.",
            creative_allowed=True,
            creative_prompt="Create a tasteful close-detail presentation without inventing factual features.",
        ),
        _slot(
            "lifestyle", "Lifestyle / in use", "lifestyle", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE,
            ImportMediaCandidate.VIEW_LIFESTYLE,
            "Place the exact item naturally in an appropriate real-world usage scene.",
            creative_allowed=True,
            creative_prompt="Create an attractive in-use lifestyle scene appropriate to the item.",
        ),
        _slot(
            "context", "Context / environment", "context", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE,
            ImportMediaCandidate.VIEW_LEFT,
            "Show the exact item in a useful contextual environment.",
            creative_allowed=True,
            creative_prompt="Create a contextual scene that helps a buyer understand how the item is used.",
        ),
        _slot(
            "packaging", "Package / extra", "package_or_extra", TYPE_PACKAGING, TRUST_SUPPORTING, POLICY_VERIFIED,
            ImportMediaCandidate.VIEW_PACKAGE,
            "Show verified packaging or verified included material only.",
            creative_allowed=True,
            creative_prompt=(
                "Create a neutral presentation of the exact item beside a plain closed unbranded box. "
                "Do not show or imply unverified contents."
            ),
            requires_specifications=True,
        ),
        _slot(
            "alternate", "Alternate presentation", "creative_support", TYPE_CONCEPT, TRUST_CREATIVE, POLICY_CREATIVE,
            ImportMediaCandidate.VIEW_RIGHT,
            "Create a useful alternate visual presentation.",
            creative_allowed=True,
            creative_prompt="Create a premium alternate presentation grounded in the exact item identity.",
        ),
        _slot(
            "detail_2", "Secondary detail", "detail_secondary", TYPE_CLOSEUP, TRUST_CREATIVE, POLICY_CREATIVE,
            ImportMediaCandidate.VIEW_TOP,
            "Create a secondary useful detail image.",
            creative_allowed=True,
            creative_prompt="Create a secondary detail-oriented marketplace image without inventing factual claims.",
        ),
        _slot(
            "usage", "Usage scene", "usage", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE,
            ImportMediaCandidate.VIEW_SIDE,
            "Show a natural usage scene.",
            creative_allowed=True,
            creative_prompt="Create a buyer-friendly usage scene with the exact item as the focus.",
        ),
        _slot(
            "creative", "Creative support", "creative_support", TYPE_CONCEPT, TRUST_CREATIVE, POLICY_CREATIVE,
            ImportMediaCandidate.VIEW_BACK,
            "Create a final creative support image.",
            creative_allowed=True,
            creative_prompt="Create a distinctive but honest supporting visual grounded in the exact item identity.",
        ),
    ),
)


ELECTRONICS = MediaProfile(
    key="electronics",
    label="Electronics / devices",
    slots=(
        _slot(
            "hero", "Main / hero", "hero", TYPE_PRODUCT, TRUST_EXACT, POLICY_VERIFIED,
            ImportMediaCandidate.VIEW_MAIN,
            "Create a clean exact-product hero image on a neutral ecommerce background.",
        ),
        _slot(
            "front", "Front", "factual_primary", TYPE_PRODUCT, TRUST_EXACT, POLICY_VERIFIED,
            ImportMediaCandidate.VIEW_FRONT,
            "Show the exact device from the front.",
        ),
        _slot(
            "technical", "Controls / technical detail", "technical_detail", TYPE_TECHNICAL, TRUST_EXACT, POLICY_VERIFIED,
            ImportMediaCandidate.VIEW_PORTS,
            "Show only manufacturer-verified controls, ports, connectors, or technical details.",
            requires_specifications=True,
        ),
        _slot(
            "package", "Package / contents", "package_or_extra", TYPE_PACKAGING, TRUST_EXACT, POLICY_VERIFIED,
            ImportMediaCandidate.VIEW_PACKAGE,
            "Show only manufacturer-verified package contents or packaging.",
            requires_specifications=True,
        ),
        _slot(
            "lifestyle", "Lifestyle / in use", "lifestyle", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE,
            ImportMediaCandidate.VIEW_LIFESTYLE,
            "Show the exact device naturally in use.",
            creative_allowed=True,
            creative_prompt="Create a realistic professional usage scene with people naturally using the exact device.",
        ),
        _slot(
            "installation", "Installed / mounted scene", "installation", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE,
            ImportMediaCandidate.VIEW_LEFT,
            "Show the exact device installed in an appropriate environment.",
            creative_allowed=True,
            creative_prompt=(
                "Create a polished installed-use scene. Preserve the visible product identity; "
                "do not invent technical ports, mounting hardware, or hidden geometry as factual."
            ),
        ),
        _slot(
            "collaboration", "People using the product", "usage", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE,
            ImportMediaCandidate.VIEW_RIGHT,
            "Show people naturally using the exact device.",
            creative_allowed=True,
            creative_prompt="Create a premium people-in-use scene where the exact product is clearly visible and believable.",
        ),
        _slot(
            "render", "3D-style product environment", "creative_support", TYPE_CONCEPT, TRUST_CREATIVE, POLICY_CREATIVE,
            ImportMediaCandidate.VIEW_SIDE,
            "Create a premium 3D-style presentation grounded in the exact visible product identity.",
            creative_allowed=True,
            creative_prompt=(
                "Create a high-end 3D-style product environment. Treat hidden geometry as unverified; "
                "avoid showing unsupported ports, vents, controls, labels, or mounting details."
            ),
        ),
        _slot(
            "closeup", "Product detail", "detail", TYPE_CLOSEUP, TRUST_SUPPORTING, POLICY_VERIFIED,
            ImportMediaCandidate.VIEW_CLOSEUP,
            "Show a close detail supported by the manufacturer references.",
            creative_allowed=True,
            creative_prompt="Create a close product-detail image using only visible identity cues from the exact references.",
        ),
        _slot(
            "setup", "Setup / context scene", "context", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE,
            ImportMediaCandidate.VIEW_TOP,
            "Show the exact device in a useful setup/context scene.",
            creative_allowed=True,
            creative_prompt="Create a clean setup scene that demonstrates context without making unverified technical claims.",
        ),
    ),
)


FASHION = MediaProfile(
    key="fashion",
    label="Clothing / fashion",
    slots=(
        _slot("hero", "Main / hero", "hero", TYPE_PRODUCT, TRUST_EXACT, POLICY_VERIFIED, ImportMediaCandidate.VIEW_MAIN,
              "Show the exact garment as the primary clean fashion image."),
        _slot("front", "Front full view", "factual_primary", TYPE_PRODUCT, TRUST_EXACT, POLICY_VERIFIED, ImportMediaCandidate.VIEW_FRONT,
              "Show the exact garment from the front."),
        _slot("back", "Back view", "factual_secondary", TYPE_PRODUCT, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_BACK,
              "Show the garment back only when supported by evidence.",
              creative_allowed=True,
              creative_prompt="Create a tasteful rear fashion presentation while avoiding invented logos, seams, pockets, labels, or closures."),
        _slot("fabric", "Fabric / texture detail", "material_detail", TYPE_CLOSEUP, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_CLOSEUP,
              "Show a truthful fabric, texture, stitching, or finish detail.",
              creative_allowed=True,
              creative_prompt="Create a material-detail image based on visible texture; do not invent fabric composition or labels."),
        _slot("model", "Model wearing item", "model_worn", TYPE_MODEL_WORN, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_LIFESTYLE,
              "Show the exact garment naturally worn by a model.",
              creative_allowed=True,
              creative_prompt="Create a tasteful model-worn fashion scene preserving the garment's visible color, pattern, silhouette, and branding."),
        _slot("styling", "Styled outfit scene", "lifestyle", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_LEFT,
              "Create a styled outfit/lifestyle scene.",
              creative_allowed=True,
              creative_prompt="Create an attractive styling scene built around the exact garment."),
        _slot("fit", "Fit / movement scene", "usage", TYPE_MODEL_WORN, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_RIGHT,
              "Show how the garment looks in a natural pose or movement.",
              creative_allowed=True,
              creative_prompt="Create a natural fit/movement scene. Do not imply precise sizing or measurements that were not verified."),
        _slot("variant", "Alternate color / styling", "creative_support", TYPE_CONCEPT, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_SIDE,
              "Create a supporting fashion presentation without inventing an unavailable color variant.",
              creative_allowed=True,
              creative_prompt="Create an alternate styling presentation using the same verified garment color and design unless a variant is verified."),
        _slot("label", "Label / packaging detail", "package_or_extra", TYPE_PACKAGING, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_PACKAGE,
              "Show labels or packaging only when verified.",
              creative_allowed=True,
              creative_prompt="Create a neutral folded/boxed presentation without inventing brand labels, care text, size tags, or packaging claims."),
        _slot("editorial", "Editorial creative", "creative_support", TYPE_CONCEPT, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_TOP,
              "Create a premium editorial fashion image.",
              creative_allowed=True,
              creative_prompt="Create a premium editorial fashion visual with the exact garment as the clear focus."),
    ),
)


FOOTWEAR = MediaProfile(
    key="footwear",
    label="Shoes / footwear",
    slots=(
        _slot("hero", "Main / hero", "hero", TYPE_PRODUCT, TRUST_EXACT, POLICY_VERIFIED, ImportMediaCandidate.VIEW_MAIN,
              "Show the exact footwear as the clean hero image."),
        _slot("side", "Side profile", "factual_primary", TYPE_PRODUCT, TRUST_EXACT, POLICY_VERIFIED, ImportMediaCandidate.VIEW_SIDE,
              "Show the exact shoe side profile."),
        _slot("top", "Top view", "factual_secondary", TYPE_PRODUCT, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_TOP,
              "Show the exact shoe from above when evidence supports it.",
              creative_allowed=True,
              creative_prompt="Create a top-inspired presentation without inventing lacing, tongue labels, stitching, or materials."),
        _slot("heel", "Heel / rear", "detail", TYPE_CLOSEUP, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_BACK,
              "Show the verified heel/rear design.",
              creative_allowed=True,
              creative_prompt="Create a heel-focused presentation while avoiding invented rear logos, stitching, or construction details."),
        _slot("sole", "Sole / outsole", "technical_detail", TYPE_CLOSEUP, TRUST_EXACT, POLICY_VERIFIED, ImportMediaCandidate.VIEW_PORTS,
              "Show the actual outsole only when directly supported by evidence.",
              requires_specifications=False),
        _slot("on_foot", "On-foot lifestyle", "model_worn", TYPE_MODEL_WORN, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_LIFESTYLE,
              "Show the exact footwear naturally worn.",
              creative_allowed=True,
              creative_prompt="Create a realistic on-foot lifestyle scene preserving the shoe's visible design and color."),
        _slot("material", "Material close-up", "material_detail", TYPE_CLOSEUP, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_CLOSEUP,
              "Show a visible material/construction detail.",
              creative_allowed=True,
              creative_prompt="Create a material detail based only on visible texture and construction."),
        _slot("box", "Box / packaging", "package_or_extra", TYPE_PACKAGING, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_PACKAGE,
              "Show verified shoe packaging only.",
              creative_allowed=True,
              creative_prompt="Show the exact footwear beside a plain closed unbranded shoe box; do not invent box labels or included extras."),
        _slot("street", "Street / styling scene", "lifestyle", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_LEFT,
              "Create a styling scene.",
              creative_allowed=True,
              creative_prompt="Create an attractive street/styling scene featuring the exact footwear."),
        _slot("premium", "Premium creative", "creative_support", TYPE_CONCEPT, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_RIGHT,
              "Create a premium supporting footwear image.",
              creative_allowed=True,
              creative_prompt="Create a premium studio or environmental footwear presentation."),
    ),
)


WATCHES = MediaProfile(
    key="watches_jewelry",
    label="Watches / jewelry",
    slots=(
        _slot("hero", "Main / hero", "hero", TYPE_PRODUCT, TRUST_EXACT, POLICY_VERIFIED, ImportMediaCandidate.VIEW_MAIN,
              "Show the exact watch or jewelry item as the hero."),
        _slot("dial", "Dial / face", "factual_primary", TYPE_CLOSEUP, TRUST_EXACT, POLICY_VERIFIED, ImportMediaCandidate.VIEW_FRONT,
              "Show the exact dial/face or primary front design."),
        _slot("profile", "Side profile", "factual_secondary", TYPE_PRODUCT, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_SIDE,
              "Show the side profile only when supported.",
              creative_allowed=True,
              creative_prompt="Create a side-inspired premium presentation; avoid inventing crown, buttons, engraving, stones, or case geometry."),
        _slot("caseback", "Caseback / rear", "technical_detail", TYPE_TECHNICAL, TRUST_EXACT, POLICY_VERIFIED, ImportMediaCandidate.VIEW_BACK,
              "Show the actual rear/caseback only when verified."),
        _slot("strap", "Strap / clasp detail", "detail", TYPE_CLOSEUP, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_CLOSEUP,
              "Show a verified strap, clasp, bracelet, or material detail.",
              creative_allowed=True,
              creative_prompt="Create a tasteful strap/material detail without inventing clasp mechanisms or markings."),
        _slot("wrist", "On-wrist lifestyle", "model_worn", TYPE_MODEL_WORN, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_LIFESTYLE,
              "Show the exact item naturally worn.",
              creative_allowed=True,
              creative_prompt="Create a premium on-wrist lifestyle scene preserving the exact visible product identity."),
        _slot("crown", "Crown / control detail", "detail_secondary", TYPE_CLOSEUP, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_TOP,
              "Show verified crown/control details only.",
              creative_allowed=True,
              creative_prompt="Create a detail-oriented view without inventing controls, engravings, stones, or markings."),
        _slot("box", "Box / presentation", "package_or_extra", TYPE_PACKAGING, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_PACKAGE,
              "Show verified packaging/presentation material only.",
              creative_allowed=True,
              creative_prompt="Create a neutral premium presentation beside a plain closed unbranded box."),
        _slot("styled", "Styled premium scene", "lifestyle", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_LEFT,
              "Create a premium styled scene.",
              creative_allowed=True,
              creative_prompt="Create a premium styled scene appropriate to watches or jewelry."),
        _slot("creative", "3D-style creative", "creative_support", TYPE_CONCEPT, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_RIGHT,
              "Create a premium 3D-style supporting visual.",
              creative_allowed=True,
              creative_prompt="Create a high-end 3D-style product visual while avoiding unsupported engravings, mechanisms, or material claims."),
    ),
)


EYEWEAR = MediaProfile(
    key="eyewear",
    label="Eyeglasses / eyewear",
    slots=(
        _slot("hero", "Main / hero", "hero", TYPE_PRODUCT, TRUST_EXACT, POLICY_VERIFIED, ImportMediaCandidate.VIEW_MAIN,
              "Show the exact eyewear as the hero image."),
        _slot("front", "Front frame", "factual_primary", TYPE_PRODUCT, TRUST_EXACT, POLICY_VERIFIED, ImportMediaCandidate.VIEW_FRONT,
              "Show the exact frame from the front."),
        _slot("side", "Temple / side", "factual_secondary", TYPE_PRODUCT, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_SIDE,
              "Show the temple/side only when supported.",
              creative_allowed=True,
              creative_prompt="Create a side-inspired eyewear presentation without inventing hinge, temple branding, or hardware."),
        _slot("folded", "Folded / alternate view", "detail", TYPE_PRODUCT, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_LEFT,
              "Show a verified folded/alternate frame view.",
              creative_allowed=True,
              creative_prompt="Create a tasteful folded/alternate presentation grounded in the visible frame design."),
        _slot("hinge", "Hinge / frame detail", "detail_secondary", TYPE_CLOSEUP, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_CLOSEUP,
              "Show a visible frame or hinge detail only when supported.",
              creative_allowed=True,
              creative_prompt="Create a frame-detail close-up without inventing hinge mechanisms or markings."),
        _slot("on_face", "On-face model", "model_worn", TYPE_MODEL_WORN, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_LIFESTYLE,
              "Show the exact eyewear naturally worn by a model.",
              creative_allowed=True,
              creative_prompt="Create a tasteful on-face model image preserving the visible frame color, silhouette, and lens shape."),
        _slot("case", "Case / packaging", "package_or_extra", TYPE_PACKAGING, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_PACKAGE,
              "Show verified case/packaging only.",
              creative_allowed=True,
              creative_prompt="Show the exact eyewear beside a plain closed unbranded case; do not invent branded packaging."),
        _slot("styled", "Styled lifestyle", "lifestyle", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_RIGHT,
              "Create a styled eyewear scene.",
              creative_allowed=True,
              creative_prompt="Create an attractive eyewear lifestyle scene with the exact frame identity."),
        _slot("detail", "Lens / bridge detail", "material_detail", TYPE_CLOSEUP, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_TOP,
              "Show verified lens, bridge, or frame detail.",
              creative_allowed=True,
              creative_prompt="Create a clean lens/bridge detail without making unverified coating, prescription, or material claims."),
        _slot("creative", "Creative support", "creative_support", TYPE_CONCEPT, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_BACK,
              "Create a final premium creative eyewear visual.",
              creative_allowed=True,
              creative_prompt="Create a premium supporting eyewear visual with no unverified technical claims."),
    ),
)


FURNITURE = MediaProfile(
    key="furniture_home",
    label="Furniture / home",
    slots=(
        _slot("hero", "Main / hero", "hero", TYPE_PRODUCT, TRUST_EXACT, POLICY_VERIFIED, ImportMediaCandidate.VIEW_MAIN,
              "Show the exact furniture/home item as the hero."),
        _slot("front", "Primary product view", "factual_primary", TYPE_PRODUCT, TRUST_EXACT, POLICY_VERIFIED, ImportMediaCandidate.VIEW_FRONT,
              "Show the exact item clearly."),
        _slot("angle", "Alternate angle", "factual_secondary", TYPE_PRODUCT, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_LEFT,
              "Show another factual angle only when supported.",
              creative_allowed=True,
              creative_prompt="Create an alternate presentation while avoiding invented drawers, handles, seams, joints, dimensions, or hardware."),
        _slot("detail", "Material / finish detail", "material_detail", TYPE_CLOSEUP, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_CLOSEUP,
              "Show a material/finish detail visible in the references.",
              creative_allowed=True,
              creative_prompt="Create a material/finish close-up without inventing material composition or construction."),
        _slot("room", "Room lifestyle", "lifestyle", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_LIFESTYLE,
              "Place the exact item naturally in a suitable room.",
              creative_allowed=True,
              creative_prompt="Create a tasteful room lifestyle scene with the exact item as the focus."),
        _slot("styled", "Styled room scene", "context", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_RIGHT,
              "Create a second styled/context scene.",
              creative_allowed=True,
              creative_prompt="Create a premium styled room scene without implying unverified dimensions or included decor."),
        _slot("scale", "Use / scale scene", "usage", TYPE_SCENE, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_SIDE,
              "Show the item in natural use or human scale.",
              creative_allowed=True,
              creative_prompt="Create a realistic use/scale scene. Do not imply exact measurements unless verified."),
        _slot("rear", "Rear / construction detail", "detail_secondary", TYPE_PRODUCT, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_BACK,
              "Show rear/construction details only when supported.",
              creative_allowed=True,
              creative_prompt="Create a rear-inspired visual while keeping unsupported construction details obscured or simplified."),
        _slot("package", "Package / assembly extra", "package_or_extra", TYPE_PACKAGING, TRUST_SUPPORTING, POLICY_VERIFIED, ImportMediaCandidate.VIEW_PACKAGE,
              "Show verified packaging/assembly extras only.",
              creative_allowed=True,
              creative_prompt="Create a neutral package/assembly presentation without inventing included tools or hardware."),
        _slot("creative", "Design visualization", "creative_support", TYPE_CONCEPT, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_TOP,
              "Create a design-oriented supporting visual.",
              creative_allowed=True,
              creative_prompt="Create a premium design visualization grounded in the exact item's visible design."),
    ),
)


PROPERTY = MediaProfile(
    key="property",
    label="Property / real estate",
    notes=(
        "Actual property slots never use generative fallback. A separate concept-staging slot "
        "may be generated, but it must remain clearly conceptual."
    ),
    slots=(
        _slot("exterior", "Actual exterior / hero", "hero", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_MAIN,
              "Actual property exterior photo required.", representation_rule="actual_real_world"),
        _slot("exterior_alt", "Actual exterior alternate", "factual_secondary", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_FRONT,
              "Actual alternate exterior photo required.", representation_rule="actual_real_world"),
        _slot("living", "Actual living room", "interior", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_LEFT,
              "Actual living-room photo required.", representation_rule="actual_real_world"),
        _slot("kitchen", "Actual kitchen", "interior", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_RIGHT,
              "Actual kitchen photo required.", representation_rule="actual_real_world"),
        _slot("bedroom", "Actual bedroom", "interior", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_SIDE,
              "Actual bedroom photo required.", representation_rule="actual_real_world"),
        _slot("bathroom", "Actual bathroom", "interior", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_BACK,
              "Actual bathroom photo required.", representation_rule="actual_real_world"),
        _slot("compound", "Actual compound / parking", "context", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_TOP,
              "Actual compound/parking photo required.", representation_rule="actual_real_world"),
        _slot("floorplan", "Verified floor plan", "floorplan", TYPE_FLOORPLAN, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_CLOSEUP,
              "Verified seller/architect floor plan required.", representation_rule="documentary"),
        _slot("neighborhood", "Actual neighborhood / surroundings", "location_context", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_PACKAGE,
              "Actual surroundings/location-context media required.", representation_rule="actual_real_world"),
        _slot("concept", "Concept staging visualization", "concept_visualization", TYPE_CONCEPT, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_LIFESTYLE,
              "Create an optional concept-only staged visualization.",
              creative_allowed=True,
              creative_prompt=(
                  "Create a clearly conceptual interior/exterior staging visualization. "
                  "Do not represent it as an actual photograph of the listed property. "
                  "Do not invent bedrooms, facilities, views, roads, dimensions, location facts, ownership facts, or amenities."
              ),
              representation_rule="concept_only"),
    ),
)


LAND = MediaProfile(
    key="land",
    label="Land / plots",
    notes=(
        "Real land/location evidence must stay documentary. Only the final concept-development "
        "slot may use creative visualization."
    ),
    slots=(
        _slot("site", "Actual site / hero", "hero", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_MAIN,
              "Actual site photo required.", representation_rule="actual_real_world"),
        _slot("wide", "Actual wide land view", "factual_primary", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_FRONT,
              "Actual wide site photo required.", representation_rule="actual_real_world"),
        _slot("access", "Actual access road", "access", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_LEFT,
              "Actual access-road photo required.", representation_rule="actual_real_world"),
        _slot("boundary", "Actual boundary / markers", "boundary", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_RIGHT,
              "Actual boundary/marker evidence required.", representation_rule="actual_real_world"),
        _slot("surroundings", "Actual surroundings", "location_context", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_SIDE,
              "Actual surrounding-area photo required.", representation_rule="actual_real_world"),
        _slot("landmark", "Actual nearby landmark", "location_context", TYPE_PROPERTY, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_BACK,
              "Actual nearby-landmark evidence required.", representation_rule="actual_real_world"),
        _slot("survey", "Verified survey / layout", "survey", TYPE_FLOORPLAN, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_TOP,
              "Verified survey/layout document required.", representation_rule="documentary"),
        _slot("map", "Verified map / location graphic", "map", TYPE_MAP, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_PACKAGE,
              "Verified location/map material required.", representation_rule="documentary"),
        _slot("aerial", "Actual aerial / drone view", "aerial", TYPE_AERIAL, TRUST_ACTUAL, POLICY_ACTUAL_ONLY, ImportMediaCandidate.VIEW_CLOSEUP,
              "Actual aerial/drone media required.", representation_rule="actual_real_world"),
        _slot("concept", "Concept development visualization", "concept_visualization", TYPE_CONCEPT, TRUST_CREATIVE, POLICY_CREATIVE, ImportMediaCandidate.VIEW_LIFESTYLE,
              "Create an optional concept-only development visualization.",
              creative_allowed=True,
              creative_prompt=(
                  "Create a clearly conceptual future-development visualization for inspiration only. "
                  "Do not alter or assert actual boundaries, access roads, topography, plot dimensions, title status, "
                  "location, utilities, structures, neighborhood facts, or planning approvals."
              ),
              representation_rule="concept_only"),
    ),
)


PROFILES = {
    profile.key: profile
    for profile in (
        GENERIC,
        ELECTRONICS,
        FASHION,
        FOOTWEAR,
        WATCHES,
        EYEWEAR,
        FURNITURE,
        PROPERTY,
        LAND,
    )
}


CATEGORY_KEYWORDS = {
    "land": (
        "land", "plot", "plots", "acre", "acres", "hectare", "hectares",
        "residential plot", "commercial plot", "survey plan",
    ),
    "property": (
        "property", "properties", "real estate", "house", "home for sale",
        "apartment", "flat", "duplex", "bungalow", "villa", "townhouse",
        "office space", "warehouse property", "shop space", "rent apartment",
    ),
    "footwear": (
        "shoe", "shoes", "sneaker", "sneakers", "boot", "boots", "slipper",
        "slippers", "sandal", "sandals", "loafer", "loafers", "footwear",
        "heels", "trainer", "trainers",
    ),
    "eyewear": (
        "eyeglass", "eyeglasses", "glasses", "sunglass", "sunglasses",
        "spectacle", "spectacles", "optical frame", "eyewear",
    ),
    "watches_jewelry": (
        "watch", "watches", "wristwatch", "wrist watch", "smartwatch",
        "jewelry", "jewellery", "necklace", "bracelet", "ring", "earring",
        "pendant", "chain",
    ),
    "fashion": (
        "fashion", "clothing", "clothes", "shirt", "t-shirt", "tshirt",
        "dress", "gown", "trouser", "trousers", "jeans", "jacket", "blazer",
        "hoodie", "skirt", "shorts", "kaftan", "agbada", "native wear",
        "underwear", "uniform", "fabric", "apparel",
    ),
    "furniture_home": (
        "furniture", "sofa", "chair", "table", "desk", "bed", "wardrobe",
        "cabinet", "shelf", "shelves", "console", "mattress", "dining set",
        "home decor", "lamp", "lighting fixture",
    ),
    "electronics": (
        "electronics", "electronic", "camera", "webcam", "conference",
        "video conferencing", "computer", "laptop", "desktop", "monitor",
        "projector", "speaker", "headset", "headphone", "earbud", "microphone",
        "router", "switch", "keyboard", "mouse", "phone", "smartphone",
        "tablet", "television", "tv", "amplifier", "mixer", "printer",
        "scanner", "power bank", "charger", "ups", "inverter",
    ),
}


def _safe_name(obj):
    if obj is None:
        return ""
    return str(
        getattr(obj, "name", "")
        or getattr(obj, "title", "")
        or getattr(obj, "slug", "")
        or obj
        or ""
    ).strip()


def category_context(item):
    payload = getattr(item, "normalized_payload", None) or {}
    parts = []

    target_category = getattr(item, "target_category", None)
    if target_category is not None:
        parts.extend([
            _safe_name(target_category),
            str(getattr(target_category, "slug", "") or ""),
        ])

    created_product = getattr(item, "created_product", None)
    product_category = getattr(created_product, "category", None) if created_product is not None else None
    if product_category is not None:
        parts.extend([
            _safe_name(product_category),
            str(getattr(product_category, "slug", "") or ""),
        ])

    for key in (
        "category", "category_name", "subcategory", "subcategory_name",
        "product_type", "type", "name", "title",
    ):
        value = payload.get(key)
        if value:
            parts.append(str(value))

    return " ".join(parts).lower().replace("_", " ").replace("-", " ")


def detect_media_profile_key(item):
    text = category_context(item)

    # Real-estate profiles first because their factual-media policy is stricter.
    ordered = (
        "land",
        "property",
        "footwear",
        "eyewear",
        "watches_jewelry",
        "fashion",
        "furniture_home",
        "electronics",
    )
    for key in ordered:
        if any(keyword in text for keyword in CATEGORY_KEYWORDS[key]):
            return key
    return "generic"


def get_media_profile(item):
    key = detect_media_profile_key(item)
    return PROFILES.get(key, GENERIC)


def slot_metadata(profile, slot):
    return {
        "media_profile": profile.key,
        "media_profile_label": profile.label,
        "slot_key": slot.key,
        "display_label": slot.label,
        "universal_role": slot.universal_role,
        "media_type": slot.media_type,
        "trust_policy": slot.trust_policy,
        "generation_policy": slot.generation_policy,
        "creative_fallback_allowed": bool(slot.creative_allowed),
        "requires_specifications": bool(slot.requires_specifications),
        "representation_rule": slot.representation_rule,
        "slot_prompt": slot.prompt,
        "creative_prompt": slot.creative_prompt,
        "taxonomy_version": "5.1",
    }


def candidate_metadata(candidate):
    data = getattr(candidate, "metadata", None) or {}
    return data if isinstance(data, dict) else {}


def candidate_display_label(candidate):
    data = candidate_metadata(candidate)
    return str(
        data.get("display_label")
        or getattr(candidate, "get_view_role_display", lambda: "")()
        or getattr(candidate, "view_role", "")
        or "Media"
    )


def candidate_profile_label(candidate):
    data = candidate_metadata(candidate)
    return str(data.get("media_profile_label") or "Legacy media plan")


def candidate_generation_policy(candidate):
    data = candidate_metadata(candidate)
    return str(data.get("generation_policy") or POLICY_VERIFIED)


def candidate_creative_allowed(candidate):
    data = candidate_metadata(candidate)
    if "creative_fallback_allowed" in data:
        return bool(data.get("creative_fallback_allowed"))
    return True


def candidate_is_actual_only(candidate):
    return candidate_generation_policy(candidate) == POLICY_ACTUAL_ONLY


def candidate_is_intentional_creative(candidate):
    return candidate_generation_policy(candidate) == POLICY_CREATIVE


def candidate_representation_rule(candidate):
    data = candidate_metadata(candidate)
    return str(data.get("representation_rule") or "product")
