from django.test import SimpleTestCase

from catalog_imports.services.input_parser import parse_inputs


class InputParserTests(SimpleTestCase):
    def test_mixed_and_deduplicated(self):
        result = parse_inputs("https://example.com/a\nLogitech C920e\nhttps://example.com/a\n")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["kind"], "url")
        self.assertEqual(result[1]["kind"], "name")
