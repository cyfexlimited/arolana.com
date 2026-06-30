from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError

from core.content_i18n import normalize_language_code
from core.models import ContentTranslation


TRANSLATABLE_MODELS = {
    "products.Product": ("name", "description", "specifications"),
    "products.Category": ("name", "description", "hero_title", "hero_subtitle"),
    "hero_banners.HeroBanner": (
        "title", "subtitle", "description", "button1_text", "button2_text", "button3_text",
    ),
    "homepage.HomepageBanner": ("title", "subtitle", "button_text"),
    "subscriptions.SubscriptionPlan": (
        "display_name", "description", "feature_bullets",
    ),
    "pages.Page": ("title", "content", "sidebar_content", "meta_description"),
    "pages.FAQ": ("question", "answer"),
    "pages.SupportArticle": ("title", "content"),
    "smartchat.AIKnowledgeBase": ("question", "answer"),
    "smartchat.AITrainingData": ("question", "answer"),
    "installers.ServiceCategory": ("name", "description"),
    "installers.ProviderService": ("service_name", "description"),
    "vendors.VendorProfile": (
        "description", "store_slogan", "business_hours", "return_policy",
        "warranty_note", "delivery_note",
    ),
}


class Command(BaseCommand):
    help = "Report missing active database translations for a selected language."

    def add_arguments(self, parser):
        parser.add_argument("--language", required=True)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--fail-on-missing", action="store_true")

    def handle(self, *args, **options):
        language = normalize_language_code(options["language"])
        if language == "en":
            self.stdout.write(self.style.SUCCESS("English is the source/fallback language."))
            return

        missing = []
        limit = max(0, options["limit"])
        for model_label, field_names in TRANSLATABLE_MODELS.items():
            model = apps.get_model(model_label)
            content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
            queryset = model._default_manager.all()
            if any(field.name == "is_active" for field in model._meta.fields):
                queryset = queryset.filter(is_active=True)
            if limit:
                queryset = queryset[:limit]

            for obj in queryset.iterator() if not limit else queryset:
                translated_fields = set(
                    ContentTranslation.objects.filter(
                        content_type=content_type,
                        object_id=obj.pk,
                        language_code=language,
                        is_active=True,
                    ).values_list("field_name", flat=True)
                )
                for field_name in field_names:
                    source = getattr(obj, field_name, "")
                    if source not in (None, "", [], {}) and field_name not in translated_fields:
                        missing.append(f"{model_label} #{obj.pk}.{field_name}")

        if missing:
            for item in missing[:200]:
                self.stdout.write(f"MISSING {language}: {item}")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(missing)} source field(s) do not yet have an active {language} translation."
                )
            )
            if options["fail_on_missing"]:
                raise CommandError("Database content translation audit failed.")
        else:
            self.stdout.write(self.style.SUCCESS(f"Database content is complete for {language}."))
