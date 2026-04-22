from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from open_workshop_manager.access import api_callback
from open_workshop_manager.settings import MAIN_URL


class _DummySession:
    async def __aenter__(self) -> "_DummySession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def execute(self, *args, **kwargs):  # pragma: no cover - safety net
        raise AssertionError("DB access was not expected in this test")

    async def commit(self):  # pragma: no cover - safety net
        raise AssertionError("DB access was not expected in this test")

    async def get(self, *args, **kwargs):  # pragma: no cover - safety net
        raise AssertionError("DB access was not expected in this test")


class AccessCallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app = FastAPI()
        app.include_router(api_callback.router)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def test_callback_accepts_empty_body(self) -> None:
        dummy_session = _DummySession()

        with patch.object(
            api_callback.tools,
            "check_token",
            AsyncMock(return_value=True),
        ), patch.object(
            api_callback.account,
            "AsyncSessionLocal",
            return_value=dummy_session,
        ):
            response = self.client.post(f"{MAIN_URL}/access/callback/context")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["authenticated"])
        self.assertEqual(body["owner_id"], -1)
        self.assertNotIn("mods", body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
