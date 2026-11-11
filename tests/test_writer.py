"""Tests for djcues.writer — backup, cue row building, DB write."""

from __future__ import annotations

from djcues.constants import CUE_SYSTEM, CUE_SYSTEM_BY_PAD


# ---------------------------------------------------------------------------
# Test 1: backup_database creates a timestamped copy
# ---------------------------------------------------------------------------


def test_backup_creates_timestamped_copy(tmp_path):
    fake_db = tmp_path / "master.db"
    fake_db.write_bytes(b"sqlite-fake-content")

    from djcues.writer import backup_database

    backup_path = backup_database(fake_db)

    assert backup_path.exists()
    assert backup_path.parent == tmp_path
    assert backup_path.name.startswith("master-backup-")
    assert backup_path.name.endswith(".db")
    assert backup_path.read_bytes() == b"sqlite-fake-content"


# ---------------------------------------------------------------------------
# Helpers for build_cue_rows tests
# ---------------------------------------------------------------------------


def _make_hot_cues(statuses: dict[str, str] | None = None) -> dict:
    """Build a hot cues dict keyed by pad letter with position data.

    *statuses* overrides the default 'accepted' status per pad.
    """
    if statuses is None:
        statuses = {}
    cues: dict[str, dict] = {}
    for pad in "ABCDEFGH":
        slot = CUE_SYSTEM_BY_PAD[pad]
        entry: dict = {
            "status": statuses.get(pad, "accepted"),
            "position_ms": 1000.0 * (ord(pad) - ord("A") + 1),
        }
        if slot.is_loop:
            entry["loop_end_ms"] = entry["position_ms"] + 7500.0
        else:
            entry["loop_end_ms"] = None
        cues[pad] = entry
    return cues


def _make_memory_cues(statuses: dict[str, str] | None = None) -> dict:
    """Build a memory cues dict keyed by slot number string '1'-'8'."""
    if statuses is None:
        statuses = {}
    cues: dict[str, dict] = {}
    for i in range(8):
        slot_num = str(i + 1)
        slot = CUE_SYSTEM[i]
        entry: dict = {
            "status": statuses.get(slot_num, "accepted"),
            "position_ms": 500.0 * (i + 1),
        }
        if slot.is_loop:
            entry["loop_end_ms"] = entry["position_ms"] + 7500.0
        else:
            entry["loop_end_ms"] = None
        cues[slot_num] = entry
    return cues


# ---------------------------------------------------------------------------
# Test 2: build_cue_rows creates hot and memory rows
# ---------------------------------------------------------------------------


def test_build_cue_rows_creates_hot_and_memory():
    from djcues.writer import build_cue_rows

    hot_cues = _make_hot_cues()
    memory_cues = _make_memory_cues()

    hot_rows, mem_rows = build_cue_rows(hot_cues, memory_cues)

    assert len(hot_rows) == 8
    assert len(mem_rows) == 8

    # Verify hot cue fields
    for row in hot_rows:
        assert "Kind" in row
        assert "InMsec" in row
        assert "OutMsec" in row
        assert "ColorTableIndex" in row
        assert "Comment" in row
        assert row["InFrame"] == 0
        assert row["InMpegFrame"] == 0
        assert row["InMpegAbs"] == 0
        assert row["BeatLoopSize"] == 0
        assert row["CueMicrosec"] == 0

    # Check specific hot cue: pad A (kind=1, not a loop)
    hot_a = next(r for r in hot_rows if r["Kind"] == 1)
    assert hot_a["InMsec"] == 1000
    assert hot_a["OutMsec"] == -1
    assert hot_a["ColorTableIndex"] == 18
    assert hot_a["Color"] == -1
    assert hot_a["Comment"] == "First Beat"
    assert hot_a["ActiveLoop"] == -1
    assert hot_a["OutFrame"] == -1
    assert hot_a["OutMpegFrame"] == -1
    assert hot_a["OutMpegAbs"] == -1

    # Check loop cue: pad B (kind=2, is_loop)
    hot_b = next(r for r in hot_rows if r["Kind"] == 2)
    assert hot_b["InMsec"] == 2000
    assert hot_b["OutMsec"] == int(2000.0 + 7500.0)  # 9500
    assert hot_b["ActiveLoop"] == 0
    assert hot_b["OutFrame"] == 0
    assert hot_b["OutMpegFrame"] == 0
    assert hot_b["OutMpegAbs"] == 0

    # All memory cues should have Kind=0
    for row in mem_rows:
        assert row["Kind"] == 0

    # Check memory cue for slot 1 (pad A)
    mem_1 = mem_rows[0]  # first in iteration order
    assert mem_1["Comment"] == "First Beat"
    assert mem_1["Color"] == 4
    assert mem_1["InMsec"] == 500


# ---------------------------------------------------------------------------
# Test 3: build_cue_rows skips skipped cues
# ---------------------------------------------------------------------------


def test_build_cue_rows_skips_skipped_cues():
    from djcues.writer import build_cue_rows

    hot_cues = _make_hot_cues(statuses={"B": "skipped", "H": "skipped"})
    memory_cues = _make_memory_cues(statuses={"2": "skipped", "8": "skipped"})

    hot_rows, mem_rows = build_cue_rows(hot_cues, memory_cues)

    assert len(hot_rows) == 6
    assert len(mem_rows) == 6

    # Kind 2 (B) and Kind 9 (H) should not be present
    hot_kinds = {r["Kind"] for r in hot_rows}
    assert 2 not in hot_kinds
    assert 9 not in hot_kinds


# ---------------------------------------------------------------------------
# Test 4: build_cue_rows handles auto status
# ---------------------------------------------------------------------------


def test_build_cue_rows_handles_auto_status():
    from djcues.writer import build_cue_rows

    hot_cues = _make_hot_cues()
    memory_cues = _make_memory_cues(statuses={"3": "auto"})

    hot_rows, mem_rows = build_cue_rows(hot_cues, memory_cues)

    # "auto" should be treated as accepted — all 8 memory rows present
    assert len(mem_rows) == 8


def test_backup_database_to_documents(tmp_path):
    from djcues.writer import backup_database_to_documents

    db_dir = tmp_path / "rekordbox"
    db_dir.mkdir()
    fake_db = db_dir / "master.db"
    fake_db.write_bytes(b"sqlite-real-content")
    fake_wal = db_dir / "master.db-wal"
    fake_wal.write_bytes(b"wal-data")

    fake_docs = tmp_path / "Documents"
    fake_docs.mkdir()

    dest = backup_database_to_documents(fake_db, documents_dir=fake_docs)

    assert dest.exists()
    assert dest.name == "master.db"
    assert dest.read_bytes() == b"sqlite-real-content"
    assert dest.parent.parent == fake_docs / "rekordbox databse backup"
    assert (dest.parent / "master.db-wal").read_bytes() == b"wal-data"


def test_apply_session_asks_for_backup(tmp_path, monkeypatch):
    import json
    from unittest.mock import MagicMock
    import click
    import djcues.db
    from djcues.writer import apply_session

    # Setup fake DB dir & session file
    db_dir = tmp_path / "db_dir"
    db_dir.mkdir()
    (db_dir / "master.db").write_bytes(b"db-bytes")

    fake_docs = tmp_path / "MyDocs"
    fake_docs.mkdir()
    monkeypatch.setattr("djcues.writer.get_documents_dir", lambda: fake_docs)

    mock_db = MagicMock()
    mock_db.db_directory = db_dir
    mock_db.get_cue.return_value = []
    monkeypatch.setattr(djcues.db, "get_db", lambda: mock_db)

    session_file = tmp_path / "session.json"
    session_file.write_text(json.dumps({"tracks": {}}), encoding="utf-8")

    # Case 1: User confirms backup ("y")
    monkeypatch.setattr(click, "confirm", lambda *args, **kwargs: True)
    apply_session(session_file, dry_run=False, force=True, backup=None)

    backup_root = fake_docs / "rekordbox databse backup"
    assert backup_root.exists()
    subdirs = list(backup_root.iterdir())
    assert len(subdirs) == 1
    assert (subdirs[0] / "master.db").read_bytes() == b"db-bytes"

    # Case 2: User declines backup ("n")
    monkeypatch.setattr(click, "confirm", lambda *args, **kwargs: False)
    apply_session(session_file, dry_run=False, force=True, backup=None)
    # Still only 1 backup folder (no new backup created)
    assert len(list(backup_root.iterdir())) == 1


def test_build_cue_rows_respects_no_loops_and_16_pads():
    from djcues.writer import build_cue_rows

    hot_cues = {
        "B": {"status": "accepted", "position_ms": 2000.0, "loop_end_ms": None},
        "P": {"status": "accepted", "position_ms": 16000.0, "loop_end_ms": None},
    }
    memory_cues = {
        "2": {"status": "accepted", "position_ms": 2000.0, "loop_end_ms": None},
        "16": {"status": "accepted", "position_ms": 16000.0, "loop_end_ms": None},
    }
    hot_rows, mem_rows = build_cue_rows(hot_cues, memory_cues)
    assert len(hot_rows) == 2
    assert len(mem_rows) == 2
    for row in hot_rows + mem_rows:
        assert row["OutMsec"] == -1
        assert row["ActiveLoop"] == -1


def test_build_cue_rows_sets_active_loop_1():
    from djcues.writer import build_cue_rows

    hot_cues = {}
    memory_cues = {
        "9": {
            "status": "accepted",
            "position_ms": 210000.0,
            "loop_end_ms": 225000.0,
            "comment": "Auto-Backup Loop (Active)",
            "active_loop": True,
        }
    }
    _, mem_rows = build_cue_rows(hot_cues, memory_cues)
    assert len(mem_rows) == 1
    row = mem_rows[0]
    assert row["Kind"] == 0
    assert row["InMsec"] == 210000
    assert row["OutMsec"] == 225000
    assert row["ActiveLoop"] == 1
    assert row["Color"] == 5
    assert row["Comment"] == "Auto-Backup Loop (Active)"
