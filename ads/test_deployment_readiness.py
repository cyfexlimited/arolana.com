from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase

from .deployment_readiness import deployment_readiness


class AdsDeploymentReadinessTests(SimpleTestCase):
    def test_safe_snapshot_is_ready_without_provider_access(self):
        schema = {"current": True, "expected": ["0019_metapublicationattempt_executing"], "missing": [], "error": None}
        runtime = {
            "live_writes_enabled": False, "allowlist_configured": False,
            "acceptance_harness_enabled": False, "delivery_mode": "PAUSED",
            "activation_supported": False, "provider_reads_during_execute": False,
            "safe_to_start": True, "blockers": [],
        }
        with patch("ads.deployment_readiness.inspect_ads_schema", return_value=schema), patch(
            "ads.deployment_readiness.runtime_safety_snapshot", return_value=runtime
        ):
            result = deployment_readiness()
        self.assertTrue(result["safe_to_start"])
        self.assertEqual(result["blockers"], [])

    def test_missing_schema_blocks_without_migration(self):
        schema = {"current": False, "expected": ["0019_metapublicationattempt_executing"], "missing": ["0019_metapublicationattempt_executing"], "error": None}
        runtime = {"live_writes_enabled": False, "allowlist_configured": False, "acceptance_harness_enabled": False, "delivery_mode": "PAUSED", "activation_supported": False, "provider_reads_during_execute": False, "safe_to_start": True, "blockers": []}
        with patch("ads.deployment_readiness.inspect_ads_schema", return_value=schema), patch("ads.deployment_readiness.runtime_safety_snapshot", return_value=runtime):
            result = deployment_readiness()
        self.assertFalse(result["safe_to_start"])
        self.assertEqual(result["blockers"], ["ads_schema_outdated"])

    def test_schema_database_failure_blocks_safely(self):
        schema = {"current": False, "expected": [], "missing": [], "error": "schema_inspection_unavailable"}
        runtime = {"live_writes_enabled": False, "allowlist_configured": False, "acceptance_harness_enabled": False, "delivery_mode": "PAUSED", "activation_supported": False, "provider_reads_during_execute": False, "safe_to_start": True, "blockers": []}
        with patch("ads.deployment_readiness.inspect_ads_schema", return_value=schema), patch("ads.deployment_readiness.runtime_safety_snapshot", return_value=runtime):
            result = deployment_readiness()
        self.assertFalse(result["safe_to_start"])
        self.assertEqual(result["blockers"], ["schema_inspection_unavailable"])

    def test_command_reports_bounded_schema_state(self):
        output = StringIO()
        with patch("ads.deployment_readiness.inspect_ads_schema", return_value={"current": True, "expected": ["0019_metapublicationattempt_executing"], "missing": [], "error": None}):
            call_command("check_ads_deployment_readiness", stdout=output)
        text = output.getvalue()
        self.assertIn("Deployment readiness: READY", text)
        self.assertIn("Expected Ads migration: 0019_metapublicationattempt_executing", text)
        self.assertNotIn("DATABASE", text)

