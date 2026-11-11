"""Write cue data to the rekordbox database."""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
from datetime import datetime
from uuid import uuid4

from djcues.constants import ALL_CUE_SLOTS, CUE_SYSTEM, CUE_SYSTEM_BY_PAD


def get_documents_dir() -> pathlib.Path:
    """Return the user's Documents folder across Windows and Unix systems."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5 (My Documents)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return pathlib.Path(buf.value)
        except Exception:
            pass
    return pathlib.Path.home() / "Documents"


def _format_ms(ms: float) -> str:
    """Format milliseconds as M:SS.s"""
    total_seconds = ms / 1000
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:04.1f}"


def backup_database(db_path: pathlib.Path) -> pathlib.Path:
    """Copy master.db to a timestamped backup next to the DB. Returns the backup path."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = db_path.stem
    backup_name = f"{stem}-backup-{timestamp}.db"
    backup_path = db_path.parent / backup_name
    shutil.copy2(db_path, backup_path)
    return backup_path


def backup_database_to_documents(
    db_path: pathlib.Path,
    documents_dir: pathlib.Path | None = None,
) -> pathlib.Path:
    """Create a timestamped backup folder inside '<Documents>/rekordbox databse backup'.

    Copies master.db (and WAL/SHM companion files if present) into the timestamped folder.
    Returns the backed-up master.db path.
    """
    docs = documents_dir if documents_dir is not None else get_documents_dir()
    backup_root = docs / "rekordbox databse backup"
    timestamp_folder = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target_dir = backup_root / timestamp_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    dest = target_dir / db_path.name
    shutil.copy2(db_path, dest)

    # Also copy SQLite companion files (-wal, -shm) if present for DB consistency
    for suffix in ("-wal", "-shm"):
        companion = pathlib.Path(f"{db_path}{suffix}")
        if companion.exists():
            shutil.copy2(companion, target_dir / companion.name)

    return dest


def build_cue_rows(
    cues: dict, memory_cues: dict
) -> tuple[list[dict], list[dict]]:
    """Convert session cue data into lists of field dicts for DjmdCue creation.

    Hot cues are keyed by pad letter A-H; memory cues by slot number "1"-"8".
    Skips entries with status "skipped". Treats "auto" and "adjusted" as accepted.
    """
    hot_rows: list[dict] = []
    mem_rows: list[dict] = []

    # --- Hot cues ---
    for pad, slot in CUE_SYSTEM_BY_PAD.items():
        entry = cues.get(pad)
        if entry is None:
            continue
        if entry.get("status") == "skipped":
            continue

        is_loop = entry.get("loop_end_ms") is not None
        in_msec = int(entry["position_ms"])
        if is_loop:
            out_msec = int(entry["loop_end_ms"])
        else:
            out_msec = -1

        is_active = bool(entry.get("active_loop", False)) and is_loop
        hot_rows.append({
            "Kind": slot.kind,
            "InMsec": in_msec,
            "InFrame": 0,
            "InMpegFrame": 0,
            "InMpegAbs": 0,
            "OutMsec": out_msec,
            "OutFrame": 0 if is_loop else -1,
            "OutMpegFrame": 0 if is_loop else -1,
            "OutMpegAbs": 0 if is_loop else -1,
            "Color": slot.hot_cue_color,
            "ColorTableIndex": slot.hot_cue_color_table_index,
            "ActiveLoop": 1 if is_active else (0 if is_loop else -1),
            "Comment": entry.get("comment") or slot.hot_cue_label,
            "BeatLoopSize": 0,
            "CueMicrosec": 0,
        })

    # --- Memory cues ---
    for slot_num_str, entry in memory_cues.items():
        if entry.get("status") == "skipped":
            continue

        slot_idx = int(slot_num_str) - 1
        slot = ALL_CUE_SLOTS[slot_idx] if slot_idx < len(ALL_CUE_SLOTS) else ALL_CUE_SLOTS[-1]

        is_loop = entry.get("loop_end_ms") is not None
        is_active = bool(entry.get("active_loop", False)) and is_loop
        in_msec = int(entry["position_ms"])
        if is_loop:
            out_msec = int(entry["loop_end_ms"])
        else:
            out_msec = -1

        mem_color = 5 if is_active else slot.memory_cue_color
        mem_rows.append({
            "Kind": 0,
            "InMsec": in_msec,
            "InFrame": 0,
            "InMpegFrame": 0,
            "InMpegAbs": 0,
            "OutMsec": out_msec,
            "OutFrame": 0 if is_loop else -1,
            "OutMpegFrame": 0 if is_loop else -1,
            "OutMpegAbs": 0 if is_loop else -1,
            "Color": mem_color,
            "ColorTableIndex": 0 if is_active else slot.memory_cue_color_table_index,
            "ActiveLoop": 1 if is_active else (0 if is_loop else -1),
            "Comment": entry.get("comment") or slot.memory_cue_label,
            "BeatLoopSize": 0,
            "CueMicrosec": 0,
        })

    return hot_rows, mem_rows


def write_cues_for_track(db, content, hot_rows, mem_rows, overwrite=False) -> int:
    """Write cue rows to the DB.

    If overwrite is True, deletes existing cues first.
    Returns the count of cues written.
    """
    try:
        from pyrekordbox.masterdb import DjmdCue
    except ImportError:
        from pyrekordbox.db6.tables import DjmdCue

    if overwrite:
        existing = db.get_cue(ContentID=content.ID)
        for cue in existing:
            db.delete(cue)

    count = 0
    for row in hot_rows + mem_rows:
        cue_id = db.generate_unused_id(DjmdCue)
        cue_uuid = str(uuid4())
        cue = DjmdCue.create(
            ID=str(cue_id),
            ContentID=str(content.ID),
            ContentUUID=content.UUID,
            UUID=cue_uuid,
            **row,
        )
        db.add(cue)
        count += 1

    return count


def apply_session(session_path, dry_run=False, force=False, backup: bool | None = None) -> dict:
    """Read a session JSON file, show summary, optionally back up DB to Documents, and write cues.

    One commit per track. Returns a summary dict.
    """
    import click
    from djcues.db import get_db

    session_path = pathlib.Path(session_path)
    with open(session_path, encoding="utf-8") as f:
        session = json.load(f)

    tracks = session.get("tracks", {})

    # Count statuses
    accepted = 0
    adjusted = 0
    skipped = 0
    overwrite_ids: list[str] = []

    for track_id, track_data in tracks.items():
        status = track_data.get("status", "")
        if status == "accepted":
            accepted += 1
        elif status == "adjusted":
            adjusted += 1
        elif status == "skipped":
            skipped += 1

        if status in ("accepted", "adjusted"):
            if track_data.get("has_existing_cues", False):
                overwrite_ids.append(track_id)

    total_write = accepted + adjusted

    click.echo(f"Session: {session_path.name}")
    click.echo(f"  Accepted: {accepted}  Adjusted: {adjusted}  Skipped: {skipped}")
    click.echo(f"  Tracks to write: {total_write}")
    if overwrite_ids:
        click.echo(f"  Tracks with existing cues (overwrite): {len(overwrite_ids)}")

    result = {
        "accepted": accepted,
        "adjusted": adjusted,
        "skipped": skipped,
        "written": 0,
        "cues_written": 0,
    }

    if dry_run:
        click.echo("Dry run — no changes written.")
        return result

    db = get_db()
    if backup is None:
        docs_backup_root = get_documents_dir() / "rekordbox databse backup"
        do_backup = click.confirm(
            f"Möchtest du vorher ein Backup der Rekordbox-Datenbank in '{docs_backup_root}' (Ordner mit Datum & Uhrzeit) erstellen?",
            default=True,
        )
    else:
        do_backup = backup

    if do_backup:
        backup_path = backup_database_to_documents(db.db_directory / "master.db")
        click.echo(f"Backup gespeichert in: {backup_path}")
    else:
        click.echo("Backup übersprungen — fahre ohne Backup fort.")

    written = 0
    cues_written = 0

    # Check DB for existing cues at apply time (not just session flag)
    tracks_with_existing: dict[str, list] = {}  # track_id -> existing cue list
    for track_id, track_data in tracks.items():
        status = track_data.get("status", "")
        if status not in ("accepted", "adjusted"):
            continue
        existing = list(db.get_cue(ContentID=int(track_id)))
        if existing:
            tracks_with_existing[track_id] = existing

    if tracks_with_existing and not force:
        from djcues.constants import KIND_TO_PAD

        click.echo(f"\n{len(tracks_with_existing)} track(s) have existing cues that will be replaced:\n")
        for track_id, existing in tracks_with_existing.items():
            track_data = tracks[track_id]
            title = track_data.get("title", track_id)
            click.echo(f"  {title}")

            # Show existing cues
            existing_hot = sorted([c for c in existing if c.Kind > 0], key=lambda c: c.Kind)
            existing_mem = [c for c in existing if c.Kind == 0]
            click.echo(f"    Existing: {len(existing_hot)} hot, {len(existing_mem)} memory")
            for c in existing_hot:
                pad = KIND_TO_PAD.get(c.Kind, "?")
                click.echo(f"      [{pad}] {c.Comment or '?':20s} {_format_ms(c.InMsec)}")

            # Show proposed cues
            hot_data = track_data.get("cues", {})
            new_hot = [(p, d) for p, d in hot_data.items() if d.get("status") != "skipped"]
            new_mem = [(n, d) for n, d in track_data.get("memory_cues", {}).items() if d.get("status") != "skipped"]
            click.echo(f"    Proposed: {len(new_hot)} hot, {len(new_mem)} memory")
            for pad, d in sorted(new_hot):
                from djcues.constants import CUE_SYSTEM_BY_PAD
                slot = CUE_SYSTEM_BY_PAD.get(pad)
                label = slot.hot_cue_label if slot else pad
                click.echo(f"      [{pad}] {label:20s} {_format_ms(d['position_ms'])}")
            click.echo()

        click.confirm("Continue?", abort=True)

    for track_id, track_data in tracks.items():
        status = track_data.get("status", "")
        if status not in ("accepted", "adjusted"):
            continue

        hot_cues_data = track_data.get("cues", {})
        mem_cues_data = track_data.get("memory_cues", {})
        hot_rows, mem_rows = build_cue_rows(hot_cues_data, mem_cues_data)

        content = db.get_content(ID=int(track_id))
        overwrite = track_id in tracks_with_existing.keys()
        count = write_cues_for_track(db, content, hot_rows, mem_rows, overwrite=overwrite)
        db.commit()

        title = track_data.get("title", f"ID {track_id}")
        click.echo(f"  Wrote {count} cues for {title}")
        written += 1
        cues_written += count

    result["written"] = written
    result["cues_written"] = cues_written
    click.echo(f"Done: {written} tracks, {cues_written} cues written.")
    return result
