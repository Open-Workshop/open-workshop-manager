from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from open_workshop_manager import mod_events


class _FakeJetStream:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def publish(self, subject, payload, timeout=None, stream=None):
        self.calls.append(
            {
                "subject": subject,
                "payload": payload,
                "timeout": timeout,
                "stream": stream,
            }
        )
        return SimpleNamespace(stream=stream, seq=42)


class ModEventsTests(unittest.TestCase):
    def tearDown(self) -> None:
        mod_events._jetstream = None

    def test_publish_mod_event_sends_required_payload_fields(self) -> None:
        fake_jetstream = _FakeJetStream()
        mod_events._jetstream = fake_jetstream

        with patch.object(
            mod_events.config,
            "NATS_MOD_EVENTS_ENABLED",
            True,
        ), patch.object(
            mod_events.config,
            "NATS_MOD_EVENTS_REQUIRED",
            False,
        ), patch.object(
            mod_events.config,
            "NATS_MOD_EVENTS_STREAM",
            "MOD_EVENTS",
        ), patch.object(
            mod_events.config,
            "NATS_MOD_EVENTS_SUBJECT_PREFIX",
            "mods",
        ), patch.object(
            mod_events.config,
            "NATS_PUBLISH_TIMEOUT_SECONDS",
            3,
        ):
            asyncio.run(
                mod_events.publish_mod_event(
                    mod_events.MOD_EVENT_CHANGED,
                    17,
                    "Demo Mod",
                    "Full text",
                )
            )

        self.assertEqual(len(fake_jetstream.calls), 1)
        call = fake_jetstream.calls[0]
        self.assertEqual(call["subject"], "mods.changed")
        self.assertEqual(call["stream"], "MOD_EVENTS")
        self.assertEqual(call["timeout"], 3.0)

        payload = json.loads(call["payload"].decode("utf-8"))
        self.assertEqual(payload["event"], "mod.changed")
        self.assertEqual(payload["id"], 17)
        self.assertEqual(payload["title"], "Demo Mod")
        self.assertEqual(payload["full_description"], "Full text")
        self.assertIn("occurred_at", payload)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
