from io import StringIO

from django.core import checks
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, override_settings

from .checks import meta_live_runtime_check
from .meta_runtime import (
    acceptance_harness_allowed,
    parse_account_allowlist,
    parse_live_write_setting,
    runtime_safety_snapshot,
)


class MetaRuntimeSafetyTests(SimpleTestCase):
    def test_boolean_and_allowlist_parsing_is_strict(self):
        self.assertIs(parse_live_write_setting("true"), True)
        self.assertIs(parse_live_write_setting("false"), False)
        for value in ("1", "yes", "on", "enabled", 1, None):
            self.assertIsNone(parse_live_write_setting(value))
        self.assertEqual(parse_account_allowlist(" act_123,123 "), (frozenset({"123"}), True))
        for value in ("123 456", {"123": True}, ["123", "bad"], ["١٢٣"]):
            allowed, valid = parse_account_allowlist(value)
            self.assertEqual((allowed, valid), (frozenset(), False))

    @override_settings(
        META_ADS_LIVE_WRITES_ENABLED=False,
        META_ADS_LIVE_WRITE_ACCOUNT_ALLOWLIST="",
        META_ADS_ACCEPTANCE_HARNESS_ENABLED=False,
        META_ADS_LIVE_AUTHORIZATION_MAX_AGE_SECONDS=900,
        META_ADS_VERIFICATION_MAX_AGE_SECONDS=600,
        META_ADS_PERMISSION_MAX_AGE_SECONDS=600,
    )
    def test_snapshot_is_bounded_and_does_not_expose_identifiers(self):
        snapshot = runtime_safety_snapshot()
        self.assertEqual(snapshot["delivery_mode"], "PAUSED")
        self.assertFalse(snapshot["activation_supported"])
        self.assertTrue(snapshot["safe_to_start"])
        self.assertNotIn("123", repr(snapshot))
        self.assertFalse(acceptance_harness_allowed())

    @override_settings(
        META_ADS_LIVE_WRITES_ENABLED=True,
        META_ADS_LIVE_WRITE_ACCOUNT_ALLOWLIST="",
        META_ADS_ACCEPTANCE_HARNESS_ENABLED=False,
    )
    def test_enabled_without_allowlist_is_blocked_and_check_is_value_free(self):
        snapshot = runtime_safety_snapshot()
        self.assertFalse(snapshot["safe_to_start"])
        self.assertIn("meta_live_allowlist_empty", snapshot["blockers"])
        messages = meta_live_runtime_check(None)
        self.assertTrue(any(message.id == "ads.W001" for message in messages))
        self.assertNotIn("123", repr(messages))

    def test_readiness_command_is_safe_by_default(self):
        output = StringIO()
        call_command("check_meta_ads_live_readiness", stdout=output)
        self.assertIn("Runtime safety: SAFE", output.getvalue())
        self.assertNotIn("access_token", output.getvalue())

    @override_settings(META_ADS_ACCEPTANCE_HARNESS_ENABLED=True)
    def test_acceptance_harness_requires_explicit_test_override(self):
        self.assertTrue(acceptance_harness_allowed())

