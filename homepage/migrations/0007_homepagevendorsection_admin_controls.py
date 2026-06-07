from django.db import migrations, models


DEFAULT_VENDOR_SECTIONS = [
    {
        "section_type": "verified_vendors",
        "title": "Verified Vendors",
        "description": "Trusted Arolana sellers across all vendor types.",
        "vendor_type_filter": "",
        "verified_only": True,
        "manufacturer_only": False,
        "max_items": 12,
        "sort_order": 10,
        "empty_state_text": "No verified vendors yet.",
        "view_all_url": "/vendors/?section=verified_vendors",
        "show_view_all": True,
        "show_when_empty": True,
        "is_active": True,
    },
    {
        "section_type": "factory_direct_manufacturers",
        "title": "Factory Direct Manufacturers",
        "description": "Verified factory-direct suppliers and manufacturers.",
        "vendor_type_filter": "manufacturer",
        "verified_only": True,
        "manufacturer_only": True,
        "max_items": 12,
        "sort_order": 20,
        "empty_state_text": "No verified manufacturers yet.",
        "view_all_url": "/vendors/?section=factory_direct_manufacturers",
        "show_view_all": True,
        "show_when_empty": False,
        "is_active": True,
    },
    {
        "section_type": "top_retailers",
        "title": "Top Retailers",
        "description": "Retail-ready sellers with verified Arolana stores.",
        "vendor_type_filter": "retailer",
        "verified_only": True,
        "manufacturer_only": False,
        "max_items": 12,
        "sort_order": 30,
        "empty_state_text": "No verified retailers yet.",
        "view_all_url": "/vendors/?section=top_retailers",
        "show_view_all": True,
        "show_when_empty": True,
        "is_active": True,
    },
    {
        "section_type": "distributors_wholesalers",
        "title": "Distributors & Wholesalers",
        "description": "Bulk supply partners for trade buyers.",
        "vendor_type_filter": "distributor_wholesaler",
        "verified_only": True,
        "manufacturer_only": False,
        "max_items": 12,
        "sort_order": 40,
        "empty_state_text": "No distributors or wholesalers yet.",
        "view_all_url": "/vendors/?section=distributors_wholesalers",
        "show_view_all": True,
        "show_when_empty": True,
        "is_active": True,
    },
    {
        "section_type": "service_providers",
        "title": "Service Providers",
        "description": "Verified service providers for business support.",
        "vendor_type_filter": "service_provider",
        "verified_only": True,
        "manufacturer_only": False,
        "max_items": 12,
        "sort_order": 50,
        "empty_state_text": "No service providers yet.",
        "view_all_url": "/vendors/?section=service_providers",
        "show_view_all": True,
        "show_when_empty": True,
        "is_active": True,
    },
]


def seed_homepage_vendor_sections(apps, schema_editor):
    HomepageVendorSection = apps.get_model("homepage", "HomepageVendorSection")
    for defaults in DEFAULT_VENDOR_SECTIONS:
        section = HomepageVendorSection.objects.filter(section_type=defaults["section_type"]).order_by("sort_order", "id").first()
        created = False
        if not section:
            section = HomepageVendorSection.objects.create(**defaults)
            created = True
        if created:
            continue

        changed = False
        for field, value in defaults.items():
            current = getattr(section, field, None)
            if field in {"title", "description", "empty_state_text", "view_all_url"}:
                if not current:
                    setattr(section, field, value)
                    changed = True
            elif field in {"vendor_type_filter", "manufacturer_only"}:
                if section.section_type == "factory_direct_manufacturers" and current != value:
                    setattr(section, field, value)
                    changed = True
            elif field == "sort_order" and current in (None, 0):
                setattr(section, field, value)
                changed = True
        if changed:
            section.save()


class Migration(migrations.Migration):

    dependencies = [
        ("homepage", "0006_homepagevendorsection"),
    ]

    operations = [
        migrations.AddField(
            model_name="homepagevendorsection",
            name="description",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="homepagevendorsection",
            name="show_view_all",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="homepagevendorsection",
            name="show_when_empty",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="homepagevendorsection",
            name="view_all_url",
            field=models.CharField(blank=True, default="/vendors/", max_length=500),
        ),
        migrations.RunPython(seed_homepage_vendor_sections, migrations.RunPython.noop),
    ]
