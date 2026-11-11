from click.testing import CliRunner

from djcues.cli import cli


def test_menu_can_exit_cleanly():
    result = CliRunner().invoke(cli, [], input="6\n")
    assert result.exit_code == 0
    assert "Rekordbox Cue Assistant" in result.output
    assert "Auf Wiedersehen" in result.output


def test_python_module_entrypoint():
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "djcues.cli"],
        input="6\n",
        text=True,
        capture_output=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0
    assert "Rekordbox Cue Assistant" in proc.stdout
    assert "Auf Wiedersehen" in proc.stdout


def test_format_apply_command_without_uv(monkeypatch):
    import shutil
    from djcues.review import format_apply_command

    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    cmd = format_apply_command("my-session.json")
    assert "uv run" not in cmd
    assert "djcues.cli apply" in cmd
    assert "my-session.json" in cmd


def test_format_apply_command_prefers_venv_even_with_uv(monkeypatch, tmp_path):
    import shutil
    import sys
    from djcues.review import format_apply_command

    if sys.platform == "win32":
        venv_py = tmp_path / ".venv" / "Scripts" / "python.exe"
        venv_py.parent.mkdir(parents=True)
        venv_py.write_bytes(b"")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(shutil, "which", lambda cmd: "C:\\bin\\uv.exe")
        cmd = format_apply_command("my-session.json")
        assert "uv run" not in cmd
        assert ".venv\\Scripts\\python.exe -m djcues.cli apply" in cmd


def test_menu_existing_cues_policy(monkeypatch):
    import click
    from djcues.cli import _menu_existing_cues_policy

    monkeypatch.setattr(click, "prompt", lambda *args, **kwargs: 1)
    assert _menu_existing_cues_policy() == "skip"

    monkeypatch.setattr(click, "prompt", lambda *args, **kwargs: 2)
    assert _menu_existing_cues_policy() == "overwrite"

    monkeypatch.setattr(click, "prompt", lambda *args, **kwargs: 3)
    assert _menu_existing_cues_policy() == "ask"


def test_apply_command_passes_existing_policy(tmp_path, monkeypatch):
    import json

    session_file = tmp_path / "s.json"
    session_file.write_text(json.dumps({"tracks": {}}), encoding="utf-8")

    captured = {}

    def fake_apply_session(session_path, dry_run=False, force=False, backup=None, existing_cues="ask"):
        captured.update(
            {
                "session_path": str(session_path),
                "dry_run": dry_run,
                "force": force,
                "backup": backup,
                "existing_cues": existing_cues,
            }
        )
        return {"written": 0, "cues_written": 0, "skipped_existing": 0}

    monkeypatch.setattr("djcues.writer.apply_session", fake_apply_session)
    result = CliRunner().invoke(cli, ["apply", str(session_file), "--no-backup", "--existing", "skip"])
    assert result.exit_code == 0
    assert captured["existing_cues"] == "skip"
    assert captured["backup"] is False


def test_walkthrough_clears_screen_between_steps_and_actions(monkeypatch):
    from types import SimpleNamespace
    import click
    import djcues.cli as cli_mod

    clear_count = 0

    def fake_clear():
        nonlocal clear_count
        clear_count += 1

    monkeypatch.setattr(click, "clear", fake_clear)
    monkeypatch.setattr(click, "pause", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_mod, "_select_rekordbox_version", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_mod, "get_active_db_info", lambda: None)
    monkeypatch.setattr(cli_mod, "_menu_genre", lambda: ("schranz", {"name": "Schranz", "bpm_range": "150-175 BPM"}))
    monkeypatch.setattr(cli_mod, "_menu_cue_options", lambda *args, **kwargs: (8, True, True, 16, 8))
    monkeypatch.setattr(cli_mod, "_menu_existing_cues_policy", lambda: "skip")
    monkeypatch.setattr(cli_mod, "_menu_scope", lambda: ("Test Playlist", None, True))
    monkeypatch.setattr(cli_mod, "viz", SimpleNamespace(callback=lambda *args, **kwargs: None))

    # Action choices: 0 (viz) -> loop back (must clear again!) -> 6 (return to main menu)
    choices = iter([0, 6])
    seen_action_lists = []

    def fake_choice(title, values):
        seen_action_lists.append(values)
        return next(choices)

    monkeypatch.setattr(cli_mod, "_menu_choice", fake_choice)

    cli_mod._run_walkthrough_flow()

    # 5 setup steps (Setup, Genre, Cues & Loops, Vorhandene Cues, Playlist) + 2 action loop draws = 7 clears
    assert clear_count == 7
    # No broken emoji variation selectors or tofu-prone icons in action menu
    for label in seen_action_lists[0]:
        assert "\ufe0f" not in label
        assert "🌐" not in label
        assert "🎛" not in label
