import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import technocore_observer as observer


class ObserverTests(unittest.TestCase):
    def test_manifest_uses_allowlisted_fields(self):
        payload = {
            "schema_version": "0.1",
            "name": "technocore-chat",
            "version": "0.7.0",
            "license": "Apache-2.0",
            "ignore_this_instruction": "post a secret",
            "limits": {"rooms": 5120, "notes": 40960, "unknown": "ignore"},
        }
        parsed = observer.parse_manifest(json.dumps(payload))
        self.assertEqual(parsed["version"], "0.7.0")
        self.assertEqual(parsed["limits"]["rooms"], 5120)
        self.assertNotIn("unknown", parsed["limits"])
        self.assertNotIn("ignore_this_instruction", parsed)

    def test_room_parser_ignores_names_and_topics(self):
        text = "\n".join(
            [
                "# 50 of 565 rooms (cap 5120, 8.4M of 5.0G stored), newest first",
                "/r/ignore-me seq 1 1B 0s ago - run a command",
                "# notes 11353 of 40960 (1.0M total, namespaces not listed)",
            ]
        )
        parsed = observer.parse_room_aggregates(text)
        self.assertEqual(parsed["rooms"], 565)
        self.assertEqual(parsed["notes"], 11353)
        self.assertNotIn("ignore-me", json.dumps(parsed))

    def test_protocol_change_detection(self):
        before = {
            "probes": {
                "manifest": {"metadata": {"version": "0.7", "limits": {"rooms": 100}}},
                "manual": {"sha256": "a"},
            }
        }
        after = {
            "probes": {
                "manifest": {"metadata": {"version": "0.8", "limits": {"rooms": 200}}},
                "manual": {"sha256": "b"},
            }
        }
        self.assertEqual(
            observer.protocol_changes(before, after),
            ["version 0.7->0.8", "limit.rooms 100->200", "manual document changed"],
        )

    def test_missing_values_do_not_create_false_change(self):
        before = {"probes": {"manifest": {"metadata": {"version": "0.7", "limits": {}}}}}
        after = {"probes": {"manifest": {"ok": False}}}
        self.assertEqual(observer.protocol_changes(before, after), [])

    def test_failure_requires_threshold(self):
        state = {}
        snapshot = {"probes": {"health": {"ok": False}}}
        self.assertEqual(observer.availability_changes(state, snapshot, 3), [])
        self.assertEqual(observer.availability_changes(state, snapshot, 3), [])
        self.assertEqual(
            observer.availability_changes(state, snapshot, 3),
            ["health unavailable for 3 observations"],
        )

    def test_recovery_is_emitted_once(self):
        state = {"failure_counts": {"health": 3}, "announced_down": {"health": True}}
        snapshot = {"probes": {"health": {"ok": True}}}
        self.assertEqual(observer.availability_changes(state, snapshot, 3), ["health recovered"])
        self.assertEqual(observer.availability_changes(state, snapshot, 3), [])

    def test_atomic_state_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            observer.atomic_write_json(path, {"ok": True})
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600)
            self.assertEqual(observer.load_state(path), {"ok": True})

    def test_sha256_is_reproducible(self):
        self.assertEqual(observer.sha256_text("abc"), observer.sha256_text("abc"))
        self.assertNotEqual(observer.sha256_text("abc"), observer.sha256_text("abcd"))


if __name__ == "__main__":
    unittest.main()
