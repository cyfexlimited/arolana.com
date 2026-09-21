# Arolana Universal Product Importer — Phase 1

This is a **new standalone Django app**. It does not replace or rewrite the existing `products` app.

## What Phase 1 contains

- `ImportSource`: configurable source websites/APIs.
- `ImportPricingRule`: editable fixed/percentage/combined pricing rules.
- `ImportBatch`: one admin import job.
- `ImportItem`: one product candidate inside a batch.
- `ImportAuditEvent`: trace of importer decisions.
- `UniversalProductDraft`: source-neutral intermediate product schema.
- Pricing engine.
- Source-brand contamination scanner.
- Baseline quality checks.
- Extractor registry.
- Generic Schema.org Product JSON-LD extractor.
- Basic tests.

## What Phase 1 intentionally does NOT do yet

- It does not change `products/models.py`, vendor listing forms, storefront, cart, or checkout.
- It does not publish products automatically.
- It does not scrape around anti-bot controls.
- It does not copy watermarked images.
- It does not generate images yet.
- It does not include Paykobo-specific parsing yet.

Those belong to later phases after this foundation is installed and tested.

## Minimal integration required

The project must register the new app in Django settings:

```python
INSTALLED_APPS = [
    # existing apps...
    "catalog_imports.apps.CatalogImportsConfig",
]
```

This is an integration registration only; it does not alter the existing products logic.

Then run:

```bash
python manage.py makemigrations catalog_imports
python manage.py migrate
python manage.py test catalog_imports
```

## Initial Arolana pricing rule

Create this in **Admin → Product Importer → Import pricing rules**:

- Name: `Default +₦50,000`
- Active: Yes
- Priority: `100`
- Fixed markup: `50000.00`
- Percentage markup: `0`
- Rounding: `No rounding`
- Leave source/brand/category/product selectors blank to make it global.

You can change the rule from Admin later without changing code.

## Architecture guarantee

All websites are converted into `UniversalProductDraft`. The final publishing service (Phase 3) will convert a verified draft into the existing Arolana `Product` and related models using their normal save/validation behavior.
