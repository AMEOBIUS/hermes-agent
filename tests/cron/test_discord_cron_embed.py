import json
import pytest
from cron.scheduler import _deliver_result
from gateway.config import Platform, PlatformConfig

def test_deliver_result_discord_embed(monkeypatch):
    # Mock config loader to return a Discord-enabled config
    class FakeConfig:
        def __init__(self):
            self.platforms = {
                Platform.DISCORD: PlatformConfig(enabled=True, token="fake-token")
            }
        def get_home_channel(self, platform):
            return None

    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"cron": {"wrap_response": True}})
    monkeypatch.setattr("gateway.config.load_gateway_config", FakeConfig)
    
    # Mock the sending function to capture what gets sent
    sent_payloads = []
    async def fake_send_to_platform(platform, pconfig, chat_id, message, thread_id=None, media_files=None, force_document=False):
        sent_payloads.append(message)
        return {"success": True, "message_id": "12345"}
        
    monkeypatch.setattr("tools.send_message_tool._send_to_platform", fake_send_to_platform)
    
    # Run a test job
    job = {
        "id": "test-job-123",
        "name": "Test Job Name",
        "deliver": "discord:112233",
        "schedule": "0 12 * * *"
    }
    
    _deliver_result(job, "Hello world!")
    
    assert len(sent_payloads) == 1
    payload_str = sent_payloads[0]
    
    # Parse payload as JSON
    payload = json.loads(payload_str)
    assert "embeds" in payload
    embed = payload["embeds"][0]
    assert embed["title"] == "🔄 Cronjob Executed: Test Job Name"
    assert embed["description"] == "Hello world!"
    assert embed["color"] == 0x00FFCC
    assert len(embed["fields"]) == 2
    assert embed["fields"][0]["value"] == "`test-job-123`"
