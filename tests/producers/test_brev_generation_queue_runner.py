from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parents[1]
SCRIPT = REPO_ROOT / ".hermes" / "profiles" / "producers" / "scripts" / "brev_generation_queue_runner.py"
SPEC = importlib.util.spec_from_file_location("brev_generation_queue_runner_test", SCRIPT)
brev_runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = brev_runner
assert SPEC.loader is not None
SPEC.loader.exec_module(brev_runner)


class FakeHelper:
    @staticmethod
    def _canonical_path(value: str) -> str:
        return "/music-ai-generator" if value else ""

    @staticmethod
    def build_safe_form_js(**kwargs) -> str:
        return "FORM_JS"


class FakeCDP:
    instances: list["FakeCDP"] = []

    def __init__(self, cdp_http_url: str, timeout: float = 20.0):
        self.cdp_http_url = cdp_http_url
        self.timeout = timeout
        self.attach_status = {"created_target": False, "target_url": "https://brev.ai/music-ai-generator"}
        self.page_ws = "ws://fake/page"
        self.evaluated: list[str] = []
        FakeCDP.instances.append(self)

    async def connect(self, url: str) -> None:
        self.url = url

    async def wait_ready(self, timeout=None):
        return {"readyState": "complete", "url": "https://brev.ai/music-ai-generator"}

    async def evaluate(self, js: str):
        self.evaluated.append(js)
        if js == "FORM_JS":
            return {"ok": True, "filled": True}
        if "field_count" in js:
            return {"field_count": 2, "fields": [{"placeholder": "description", "value_len": 20}, {"placeholder": "style", "value_len": 10}]}
        if "clicked" in js and "button" in js:
            return {"ok": True, "clicked": True, "button": "Generate"}
        if "asset_urls" in js:
            return {"ok": True, "blocked": False, "asset_urls": ["https://cdn.example/track.mp3"], "asset_candidates": []}
        return {}

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_live_runner_clicks_generate_and_completes(tmp_path, monkeypatch, capsys):
    queue = tmp_path / "brev_generation_requests.json"
    queue.write_text(json.dumps({"requests": [{
        "request_id": "brev-test-live",
        "status": "queued",
        "prompt": "dark neurodance",
        "style": "binaural pulse",
        "lyrics": "",
        "instrumental": True,
        "requested_alias": "/music-ai-generator",
    }]}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(brev_runner, "load_helper", lambda path: FakeHelper)
    monkeypatch.setattr(brev_runner, "CDPClient", FakeCDP)
    monkeypatch.setattr(brev_runner, "artifact_dir", lambda issue_id, request_id: tmp_path / "artifacts" / issue_id / request_id)

    args = brev_runner.build_parser().parse_args([
        "--queue", str(queue),
        "--request-id", "brev-test-live",
        "--issue-id", "issue-test",
        "--poll-seconds", "1",
        "--poll-interval", "0.01",
    ])

    rc = await brev_runner.process_one(args)
    out = capsys.readouterr().out
    manifest = json.loads(out)

    assert rc == 0
    assert manifest["final_status"] == "completed"
    assert manifest["ok"] is True
    assert manifest["click_result"]["clicked"] is True
    assert manifest["asset_urls"] == ["https://cdn.example/track.mp3"]
    assert any("clicked" in js and "button" in js for js in FakeCDP.instances[-1].evaluated)

    state = json.loads(queue.read_text(encoding="utf-8"))
    assert state["requests"][0]["status"] == "completed"
    assert state["requests"][0]["asset_urls"] == ["https://cdn.example/track.mp3"]
