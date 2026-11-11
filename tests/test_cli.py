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
