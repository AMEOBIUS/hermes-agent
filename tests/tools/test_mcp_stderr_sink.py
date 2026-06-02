import os
import time
from pathlib import Path

from tools import mcp_tool


def test_mcp_stderr_sink_rotates_existing_oversized_log(tmp_path: Path) -> None:
    log_path = tmp_path / "mcp-stderr.log"
    log_path.write_bytes(b"x" * 32)

    sink = mcp_tool._McpStderrSink(log_path, max_bytes=16)
    try:
        assert log_path.exists()
        assert log_path.read_bytes() == b""
        rotated = list(tmp_path.glob("mcp-stderr.log.rotated-*"))
        assert len(rotated) == 1
        assert rotated[0].read_bytes() == b"x" * 32
        assert sink.fileno() >= 0
    finally:
        sink.close()


def test_mcp_stderr_sink_keeps_active_log_bounded_for_child_fd_writes(tmp_path: Path) -> None:
    log_path = tmp_path / "mcp-stderr.log"
    sink = mcp_tool._McpStderrSink(log_path, max_bytes=64)
    try:
        os.write(sink.fileno(), b"a" * 40)
        deadline = time.time() + 2
        while time.time() < deadline and (not log_path.exists() or log_path.stat().st_size < 40):
            time.sleep(0.01)

        os.write(sink.fileno(), b"b" * 40)
        deadline = time.time() + 2
        while time.time() < deadline and not list(tmp_path.glob("mcp-stderr.log.rotated-*")):
            time.sleep(0.01)

        assert log_path.stat().st_size <= 64
        rotated = list(tmp_path.glob("mcp-stderr.log.rotated-*"))
        assert len(rotated) == 1
        assert rotated[0].read_bytes() == b"a" * 40
    finally:
        sink.close()


def test_mcp_stderr_max_bytes_env_is_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("HERMES_MCP_STDERR_LOG_MAX_BYTES", "not-an-int")
    assert mcp_tool._mcp_stderr_max_bytes() == mcp_tool._MCP_STDERR_DEFAULT_MAX_BYTES

    monkeypatch.setenv("HERMES_MCP_STDERR_LOG_MAX_BYTES", "1")
    assert mcp_tool._mcp_stderr_max_bytes() == 1024 * 1024
