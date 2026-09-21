from types import SimpleNamespace

from django.test import SimpleTestCase

from catalog_imports.services.media_profiles import (
    POLICY_ACTUAL_ONLY,
    POLICY_CREATIVE,
    TRUST_ACTUAL,
    detect_media_profile_key,
    get_media_profile,
    slot_metadata,
)


class Phase51MediaProfileTests(SimpleTestCase):
    def _item(self, *, category="", name=""):
        return SimpleNamespace(
            target_category=SimpleNamespace(name=category, slug=category.lower().replace(" ", "-")) if category else None,
            created_product=None,
            normalized_payload={"name": name, "category": category},
        )

    def test_electronics_profile_detects_conference_camera(self):
        item = self._item(category="Conference Camera", name="MeetUp 2")
        self.assertEqual(detect_media_profile_key(item), "electronics")

    def test_fashion_profile_detects_clothing(self):
        item = self._item(category="Clothing & Fashion", name="Men Shirt")
        self.assertEqual(detect_media_profile_key(item), "fashion")

    def test_footwear_profile_detects_shoes(self):
        item = self._item(category="Shoes", name="Leather Loafers")
        self.assertEqual(detect_media_profile_key(item), "footwear")

    def test_watches_and_eyewear_have_distinct_profiles(self):
        self.assertEqual(
            detect_media_profile_key(self._item(category="Wrist Watches", name="Classic Watch")),
            "watches_jewelry",
        )
        self.assertEqual(
            detect_media_profile_key(self._item(category="Eyeglasses", name="Optical Frame")),
            "eyewear",
        )

    def test_land_is_detected_before_property(self):
        item = self._item(category="Land & Properties", name="Residential plot of land")
        self.assertEqual(detect_media_profile_key(item), "land")

    def test_property_actual_slots_do_not_allow_ai_generation(self):
        profile = get_media_profile(self._item(category="Real Estate", name="4 Bedroom Duplex"))
        self.assertEqual(profile.key, "property")
        actual_slots = [slot for slot in profile.slots if slot.generation_policy == POLICY_ACTUAL_ONLY]
        self.assertTrue(actual_slots)
        self.assertTrue(all(slot.trust_policy == TRUST_ACTUAL for slot in actual_slots))

    def test_property_concept_slot_is_explicitly_creative(self):
        profile = get_media_profile(self._item(category="Real Estate", name="Apartment"))
        concept = [slot for slot in profile.slots if slot.key == "concept"][0]
        self.assertEqual(concept.generation_policy, POLICY_CREATIVE)
        self.assertEqual(concept.representation_rule, "concept_only")

    def test_slot_metadata_is_schema_free_taxonomy(self):
        profile = get_media_profile(self._item(category="Shoes", name="Sneaker"))
        data = slot_metadata(profile, profile.slots[0])
        self.assertEqual(data["taxonomy_version"], "5.1")
        self.assertEqual(data["media_profile"], "footwear")
        self.assertIn("universal_role", data)
        self.assertIn("media_type", data)
        self.assertIn("trust_policy", data)
