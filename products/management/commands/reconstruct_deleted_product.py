"""Dry-run-first reconstruction of one deleted Product and ProductVideo."""

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from products.models import Brand, Category, Product, ProductImage, ProductVideo
from social_publishing.models import SocialPlatform, SocialPublication
from vendors.models import VendorProfile


CONFIRMATION = "RECONSTRUCT_DELETED_PRODUCT"


class Command(BaseCommand):
    help = (
        "Validate a recovery manifest and optionally reconstruct a deleted Product/"
        "ProductVideo with new IDs. Dry-run is the default."
    )

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm", default="")

    def handle(self, *args, **options):
        manifest_path = Path(options["manifest"]).expanduser().resolve()
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError) as exc:
            raise CommandError(f"Could not read recovery manifest: {exc}") from exc

        plan = self._assess(manifest)
        if not options["apply"]:
            self.stdout.write(json.dumps(plan, indent=2, default=str, sort_keys=True))
            return

        if options["confirm"] != CONFIRMATION:
            raise CommandError(f"Apply requires --confirm {CONFIRMATION}")
        if plan["errors"]:
            raise CommandError("Recovery manifest is not safe to apply: " + "; ".join(plan["errors"]))

        result = self._apply(manifest)
        self.stdout.write(json.dumps(result, indent=2, default=str, sort_keys=True))

    def _assess(self, manifest):
        errors = []
        warnings = []
        evidence = manifest.get("evidence") or {}
        product_data = manifest.get("product") or {}
        video_data = manifest.get("video") or {}
        images = manifest.get("gallery_images") or []
        publication_data = manifest.get("social_publication") or {}

        old_product_id = evidence.get("deleted_product_id")
        old_video_id = evidence.get("deleted_product_video_id")
        if not old_product_id or Product.objects.filter(pk=old_product_id).exists():
            errors.append("Deleted Product ID is missing from the manifest or still exists.")
        if not old_video_id or ProductVideo.objects.filter(pk=old_video_id).exists():
            errors.append("Deleted ProductVideo ID is missing from the manifest or still exists.")

        required_product_fields = (
            "vendor_user_id", "vendor_email", "sku", "name", "description",
            "category_id", "price", "stock_quantity", "condition", "main_image",
            "approved_by_user_id", "approved_at",
        )
        for field in required_product_fields:
            if product_data.get(field) in (None, ""):
                errors.append(f"Product field {field!r} requires recovered or operator-supplied data.")

        required_video_fields = (
            "youtube_video_id", "youtube_url", "title", "description",
            "youtube_visibility", "vendor_profile_id", "approved_by_user_id", "approved_at",
        )
        for field in required_video_fields:
            if video_data.get(field) in (None, ""):
                errors.append(f"ProductVideo field {field!r} is required.")

        User = get_user_model()
        vendor = User.objects.filter(pk=product_data.get("vendor_user_id")).first()
        if not vendor or vendor.email.casefold() != str(product_data.get("vendor_email") or "").casefold():
            errors.append("Vendor user ID/email evidence does not match an existing user.")
        profile = VendorProfile.objects.filter(pk=video_data.get("vendor_profile_id")).first()
        if not profile or not vendor or profile.user_id != vendor.pk:
            errors.append("Vendor profile does not belong to the proven Product owner.")
        if product_data.get("category_id") and not Category.objects.filter(
            pk=product_data["category_id"]
        ).exists():
            errors.append("Operator-supplied category does not exist.")
        if product_data.get("brand_id") and not Brand.objects.filter(
            pk=product_data["brand_id"]
        ).exists():
            errors.append("Operator-supplied brand does not exist.")
        if product_data.get("approved_by_user_id") and not User.objects.filter(
            pk=product_data["approved_by_user_id"], is_staff=True
        ).exists():
            errors.append("Product approver is missing or is not staff.")
        if video_data.get("approved_by_user_id") and not User.objects.filter(
            pk=video_data["approved_by_user_id"], is_staff=True
        ).exists():
            errors.append("ProductVideo approver is missing or is not staff.")

        try:
            price = Decimal(str(product_data.get("price")))
            if price <= 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            errors.append("Operator-supplied price must be greater than zero.")
        try:
            if int(product_data.get("stock_quantity")) < 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("Operator-supplied stock_quantity must be a non-negative integer.")
        if product_data.get("condition") not in dict(Product.PRODUCT_CONDITION_CHOICES):
            errors.append("Operator-supplied condition is invalid.")
        if product_data.get("approved_at") and not parse_datetime(str(product_data["approved_at"])):
            errors.append("Product approved_at must be an ISO-8601 timestamp.")
        if video_data.get("approved_at") and not parse_datetime(str(video_data["approved_at"])):
            errors.append("ProductVideo approved_at must be an ISO-8601 timestamp.")
        if video_data.get("youtube_visibility") not in {"public", "unlisted"}:
            errors.append("ProductVideo youtube_visibility must be public or unlisted.")

        if Product.objects.filter(sku=product_data.get("sku")).exists():
            errors.append("Recovered SKU is already in use.")
        if ProductVideo.objects.filter(
            youtube_video_id=video_data.get("youtube_video_id")
        ).exists():
            errors.append("The recovered YouTube video ID is already attached to ProductVideo.")

        media = [product_data.get("main_image")] + [item.get("file_name") for item in images]
        media_checks = []
        for file_name in filter(None, media):
            exists = default_storage.exists(file_name)
            media_checks.append({"file_name": file_name, "exists": exists})
            if not exists:
                errors.append(f"Recovered media object is missing: {file_name}")

        publication = None
        publication_id = publication_data.get("id")
        if publication_id:
            publication = SocialPublication.objects.filter(pk=publication_id).first()
            expected_type = ContentType.objects.get_for_model(
                ProductVideo, for_concrete_model=False
            )
            if not publication:
                errors.append("Recovery publication does not exist.")
            else:
                if publication.content_type_id != expected_type.pk or publication.object_id != old_video_id:
                    errors.append("Publication does not reference the deleted ProductVideo evidence.")
                if publication.content_object is not None:
                    errors.append("Publication is not orphaned; refusing to remap it.")
                if not vendor or publication.owner_user_id != vendor.pk:
                    errors.append("Publication owner does not match the proven vendor.")
                if publication.owner_role != "vendor" or publication.platform != SocialPlatform.INSTAGRAM:
                    errors.append("Publication role/platform does not match the recovery evidence.")
                expected_external_id = str(publication_data.get("external_id") or "")
                if expected_external_id and publication.external_id != expected_external_id:
                    errors.append("Publication external media ID does not match the manifest.")
                if publication.status == "pending":
                    warnings.append(
                        "Pending publication may be remapped, but this command never publishes it. "
                        "A separate reviewed moderation action is required."
                    )
                else:
                    warnings.append(
                        f"Publication {publication.pk} is {publication.status}; remapping restores "
                        "audit linkage and never republishes externally."
                    )

        return {
            "mode": "dry-run",
            "ready_to_apply": not errors,
            "errors": errors,
            "warnings": warnings,
            "would_create": {
                "product": 1,
                "product_video": 1,
                "product_images": len(images),
                "forced_primary_keys": False,
            },
            "would_reattach_social_publication": publication.pk if publication else None,
            "would_publish_externally": False,
            "media_checks": media_checks,
            "unrecoverable_fields_must_be_operator_supplied": [
                "category_id", "brand_id (optional)", "price", "stock_quantity", "condition",
                "manufacturer_sku (optional)", "specifications (optional)",
            ],
        }

    @transaction.atomic
    def _apply(self, manifest):
        product_data = manifest["product"]
        video_data = manifest["video"]
        images = manifest.get("gallery_images") or []
        publication_data = manifest.get("social_publication") or {}
        User = get_user_model()

        product = Product.objects.create(
            vendor_id=product_data["vendor_user_id"],
            category_id=product_data["category_id"],
            brand_id=product_data.get("brand_id"),
            sku=product_data["sku"],
            manufacturer_sku=product_data.get("manufacturer_sku", ""),
            name=product_data["name"],
            slug=Product.build_unique_slug(
                name=product_data["name"],
                vendor=User.objects.get(pk=product_data["vendor_user_id"]),
                requested_slug=product_data.get("slug") or product_data["name"],
            ),
            condition=product_data["condition"],
            description=product_data["description"],
            specifications=product_data.get("specifications") or "",
            price=Decimal(str(product_data["price"])),
            stock_quantity=int(product_data["stock_quantity"]),
            main_image=product_data["main_image"],
            video_type="youtube",
            video_url=video_data["youtube_url"],
            approval_status="approved",
            approved_by_id=product_data["approved_by_user_id"],
            approved_at=parse_datetime(str(product_data["approved_at"])),
            is_active=True,
        )

        created_images = []
        for index, item in enumerate(images):
            created_images.append(
                ProductImage.objects.create(
                    product=product,
                    image=item["file_name"],
                    alt_text=item.get("alt_text") or product.name,
                    is_main=False,
                    order=int(item.get("order", index)),
                ).pk
            )

        video = ProductVideo.objects.create(
            product=product,
            vendor_id=video_data["vendor_profile_id"],
            title=video_data["title"],
            description=video_data["description"],
            source="youtube",
            youtube_url=video_data["youtube_url"],
            youtube_video_id=video_data["youtube_video_id"],
            youtube_visibility=video_data["youtube_visibility"],
            moderation_status="approved",
            approved_by_id=video_data["approved_by_user_id"],
            approved_at=parse_datetime(str(video_data["approved_at"])),
            duration_seconds=int(video_data.get("duration_seconds") or 0),
            is_active=True,
        )

        publication_id = publication_data.get("id")
        if publication_id:
            publication = SocialPublication.objects.select_for_update().get(pk=publication_id)
            publication.content_type = ContentType.objects.get_for_model(
                ProductVideo, for_concrete_model=False
            )
            publication.object_id = video.pk
            publication.save(update_fields=["content_type", "object_id", "updated_at"])

        return {
            "applied": True,
            "product_id": product.pk,
            "product_video_id": video.pk,
            "product_image_ids": created_images,
            "reattached_social_publication_id": publication_id,
            "published_externally": False,
        }
