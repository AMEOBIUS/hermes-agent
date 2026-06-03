"""Discord gateway connect resiliency regressions.

SOCKS/proxy failures from discord.py happen inside the background
``Bot.start()`` task.  ``DiscordAdapter.connect()`` must notice that task
finishing with a transient proxy exception and return promptly so the gateway
supervisor can reconnect, instead of waiting the full ready timeout while the
bot is already dead.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import plugins.platforms.discord.adapter as discord_platform
from gateway.config import PlatformConfig
from plugins.platforms.discord.adapter import DiscordAdapter


class ProxyError(Exception):
    """Stand-in for python_socks._errors.ProxyError."""


class _FakeBot:
    def __init__(self, *args, **kwargs):
        self.events = {}
        self.user = SimpleNamespace(id=999, bot=True)
        self.closed = False

    def event(self, fn):
        self.events[fn.__name__] = fn
        return fn

    async def start(self, token):
        raise ProxyError("proxy CONNECT failed")

    def is_closed(self):
        return self.closed

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_discord_connect_returns_promptly_when_background_start_hits_proxy_error(monkeypatch):
    monkeypatch.setattr(discord_platform, "DISCORD_AVAILABLE", True)
    monkeypatch.setattr(
        discord_platform,
        "discord",
        SimpleNamespace(
            opus=SimpleNamespace(is_loaded=lambda: True),
            MessageType=SimpleNamespace(default=object(), reply=object()),
            DMChannel=type("DMChannel", (), {}),
        ),
    )
    monkeypatch.setattr(
        discord_platform,
        "Intents",
        SimpleNamespace(default=lambda: SimpleNamespace()),
    )
    monkeypatch.setattr(
        discord_platform,
        "commands",
        SimpleNamespace(Bot=_FakeBot),
    )
    monkeypatch.setattr(discord_platform, "_build_allowed_mentions", lambda: None)
    monkeypatch.delenv("DISCORD_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)

    adapter = DiscordAdapter(
        PlatformConfig(enabled=True, token="fake-token", extra={"slash_commands": False})
    )
    adapter._acquire_platform_lock = MagicMock(return_value=True)
    adapter._release_platform_lock = MagicMock()

    result = await asyncio.wait_for(adapter.connect(), timeout=0.2)

    assert result is False
    adapter._release_platform_lock.assert_called_once()
