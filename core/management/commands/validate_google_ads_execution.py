import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ads.execution import external_campaign_execution_service
from ads.models import AdCampaign, AdChannelExecution, ExternalAdvertisingAccount
from ads.providers import ProviderAPIError, ProviderAuthorizationError, provider_for


class Command(BaseCommand):
    help = "Validate Google Ads execution against an allowlisted test account only."

    def add_arguments(self, parser):
        parser.add_argument("--campaign-id", required=True, type=int)
        parser.add_argument("--external-account-id", required=True, type=int)
        parser.add_argument("--staff-user-id", required=True, type=int)
        parser.add_argument("--confirm-test-mode", action="store_true")
        parser.add_argument("--create", action="store_true")
        parser.add_argument("--sync", action="store_true")
        parser.add_argument("--reporting", action="store_true")
        parser.add_argument("--pause", action="store_true")
        parser.add_argument("--recover-name")
        parser.add_argument("--start-date")
        parser.add_argument("--end-date")

    def handle(self, *args, **options):
        if options.get("recover_name") and any(options.get(action) for action in ("create", "sync", "reporting", "pause")):
            raise CommandError("--recover-name is read-only and cannot be combined with other actions.")
        if not options["confirm_test_mode"]:
            raise CommandError("--confirm-test-mode is required.")
        if not getattr(settings, "ADS_EXTERNAL_CAMPAIGN_TEST_MODE_ENABLED", False):
            raise CommandError("ADS_EXTERNAL_CAMPAIGN_TEST_MODE_ENABLED is disabled.")
        staff_user = get_user_model().objects.get(pk=options["staff_user_id"])
        if not staff_user.is_staff:
            raise CommandError("--staff-user-id must reference an authorized staff/admin user.")

        campaign = AdCampaign.objects.select_related("advertiser_identity").get(pk=options["campaign_id"])
        account = ExternalAdvertisingAccount.objects.get(
            pk=options["external_account_id"],
            advertiser_identity=campaign.advertiser_identity,
            channel=ExternalAdvertisingAccount.CHANNEL_GOOGLE,
        )
        allowlist = set(getattr(settings, "ADS_GOOGLE_TEST_ACCOUNT_ALLOWLIST", []) or [])
        if str(account.external_account_id) not in allowlist:
            raise CommandError("External Google account is not allowlisted for test execution.")

        result = external_campaign_execution_service.preview(campaign, "google", account)
        self.stdout.write(self.style.SUCCESS("Dry-run preview completed."))
        self.stdout.write(f"valid={result.valid} objective={result.objective}")
        if result.errors:
            self.stdout.write(f"errors={','.join(result.errors)}")
        if result.warnings:
            self.stdout.write(f"warnings={','.join(result.warnings)}")
        if not result.valid:
            raise CommandError("Preview validation failed; refusing live test mutation.")

        execution = (
            AdChannelExecution.objects
            .filter(campaign=campaign, channel="google", external_account=account)
            .first()
        )
        if options["create"]:
            execution, create_result = external_campaign_execution_service.create_execution(
                campaign,
                "google",
                account,
                dry_run=False,
                user=staff_user,
            )
            if create_result.errors:
                raise CommandError(f"Create refused/failed: {','.join(create_result.errors)}")
            self.stdout.write(self.style.SUCCESS(f"Created/read back Google campaign {execution.external_campaign_id}; status={execution.external_status}"))
        if not execution:
            raise CommandError("No Google execution exists yet. Run with --create first or create via staff UI.")

        adapter = provider_for("google")
        try:
            if options.get("recover_name"):
                matches = adapter.find_campaign_by_name(execution, options["recover_name"])
                self.stdout.write(json.dumps({"matches": matches}, sort_keys=True))
                return
            if options["sync"]:
                execution = external_campaign_execution_service.sync_status(execution)
                self.stdout.write(self.style.SUCCESS(f"Synced status={execution.status} external_status={execution.external_status}"))
            if options["reporting"]:
                start = options.get("start_date") or timezone.now().date().isoformat()
                end = options.get("end_date") or start
                payload = adapter.fetch_reporting(execution, start, end)
                snapshot = external_campaign_execution_service.normalize_reporting(execution, payload, start, end)
                self.stdout.write(self.style.SUCCESS(
                    "Reporting pulled "
                    f"impressions={snapshot.impressions} clicks={snapshot.clicks} "
                    f"spend={snapshot.spend} video_views={snapshot.video_views} "
                    f"provider_conversions={snapshot.provider_conversions} currency={snapshot.currency} "
                    f"reporting_window={snapshot.reporting_start}:{snapshot.reporting_end}"
                ))
            if options["pause"]:
                adapter.pause_campaign(execution)
                execution.status = AdChannelExecution.STATUS_PAUSED
                execution.external_status = "PAUSED"
                execution.last_synced_at = timezone.now()
                execution.save(update_fields=["status", "external_status", "last_synced_at", "updated_at"])
                self.stdout.write(self.style.SUCCESS("Google test campaign paused."))
        except (ProviderAPIError, ProviderAuthorizationError) as exc:
            raise CommandError(str(exc)) from exc
