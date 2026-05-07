"""End-to-end of the settings.json patch/unpatch round-trip on tmp files."""

import json

from claude_qte.settings import (
    HOOK_COMMAND_MARKER,
    load_settings,
    patch_for_hook,
    save_settings,
    unpatch_hook,
)


class TestLoadSave:
    def test_load_missing_returns_empty(self, settings_path):
        assert load_settings(settings_path) == {}

    def test_save_load_roundtrip(self, settings_path):
        save_settings({"hooks": {"PreToolUse": []}}, settings_path)
        assert load_settings(settings_path) == {"hooks": {"PreToolUse": []}}

    def test_load_invalid_json_returns_empty(self, settings_path):
        with open(settings_path, "w") as fh:
            fh.write("{not json")
        assert load_settings(settings_path) == {}

    def test_save_writes_atomically(self, settings_path):
        save_settings({"a": 1}, settings_path)
        with open(settings_path) as fh:
            assert json.load(fh) == {"a": 1}


class TestPatchForHook:
    def test_inserts_into_empty_settings(self, settings_path):
        patch_for_hook("/usr/local/bin/claude-qte", settings_path)
        s = load_settings(settings_path)
        assert s["hooks"]["PreToolUse"][0]["matcher"] == "Bash|Edit|Write|NotebookEdit"
        assert HOOK_COMMAND_MARKER in s["hooks"]["PreToolUse"][0]["hooks"][0]["command"]

    def test_idempotent_on_repeat(self, settings_path):
        patch_for_hook("/usr/local/bin/claude-qte", settings_path)
        patch_for_hook("/usr/local/bin/claude-qte", settings_path)
        s = load_settings(settings_path)
        # Should still be exactly one entry — not duplicated.
        assert len(s["hooks"]["PreToolUse"]) == 1

    def test_replaces_old_path_in_place(self, settings_path):
        patch_for_hook("/old/bin/claude-qte", settings_path)
        patch_for_hook("/new/bin/claude-qte", settings_path)
        s = load_settings(settings_path)
        cmds = [h["command"] for h in s["hooks"]["PreToolUse"][0]["hooks"]]
        assert any("/new/bin/claude-qte" in c for c in cmds)
        assert not any("/old/bin/claude-qte" in c for c in cmds)

    def test_preserves_other_hooks(self, settings_path):
        save_settings({
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command",
                                                   "command": "/some/other-tool"}]}
                ]
            }
        }, settings_path)
        patch_for_hook("/usr/local/bin/claude-qte", settings_path)
        s = load_settings(settings_path)
        assert len(s["hooks"]["PreToolUse"]) == 2

    def test_preserves_unrelated_top_level_keys(self, settings_path):
        save_settings({"theme": "dark", "model": "opus"}, settings_path)
        patch_for_hook("/usr/local/bin/claude-qte", settings_path)
        s = load_settings(settings_path)
        assert s["theme"] == "dark"
        assert s["model"] == "opus"


class TestUnpatchHook:
    def test_no_op_on_missing_file(self, settings_path):
        assert unpatch_hook(settings_path) is False

    def test_removes_only_our_entry(self, settings_path):
        save_settings({
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command",
                                                   "command": "/some/other-tool"}]}
                ]
            }
        }, settings_path)
        patch_for_hook("/usr/local/bin/claude-qte", settings_path)
        assert unpatch_hook(settings_path) is True
        s = load_settings(settings_path)
        assert len(s["hooks"]["PreToolUse"]) == 1
        assert "/some/other-tool" in s["hooks"]["PreToolUse"][0]["hooks"][0]["command"]

    def test_drops_empty_pre_tool_use(self, settings_path):
        patch_for_hook("/usr/local/bin/claude-qte", settings_path)
        assert unpatch_hook(settings_path) is True
        s = load_settings(settings_path)
        assert "hooks" not in s

    def test_returns_false_when_nothing_to_remove(self, settings_path):
        save_settings({"theme": "dark"}, settings_path)
        assert unpatch_hook(settings_path) is False
