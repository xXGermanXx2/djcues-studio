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
