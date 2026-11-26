from __future__ import annotations

import asyncio
import pathlib
import sys
import unittest
from unittest.mock import patch

from aiohttp import web

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from open_workshop_manager import access_client, outbound_http


class OutboundHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen = []

        async def handler(request):
            self.seen.append((request.transport, request.headers.get("Cookie")))
            response = web.json_response({"authenticated": True, "owner_id": 7})
            response.set_cookie("accessToken", "server")
            return response

        app = web.Application()
        app.router.add_post("/internal/access/context", handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.url = patch.object(access_client.config, "ACCESS_SERVICE_URL", f"http://127.0.0.1:{port}")
        self.url.start()
        await outbound_http.start()

    async def asyncTearDown(self):
        await outbound_http.stop()
        await self.runner.cleanup()
        self.url.stop()

    async def test_access_connection_reused_and_response_cookies_discarded(self):
        for cookies in ({"accessToken": "alice"}, {"accessToken": "bob"}, None):
            result = await access_client._request_json("POST", "/internal/access/context", {}, cookies=cookies)
            self.assertEqual(result["owner_id"], 7)
        self.assertEqual([cookie for _, cookie in self.seen], ["accessToken=alice", "accessToken=bob", None])
        self.assertEqual(len({id(transport) for transport, _ in self.seen}), 1)
        self.assertIsNot(outbound_http._sessions["access"], outbound_http._sessions["storage"])

    async def test_parallel_users_are_isolated(self):
        await asyncio.gather(*(
            access_client._request_json("POST", "/internal/access/context", {}, cookies={"accessToken": f"user{i}"})
            for i in range(20)
        ))
        self.assertEqual({cookie for _, cookie in self.seen}, {f"accessToken=user{i}" for i in range(20)})
