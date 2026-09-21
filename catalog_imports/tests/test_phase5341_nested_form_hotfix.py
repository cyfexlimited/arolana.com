from django.template.loader import get_template
from django.test import SimpleTestCase


class Phase5341NestedFormHotfixTests(SimpleTestCase):
    def test_downgrade_uses_formaction_not_nested_form(self):
        template = get_template(
            "admin/catalog_imports/importitem/media_review.html"
        )
        source = template.template.source

        marker = source.index("Weak visual verification?")
        block = source[marker:marker + 1700]

        self.assertIn(
            'formaction="{{ row.downgrade_manual_creative_url }}"',
            block,
        )
        self.assertIn('name="manual_creative_reason"', block)
        self.assertNotIn(
            '<form method="post" action="{{ row.downgrade_manual_creative_url }}"',
            block,
        )

    def test_downgrade_button_does_not_use_media_review_action_name(self):
        template = get_template(
            "admin/catalog_imports/importitem/media_review.html"
        )
        source = template.template.source

        marker = source.index("Weak visual verification?")
        block = source[marker:marker + 1700]

        self.assertIn(">Downgrade to manual creative</button>", block)
        self.assertNotIn('name="action" value="downgrade', block)
