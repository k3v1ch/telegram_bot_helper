from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.cancel import (
    _consume_cancel_return,
    cancel_dispatch,
    set_cancel_return,
)


class FakeContext:
    def __init__(self):
        self.user_data: dict = {}
        self.bot = AsyncMock()


def make_update():
    upd = MagicMock()
    upd.callback_query = None
    upd.message = None
    upd.effective_user = MagicMock()
    upd.effective_user.id = 42
    upd.effective_chat = MagicMock()
    upd.effective_chat.id = 100
    return upd


def test_set_cancel_return_stores_tuple():
    ctx = FakeContext()
    set_cancel_return(ctx, "chat_detail", 7)
    assert ctx.user_data["cancel_return"] == ("chat_detail", 7)


def test_set_cancel_return_without_id():
    ctx = FakeContext()
    set_cancel_return(ctx, "accounts_list")
    assert ctx.user_data["cancel_return"] == ("accounts_list", None)


def test_consume_cancel_return_default():
    ctx = FakeContext()
    assert _consume_cancel_return(ctx) == ("main_menu", None)


def test_consume_cancel_return_pops():
    ctx = FakeContext()
    set_cancel_return(ctx, "chat_settings", 9)
    assert _consume_cancel_return(ctx) == ("chat_settings", 9)
    assert "cancel_return" not in ctx.user_data


@pytest.mark.asyncio
async def test_cancel_dispatch_routes_to_main_menu(base_env, monkeypatch):
    called = {}

    async def fake_send_main_menu(update, context):
        called["main_menu"] = True

    import bot.handlers.start

    monkeypatch.setattr(bot.handlers.start, "send_main_menu", fake_send_main_menu)

    update = make_update()
    ctx = FakeContext()
    result = await cancel_dispatch(update, ctx)
    from telegram.ext import ConversationHandler

    assert result == ConversationHandler.END
    assert called.get("main_menu") is True


@pytest.mark.asyncio
async def test_cancel_dispatch_routes_to_chat_settings(base_env, monkeypatch):
    captured = {}

    async def fake_send_chat_settings(update, context, target_id):
        captured["chat_id"] = target_id

    import bot.handlers.chats

    monkeypatch.setattr(
        bot.handlers.chats, "send_chat_settings_screen", fake_send_chat_settings
    )

    update = make_update()
    ctx = FakeContext()
    set_cancel_return(ctx, "chat_settings", 42)
    await cancel_dispatch(update, ctx)
    assert captured["chat_id"] == 42


@pytest.mark.asyncio
async def test_cancel_dispatch_cleans_flow_state(base_env):
    update = make_update()
    ctx = FakeContext()
    ctx.user_data["auth"] = {"phone": "+7"}
    ctx.user_data["add_chat"] = {"name": "X"}
    ctx.user_data["search_chat_id"] = 5
    ctx.user_data["edit_chat_id"] = 7
    set_cancel_return(ctx, "main_menu")

    await cancel_dispatch(update, ctx)

    for key in ("auth", "add_chat", "search_chat_id", "edit_chat_id"):
        assert key not in ctx.user_data
