import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aiohttp

from gateway.config import PlatformConfig, Platform
from plugins.platforms.discord.adapter import DiscordAdapter
from tests.e2e.conftest import make_discord_message, make_fake_bot_user, make_runner, make_fake_dm_channel

pytestmark = pytest.mark.asyncio

class FakeResponse:
    def __init__(self, status, json_data):
        self.status = status
        self._json_data = json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def json(self):
        return self._json_data


class TestDiscordAudioN8nWebhook:
    async def test_audio_routed_to_n8n_when_webhook_url_configured(self, monkeypatch):
        # Set up adapter with extra.n8n_audio_webhook_url config
        config = PlatformConfig(
            enabled=True,
            token="fake-token",
            extra={
                "n8n_audio_webhook_url": "http://127.0.0.1:5678/webhook/1/webhook/discord-audio-analysis"
            }
        )
        
        runner = make_runner(Platform.DISCORD)
        from gateway.platforms.helpers import ThreadParticipationTracker
        with patch.object(ThreadParticipationTracker, "_load", return_value=set()):
            adapter = DiscordAdapter(config)
        
        bot_user = make_fake_bot_user()
        adapter._client = SimpleNamespace(
            user=bot_user,
            get_channel=lambda _id: None,
            fetch_channel=AsyncMock(),
        )
        adapter.set_message_handler(runner._handle_message)
        
        # Make a message with an audio attachment
        att = SimpleNamespace(
            id=12345,
            filename="mix_draft.mp3",
            size=1024567,
            url="https://cdn.discordapp.com/attachments/1/mix_draft.mp3",
            proxy_url="https://media.discordapp.net/attachments/1/mix_draft.mp3",
            content_type="audio/mpeg"
        )
        
        dm = make_fake_dm_channel()
        msg = make_discord_message(
            content="Check this loop!",
            channel=dm,
            attachments=[att]
        )
        
        # Mock ClientSession.post to return a successful response with analysis reply
        post_mock = MagicMock(return_value=FakeResponse(
            status=200,
            json_data={"ok": True, "reply": "n8n verified mix_draft.mp3"}
        ))
        
        # Monkeypatch the session post inside adapter
        monkeypatch.setattr(aiohttp.ClientSession, "post", post_mock)
        
        # We need to spy or intercept _handle_message to verify pending_text_injection.
        # But we can also check the event_text inside runner._handle_message.
        # Let's spy on runner._handle_message.
        captured_events = []
        async def mock_handle_message(event):
            captured_events.append(event)
            return "agent-handled"
            
        adapter._message_handler = mock_handle_message
        
        await adapter._handle_message(msg)
        await asyncio.sleep(0.3)
        
        # Check that post was called once
        assert post_mock.called
        call_args, call_kwargs = post_mock.call_args
        assert call_args[0] == "http://127.0.0.1:5678/webhook/1/webhook/discord-audio-analysis"
        payload = call_kwargs["json"]
        assert payload["message_id"] == str(msg.id)
        assert payload["audio_attachments"][0]["filename"] == "mix_draft.mp3"
        
        # Check that event text contains the n8n analysis injection
        assert len(captured_events) == 1
        event = captured_events[0]
        assert "[n8n Audio Analysis]: n8n verified mix_draft.mp3" in event.text
