from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase

from products.models import Category

from .content_i18n import get_request_language, translated_field, translated_key
from .models import ContentTranslation


class ContentTranslationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.category = Category.objects.create(
            name="Audio Visual",
            slug="audio-visual-i18n-test",
            description="Professional displays and conferencing.",
        )

    def test_accept_language_translates_model_content(self):
        ContentTranslation.objects.create(
            content_object=self.category,
            language_code="yo",
            field_name="name",
            translated_text="Ohun afetigbọ ati wiwo",
        )
        request = self.factory.get("/", HTTP_ACCEPT_LANGUAGE="yo-NG,yo;q=0.9,en;q=0.8")
        self.assertEqual(get_request_language(request), "yo")
        self.assertEqual(
            translated_field(self.category, "name", request=request),
            "Ohun afetigbọ ati wiwo",
        )

    def test_missing_translation_falls_back_to_english_source(self):
        request = self.factory.get("/", HTTP_ACCEPT_LANGUAGE="ig")
        self.assertEqual(
            translated_field(self.category, "description", request=request),
            self.category.description,
        )

    def test_shared_translation_key_and_english_fallback(self):
        ContentTranslation.objects.create(
            translation_key="product.condition.brand_new",
            language_code="ha",
            translated_text="Sabo",
        )
        self.assertEqual(
            translated_key(
                "product.condition.brand_new",
                "Brand New",
                language_code="ha",
            ),
            "Sabo",
        )
        self.assertEqual(
            translated_key(
                "unknown.translation.key",
                "English fallback",
                language_code="fr",
            ),
            "English fallback",
        )
