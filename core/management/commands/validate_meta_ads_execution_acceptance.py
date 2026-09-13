"""Safe, test-context-only acceptance runner for the Meta execution chain."""

from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings

from accounts.models import User
from ads.meta_live_controls import authorize
from ads.meta_publish import execute
from ads.models import AdCampaign, ExternalAdvertisingAccount


class Command(BaseCommand):
    help = "Validate a synthetic Meta Ads plan using an in-process mocked writer."

    def add_arguments(self, parser):
        parser.add_argument("--campaign-id", required=True, type=int)
        parser.add_argument("--external-account-id", required=True, type=int)
        parser.add_argument("--staff-user-id", required=True, type=int)
        parser.add_argument("--confirm-mocked-provider", action="store_true")

    def handle(self, *args, **options):
        if not options["confirm_mocked_provider"]:
            raise CommandError("mocked_provider_confirmation_required")
        if not getattr(settings, "META_ADS_ACCEPTANCE_HARNESS_ENABLED", False):
            raise CommandError("mocked_acceptance_harness_disabled")
        account = ExternalAdvertisingAccount.objects.filter(
            pk=options["external_account_id"], channel="meta"
        ).first()
        campaign = AdCampaign.objects.filter(pk=options["campaign_id"]).first()
        staff = User.objects.filter(pk=options["staff_user_id"], is_staff=True).first()
        if not account or not campaign or not staff or account.advertiser_identity_id != campaign.advertiser_identity_id:
            raise CommandError("synthetic_acceptance_context_required")
        if (account.metadata or {}).get("meta_acceptance_synthetic") is not True:
            raise CommandError("synthetic_acceptance_context_required")
        creative = campaign.creatives.order_by("pk").first()
        if not creative:
            raise CommandError("synthetic_acceptance_context_required")

        calls = []

        def mocked(name):
            def create(*args):
                if name in {"campaign", "adset", "ad"} and args[-1].get("status") != "PAUSED":
                    raise CommandError("mocked_paused_invariant_failed")
                calls.append(name)
                return "acceptance-" + name

            return create

        # These are process-local settings and explicit provider-boundary
        # intercepts. The command cannot issue an HTTP request, even by error.
        with override_settings(
            META_ADS_LIVE_WRITES_ENABLED=True,
            META_ADS_LIVE_WRITE_ACCOUNT_ALLOWLIST=[account.external_account_id],
        ), patch("requests.sessions.Session.request", side_effect=AssertionError("provider_network_blocked")), \
             patch("ads.providers.requests.get", side_effect=AssertionError("provider_network_blocked")), \
             patch("ads.providers.requests.post", side_effect=AssertionError("provider_network_blocked")), \
             patch("ads.meta_publish.MetaLivePublishAdapter.create_campaign", mocked("campaign")), \
             patch("ads.meta_publish.MetaLivePublishAdapter.create_adset", mocked("adset")), \
             patch("ads.meta_publish.MetaLivePublishAdapter.create_adcreative", mocked("creative")), \
             patch("ads.meta_publish.MetaLivePublishAdapter.create_ad", mocked("ad")):
            authorization, blockers = authorize(account.advertiser_identity, creative, account.pk, staff)
            if blockers:
                raise CommandError(blockers[0])
            result, blockers = execute(account.advertiser_identity, creative, account.pk, actor=staff)
        if blockers or not result or calls != ["campaign", "adset", "creative", "ad"]:
            raise CommandError((blockers or ["mocked_execution_failed"])[0])
        self.stdout.write(
            "Meta Ads execution acceptance\n"
            "Campaign: eligible\n"
            "Creative: eligible\n"
            "M12 readiness: ready\n"
            "M13 verification: fresh\n"
            "M14 plan: current\n"
            "M17 permissions: fresh\n"
            "M18 allowlist: process-only synthetic\n"
            "M18 authorization: valid\n"
            "Provider: MOCKED\n"
            "Initial delivery status: PAUSED\n"
            "Execution: completed\n"
            "Network provider calls: 0 real\n"
            "Result: PASS"
        )
