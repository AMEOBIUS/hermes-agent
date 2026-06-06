from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = ROOT / "plugins" / "producers-triage"
SPEC = importlib.util.spec_from_file_location(
    "hermes_plugins.producers_triage_smoke",
    PLUGIN_DIR / "__init__.py",
    submodule_search_locations=[str(PLUGIN_DIR)],
)
producers_triage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = producers_triage
assert SPEC.loader is not None
SPEC.loader.exec_module(producers_triage)


class DummyCtx:
    def __init__(self) -> None:
        self.hooks = []

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))


class CaptureAdapter:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, chat_id, text, *, reply_to=None, metadata=None):
        self.sent.append({
            "chat_id": chat_id,
            "text": text,
            "reply_to": reply_to,
            "metadata": metadata,
        })


def make_event(text: str, *, author: str = "a meobius", chat_id: str = "1509389598923559053"):
    return SimpleNamespace(
        text=text,
        message_id=f"msg-{abs(hash(text)) % 10000}",
        source=SimpleNamespace(
            platform="discord",
            chat_id=chat_id,
            user_id="user-1",
            user_name=author,
            thread_id=None,
        ),
    )


def setup_isolated_profile(tmp: Path) -> None:
    producers_triage.PRODUCERS_DIR = tmp
    producers_triage.CONSENT_FILE = tmp / "weekly_digest_consent.json"
    producers_triage.HELP_INTAKE_FILE = tmp / "help_case_intake_state.json"
    producers_triage.QUEUE_FILE = tmp / "gitdb_tools_queue.json"
    producers_triage.POST_STATE_FILE = tmp / "gitdb_tools_post_state.json"
    producers_triage.SANITY_SCRIPT = tmp / "scripts" / "public_text_sanitizer.py"
    producers_triage.GROWTH_ACTIONS_FILE = tmp / "discord_channel_growth_actions.json"
    producers_triage.GROWTH_STATUS_POST_STATE_FILE = tmp / "discord_growth_status_post_state.json"
    producers_triage.COMMUNITY_POST_GUARD_SCRIPT = tmp / "scripts" / "community_post_guard.py"
    producers_triage.HUMAN_QUESTIONS_FILE = tmp / "discord_human_questions.json"
    producers_triage.HUMAN_QUESTIONS_SCRIPT = tmp / "scripts" / "discord_human_questions.py"
    producers_triage._is_producers_profile = lambda: True
    producers_triage.run_sanitizer = lambda value: value

    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "gitdb_tools_queue.json").write_text(json.dumps({
        "generated_at": "2026-06-05T00:00:00+00:00",
        "candidates": [
            {
                "full_name": "demo/audio-tool",
                "language": "Python",
                "stars": 4242,
                "card": "demo/audio-tool - локальный инструмент для музыки",
            }
        ],
    }, ensure_ascii=False), encoding="utf-8")
    (tmp / "discord_channel_growth_actions.json").write_text(json.dumps({
        "totals": {"recent_messages": 10, "recent_human": 6, "recent_bot": 4, "human_ratio": 0.6},
        "priority_actions": [{"name": "музыка", "tags": ["healthy"], "cadence": "ручной", "actions": ["спросить людей"]}],
        "healthy_lanes": [{"name": "музыка"}],
    }, ensure_ascii=False), encoding="utf-8")
    (tmp / "discord_human_questions.json").write_text(json.dumps({
        "totals": {"human_ratio": 0.6},
        "questions": [{"channel": "музыка", "question": "что сейчас звучит живее?", "followup": "скинь один пример"}],
    }, ensure_ascii=False), encoding="utf-8")

    fallback = SimpleNamespace(
        run_prompt_doctor_offline=lambda prompt, goal, failure: f"diagnosed:{prompt}|{goal}|{failure}"
    )
    sys.modules[f"{SPEC.name}.prompt_doctor_fallback"] = fallback


def assert_contains(adapter: CaptureAdapter, needle: str) -> None:
    if not any(needle in item["text"] for item in adapter.sent):
        dump = json.dumps(adapter.sent, ensure_ascii=False, indent=2)
        raise AssertionError(f"expected {needle!r} in sends, got:\n{dump}")


async def run_smoke() -> dict:
    with tempfile.TemporaryDirectory(prefix="producers-triage-smoke-") as tmpdir:
        setup_isolated_profile(Path(tmpdir))
        adapter = CaptureAdapter()
        gateway = SimpleNamespace(adapters={"discord": adapter})

        ctx = DummyCtx()
        producers_triage.register(ctx)
        if len(ctx.hooks) != 1 or ctx.hooks[0][0] != "pre_gateway_dispatch":
            raise AssertionError(f"unexpected hooks: {ctx.hooks}")

        result = await producers_triage.pre_gateway_dispatch(make_event("кработ согласие", author="artist one"), gateway=gateway)
        assert result == {"action": "skip"}
        assert_contains(adapter, "запомнил, artist one")

        result = await producers_triage.pre_gateway_dispatch(
            make_event("кработ почини промпт\nпромпт: dark neurodance\nцель: клубный грув\nпроблема: мутный микс"),
            gateway=gateway,
        )
        assert result == {"action": "skip"}
        assert_contains(adapter, "diagnosed:dark neurodance|клубный грув|мутный микс")

        result = await producers_triage.pre_gateway_dispatch(make_event("кработ статус роста"), gateway=gateway)
        assert result == {"action": "skip"}
        assert_contains(adapter, "статус роста")

        result = await producers_triage.pre_gateway_dispatch(make_event("кработ вопросы"), gateway=gateway)
        assert result == {"action": "skip"}
        assert_contains(adapter, "вопросы для оживления дискорда")

        result = await producers_triage.pre_gateway_dispatch(make_event("кработ очередь"), gateway=gateway)
        assert result == {"action": "skip"}
        assert_contains(adapter, "demo/audio-tool")

        result = await producers_triage.pre_gateway_dispatch(make_event("кработ обнови очередь", author="artist one"), gateway=gateway)
        assert result == {"action": "skip"}
        assert_contains(adapter, "команда доступна только администраторам")

        producers_triage.trigger_queue_refresh = lambda **kwargs: {
            "ok": True,
            "summary": {
                "candidate_count": 1,
                "denied_count": 0,
                "source_counts": {"gitdb": 1, "telegram": 1, "x": 0},
                "top": [{"full_name": "demo/audio-tool", "score": 8.0, "sources": ["telegram", "gitdb"]}],
            },
        }
        result = await producers_triage.pre_gateway_dispatch(make_event("кработ обнови очередь без трендшифт"), gateway=gateway)
        assert result == {"action": "skip"}
        for _ in range(20):
            if any("очередь инструментов обновлена" in item["text"] for item in adapter.sent):
                break
            await asyncio.sleep(0.01)
        assert_contains(adapter, "очередь инструментов обновлена")

        return {"ok": True, "send_count": len(adapter.sent), "checks": 7}


def main() -> int:
    result = asyncio.run(run_smoke())
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
