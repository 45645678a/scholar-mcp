"""Tests for install.py — config read/write, IDE detection, registration."""
import sys
import os
import json
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from install import (
    _read_config,
    _write_config,
    _server_entry,
    register_ide,
    unregister_ide,
    detect_ides,
    MCP_KEY,
    IDE_CONFIGS,
)


# ═══════════════════════════════════════
# Config Read/Write
# ═══════════════════════════════════════

class TestReadConfig:
    def test_nonexistent_file(self, tmp_path):
        result = _read_config(tmp_path / "nonexistent.json")
        assert result == {}

    def test_valid_json(self, tmp_path):
        cfg = tmp_path / "test.json"
        cfg.write_text('{"mcpServers": {"test": {}}}', encoding="utf-8")
        result = _read_config(cfg)
        assert "mcpServers" in result

    def test_utf8_bom(self, tmp_path):
        cfg = tmp_path / "test.json"
        cfg.write_bytes(b'\xef\xbb\xbf{"key": "value"}')
        result = _read_config(cfg)
        assert result == {"key": "value"}

    def test_invalid_json(self, tmp_path):
        cfg = tmp_path / "bad.json"
        cfg.write_text("not json{{{", encoding="utf-8")
        result = _read_config(cfg)
        assert result == {}


class TestWriteConfig:
    def test_creates_file(self, tmp_path):
        cfg = tmp_path / "new.json"
        _write_config(cfg, {"test": True})
        assert cfg.exists()
        assert json.loads(cfg.read_text(encoding="utf-8")) == {"test": True}

    def test_creates_parent_dirs(self, tmp_path):
        cfg = tmp_path / "a" / "b" / "config.json"
        _write_config(cfg, {"nested": True})
        assert cfg.exists()

    def test_backup_created(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text('{"old": true}', encoding="utf-8")
        _write_config(cfg, {"new": True})

        backup = cfg.with_suffix(".json.bak")
        assert backup.exists()
        assert json.loads(backup.read_text()) == {"old": True}
        assert json.loads(cfg.read_text(encoding="utf-8")) == {"new": True}

    def test_backup_no_overwrite(self, tmp_path):
        cfg = tmp_path / "config.json"
        backup = cfg.with_suffix(".json.bak")

        # Create original + existing backup
        cfg.write_text('{"v1": true}', encoding="utf-8")
        backup.write_text('{"v0": true}', encoding="utf-8")

        _write_config(cfg, {"v2": True})

        # Original backup should be preserved
        assert json.loads(backup.read_text()) == {"v0": True}
        # A timestamped backup should exist (exclude the .json.bak itself)
        all_bak = list(tmp_path.glob("config*.bak"))
        timestamped = [f for f in all_bak if f != backup]
        assert len(timestamped) == 1

    def test_unicode_content(self, tmp_path):
        cfg = tmp_path / "config.json"
        _write_config(cfg, {"name": "中文测试"})
        content = cfg.read_text(encoding="utf-8")
        assert "中文测试" in content


# ═══════════════════════════════════════
# Server Entry
# ═══════════════════════════════════════

class TestServerEntry:
    def test_has_command(self):
        entry = _server_entry()
        assert "command" in entry
        assert "args" in entry

    @patch.dict(os.environ, {"AI_API_KEY": "test-key-123"}, clear=False)
    def test_env_vars_included(self):
        entry = _server_entry()
        if "env" in entry:
            assert entry["env"].get("AI_API_KEY") == "test-key-123"

    @patch.dict(os.environ, {}, clear=False)
    def test_empty_env_excluded(self):
        # Remove AI keys from env
        env_copy = os.environ.copy()
        for key in ("AI_API_KEY", "DS_KEY", "AI_API_BASE", "AI_MODEL", "UNPAYWALL_EMAIL"):
            env_copy.pop(key, None)
        with patch.dict(os.environ, env_copy, clear=True):
            entry = _server_entry()
            # env should be empty or not present
            env = entry.get("env", {})
            assert not env.get("AI_API_KEY")


# ═══════════════════════════════════════
# IDE Registration
# ═══════════════════════════════════════

class TestRegisterIDE:
    def test_register_creates_config(self, tmp_path):
        test_config_path = tmp_path / "mcp.json"
        with patch.dict(IDE_CONFIGS, {
            "test_ide": {
                "name": "Test IDE",
                "config_path": lambda: test_config_path,
                "format": "mcpServers",
            }
        }):
            register_ide("test_ide")
            assert test_config_path.exists()
            config = json.loads(test_config_path.read_text(encoding="utf-8"))
            assert MCP_KEY in config["mcpServers"]

    def test_register_preserves_existing(self, tmp_path):
        test_config_path = tmp_path / "mcp.json"
        test_config_path.write_text(json.dumps({
            "mcpServers": {"other-tool": {"command": "other"}}
        }), encoding="utf-8")

        with patch.dict(IDE_CONFIGS, {
            "test_ide": {
                "name": "Test IDE",
                "config_path": lambda: test_config_path,
                "format": "mcpServers",
            }
        }):
            register_ide("test_ide")
            config = json.loads(test_config_path.read_text(encoding="utf-8"))
            assert "other-tool" in config["mcpServers"]
            assert MCP_KEY in config["mcpServers"]

    def test_register_unknown_ide_raises(self):
        with pytest.raises(ValueError):
            register_ide("nonexistent_ide")


class TestUnregisterIDE:
    def test_unregister(self, tmp_path):
        test_config_path = tmp_path / "mcp.json"
        test_config_path.write_text(json.dumps({
            "mcpServers": {MCP_KEY: {"command": "test"}, "other": {"command": "other"}}
        }), encoding="utf-8")

        with patch.dict(IDE_CONFIGS, {
            "test_ide": {
                "name": "Test IDE",
                "config_path": lambda: test_config_path,
                "format": "mcpServers",
            }
        }):
            result = unregister_ide("test_ide")
            assert result is True
            config = json.loads(test_config_path.read_text(encoding="utf-8"))
            assert MCP_KEY not in config["mcpServers"]
            assert "other" in config["mcpServers"]

    def test_unregister_not_found(self, tmp_path):
        test_config_path = tmp_path / "mcp.json"
        test_config_path.write_text('{"mcpServers": {}}', encoding="utf-8")

        with patch.dict(IDE_CONFIGS, {
            "test_ide": {
                "name": "Test IDE",
                "config_path": lambda: test_config_path,
                "format": "mcpServers",
            }
        }):
            result = unregister_ide("test_ide")
            assert result is False


# ═══════════════════════════════════════
# IDE Detection
# ═══════════════════════════════════════

class TestDetectIDEs:
    def test_detects_existing_config(self, tmp_path):
        config_path = tmp_path / "mcp.json"
        config_path.write_text("{}", encoding="utf-8")

        with patch.dict(IDE_CONFIGS, {
            "test_ide": {
                "name": "Test IDE",
                "config_path": lambda: config_path,
                "format": "mcpServers",
            }
        }, clear=True):
            detected = detect_ides()
            assert "test_ide" in detected

    def test_detects_parent_dir(self, tmp_path):
        parent = tmp_path / "ide_config"
        parent.mkdir()
        config_path = parent / "mcp.json"  # doesn't exist, but parent does

        with patch.dict(IDE_CONFIGS, {
            "test_ide": {
                "name": "Test IDE",
                "config_path": lambda: config_path,
                "format": "mcpServers",
            }
        }, clear=True):
            detected = detect_ides()
            assert "test_ide" in detected

    def test_no_detections(self, tmp_path):
        config_path = tmp_path / "nonexistent" / "mcp.json"

        with patch.dict(IDE_CONFIGS, {
            "test_ide": {
                "name": "Test IDE",
                "config_path": lambda: config_path,
                "format": "mcpServers",
            }
        }, clear=True):
            detected = detect_ides()
            assert detected == []
