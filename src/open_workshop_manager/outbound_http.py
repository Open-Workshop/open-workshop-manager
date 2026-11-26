"""Lifecycle-managed connection pool for outgoing service requests."""
from contextlib import asynccontextmanager

import aiohttp


_sessions: dict[str, aiohttp.ClientSession] = {}


async def start() -> None:
    for name in ("access", "storage", "external"):
        if name not in _sessions or _sessions[name].closed:
            _sessions[name] = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())


async def stop() -> None:
    for session in _sessions.values():
        await session.close()
    _sessions.clear()


@asynccontextmanager
async def session_scope(*, name="access", timeout=None):
    session = _sessions.get(name)
    if session is not None and not session.closed:
        yield session
    else:
        # Standalone callers and tests do not necessarily run the app lifespan.
        async with aiohttp.ClientSession(timeout=timeout, cookie_jar=aiohttp.DummyCookieJar()) as session:
            yield session
