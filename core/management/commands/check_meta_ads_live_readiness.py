"""Inspect local Meta runtime policy without database or provider access."""
from django.core.management.base import BaseCommand, CommandError

from ads.meta_runtime import runtime_safety_snapshot


class Command(BaseCommand):
    help = "Inspect Meta Ads runtime safety without contacting any provider."
    # Report even malformed configuration safely. The registered system check
    # validates the same service during normal manage.py check/startup.
    requires_system_checks = []
    requires_migrations_checks = False

    def handle(self, *args, **options):
        state = runtime_safety_snapshot()
        self.stdout.write("\n".join([
            "Meta Ads live-publication runtime",
            "Live writes: " + ("ENABLED" if state["live_writes_enabled"] else "DISABLED"),
            "Account allowlist: " + ("CONFIGURED" if state["allowlist_configured"] else "EMPTY"),
            "Acceptance harness: " + ("ENABLED" if state["acceptance_harness_enabled"] else "DISABLED"),
            "Delivery mode: PAUSED",
            "Activation support: NONE",
            "Provider reads during execute: NONE",
            "Runtime safety: " + ("SAFE" if state["safe_to_start"] else "BLOCKED"),
        ]))
        if not state["safe_to_start"]:
            raise CommandError("meta_runtime_configuration_blocked")
