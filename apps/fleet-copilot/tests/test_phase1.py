import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from copilot.catalog import Catalog
from copilot.contracts import ContractError, Intent
from copilot.interpreter import interpret
from copilot.providers import MockProvider, ProviderError


ROOT = Path(__file__).parents[1]


class PhaseOneTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog.load(ROOT / "fixtures" / "catalog.hotel-demo.json")

    def test_supported_request_is_a_non_dispatching_preview(self):
        preview = interpret("Send the robot from the lobby to the third-floor middle hallway and bring it back", self.catalog, MockProvider())
        self.assertTrue(preview.dispatchable)
        self.assertEqual(preview.places, ("lobby", "L3_middle_hallway", "lobby"))
        self.assertEqual(preview.rounds, 1)

    def test_unknown_destination_is_held(self):
        preview = interpret("Send the robot to the fourth floor and return", self.catalog, MockProvider())
        self.assertFalse(preview.dispatchable)
        self.assertEqual(preview.action, "unsupported")

    def test_unsupported_delivery_is_held(self):
        preview = interpret("Deliver a package to the third floor", self.catalog, MockProvider())
        self.assertFalse(preview.dispatchable)

    def test_destination_listing_returns_catalog_without_dispatch(self):
        preview = interpret("What destinations can I use?", self.catalog, MockProvider())
        self.assertFalse(preview.dispatchable)
        self.assertEqual(preview.action, "list_destinations")
        self.assertEqual(preview.places, ("lobby", "L3_middle_hallway"))

    def test_closed_contract_rejects_unknown_fields(self):
        with self.assertRaises(ContractError):
            Intent.from_provider({"action": "clarify", "unexpected": True})

    def test_preview_has_no_dispatch_operation(self):
        source = (ROOT / "copilot" / "api.py").read_text(encoding="utf-8")
        self.assertNotIn("dispatch_patrol", source)

    def test_provider_failures_and_hostile_output_are_held(self):
        cases = [
            (ProviderError("refusal", "refused"), "unsupported"),
            (ProviderError("invalid_output", "incomplete"), "unsupported"),
            (ProviderError("rate_limited", "429"), "unsupported"),
            (ProviderError("timeout", "timed out"), "unsupported"),
            (ProviderError("unavailable", "unavailable"), "unsupported"),
        ]
        for failure, action in cases:
            class FailingProvider:
                name = "fault-fixture"

                def interpret(self, text):
                    raise failure

            preview = interpret("Send the robot to the lobby", self.catalog, FailingProvider())
            self.assertFalse(preview.dispatchable)
            self.assertEqual(preview.action, action)

        class HostileProvider:
            name = "hostile-fixture"

            def interpret(self, text):
                return {"action": "propose_patrol", "places": ["lobby"], "rounds": 1, "unexpected": "ignore me"}

        preview = interpret("Send the robot to the lobby", self.catalog, HostileProvider())
        self.assertFalse(preview.dispatchable)
        self.assertEqual(preview.action, "unsupported")


if __name__ == "__main__":
    unittest.main()
