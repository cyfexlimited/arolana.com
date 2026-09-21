# Arolana Universal Product Importer — Phase 4

Phase 4 turns a fully verified Import Item into a safe Arolana Product draft.

## Safety invariants

- Existing `products` / vendor / storefront code is not rewritten.
- New products are created through the existing `Product.save()` path.
- Imported Products are created with `approval_status="draft"`, `is_active=False`, and stock `0`.
- Exact duplicate matches block creation; no second Product is created.
- Retailer/source branding is not copied into generated storefront content.
- Exact structured specification data is required before draft creation.
- Shipping information is not created from model defaults when delivery evidence is absent.
- Warranty defaults are not invented; no verified warranty means `warranty_years=0` on the draft.
- Media references and generation jobs are separate from Product images.
- Up to 10 image-generation jobs can be planned.
- Official manufacturer images are reference-only until rights are confirmed.
- Only media that is explicitly approved, exact-product verified, watermark-clear, and rights-confirmed can be attached to ProductImage.
- No Phase 4 action approves or publishes a Product.

## New admin workflow

1. Verify identity, specifications and price.
2. Select/resolve Draft destination vendor/category/brand.
3. Click **Prepare Arolana draft**.
4. Confirm the draft action.
5. Review the Product draft in normal Arolana Products admin.
6. Review media candidates / planned image jobs.
7. Upload or fulfil generated images through a provider in a later provider integration.
8. Mark only exact, clean, rights-confirmed media Approved + Selected.
9. Click **Attach approved media**.
10. Final Product approval remains in Arolana's existing approval system.

## Image generation

Phase 4 creates provider-neutral image generation jobs with exact-product prompts and manufacturer reference URLs. It does **not** hard-code one AI image provider or API key. That keeps the importer universal and prevents product imagery from being generated/published without a configured provider and review gate.


## Phase 4.1 upload-safety note
Review-stage media candidates deliberately do not add a new Django ImageField/FileField.
Arolana's private-upload audit requires every upload field to have an explicit public/private policy.
Candidate assets therefore remain provider-neutral storage references until a later media provider/private-review
storage step materializes them. Only after explicit approval, exact identity verification, watermark clearance
and rights confirmation are bytes copied into the existing protected ProductImage/main_image fields.
