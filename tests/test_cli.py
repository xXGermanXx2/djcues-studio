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
