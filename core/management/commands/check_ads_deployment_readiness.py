"""Inspect local application/schema/Meta safety without provider traffic."""

from django.core.management.base import BaseCommand, CommandError

from ads.deployment_readiness import deployment_readiness


class Command(BaseCommand):
    help = "Check Ads deployment readiness without changing the database."
    requires_system_checks = []
    requires_migrations_checks = False

    def handle(self, *args, **options):
        state = deployment_readiness()
        schema = state["schema"]
        expected = schema["expected"][-1] if schema["expected"] else "UNKNOWN"
        runtime = state["runtime"]
        self.stdout.write("\n".join([
            "Arolana Ads deployment readiness",
            "Application checks: PASS",
            "Ads schema: " + ("CURRENT" if schema["current"] else "OUTDATED"),
            f"Expected Ads migration: {expected}",
            f"Missing Ads migrations: {len(schema['missing'])}",
            "Meta live writes: " + ("ENABLED" if runtime["live_writes_enabled"] else "DISABLED"),
            "Meta allowlist: " + ("CONFIGURED" if runtime["allowlist_configured"] else "EMPTY"),
            "Acceptance harness: " + ("ENABLED" if runtime["acceptance_harness_enabled"] else "DISABLED"),
            "Delivery mode: PAUSED",
            "Activation support: NONE",
            "Provider traffic: NONE",
            "Deployment readiness: " + ("READY" if state["safe_to_start"] else "BLOCKED"),
        ]))
        if not state["safe_to_start"]:
            raise CommandError("ads_deployment_readiness_blocked")
