from django.test import SimpleTestCase

from catalog_imports.models import ImportMediaCandidate
from catalog_imports.services.media_prompts import MediaPromptHold, build_generation_prompt


class DummyItem:
    identity_verified = True
    specifications_verified = True
    normalized_payload = {
        "name": "MeetUp 2 Video Conferencing Camera",
        "brand": "Logitech",
        "manufacturer_sku": "960-001681",
        "specifications": {
            "HDMI Out": "1",
            "USB": "1 x Type C USB 3.1",
            "Network": "10/100/1G Ethernet",
        },
        "package_contents": ["MeetUp 2", "Power supply", "Mount"],
    }


class DummyCandidate:
    view_role = ImportMediaCandidate.VIEW_PORTS


class Phase5PromptTests(SimpleTestCase):
    def test_prompt_is_exact_product_and_blocks_retailer_identity(self):
        prompt = build_generation_prompt(DummyItem(), DummyCandidate())
        self.assertIn("960-001681", prompt)
        self.assertIn("Do not copy or include retailer identity", prompt)
        self.assertIn("Do not invent ports", prompt)
        self.assertIn("HDMI Out", prompt)

    def test_package_view_requires_verified_contents(self):
        item = DummyItem()
        item.normalized_payload = dict(DummyItem.normalized_payload)
        item.normalized_payload["package_contents"] = []
        candidate = DummyCandidate()
        candidate.view_role = ImportMediaCandidate.VIEW_PACKAGE
        with self.assertRaises(MediaPromptHold):
            build_generation_prompt(item, candidate)
