import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.health import make_health_app
from bot.state import BotState


@pytest.fixture
def state(tmp_data_dir):
    return BotState(tmp_data_dir, alerts_default=True)


async def test_health_ok_when_connected(state):
    fake_userbot = type("U", (), {"is_connected": lambda self: True})()
    app = make_health_app(lambda: fake_userbot, state)
    async with TestServer(app) as srv:
        async with TestClient(srv) as client:
            resp = await client.get("/health")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"
            assert data["userbot_connected"] is True


async def test_health_degraded_when_not_connected(state):
    fake_userbot = type("U", (), {"is_connected": lambda self: False})()
    app = make_health_app(lambda: fake_userbot, state)
    async with TestServer(app) as srv:
        async with TestClient(srv) as client:
            resp = await client.get("/health")
            assert resp.status == 503
            data = await resp.json()
            assert data["status"] == "degraded"


async def test_health_degraded_when_none(state):
    app = make_health_app(lambda: None, state)
    async with TestServer(app) as srv:
        async with TestClient(srv) as client:
            resp = await client.get("/health")
            assert resp.status == 503


async def test_ping_endpoint(state):
    app = make_health_app(lambda: None, state)
    async with TestServer(app) as srv:
        async with TestClient(srv) as client:
            resp = await client.get("/ping")
            assert resp.status == 200
            assert (await resp.text()) == "pong"
