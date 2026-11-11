"""Read tracks, cues, and phrase data from the rekordbox database."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import pyrekordbox

try:
    from pyrekordbox.masterdb import MasterDatabase as RekordboxDatabase
except ImportError:
    from pyrekordbox import Rekordbox6Database as RekordboxDatabase

from djcues.constants import resolve_phrase_label
from djcues.models import BeatGrid, CuePoint, Phrase, Track, WaveformPoint

logger = logging.getLogger(__name__)


@dataclass
class RekordboxInstallation:
    """Represents a detected Rekordbox 6 or 7 installation/database."""

    version_major: int  # 6 or 7
    version_str: str
    db_path: pathlib.Path
    install_dir: pathlib.Path | None = None


_db: RekordboxDatabase | None = None
_selected_db_path: pathlib.Path | None = None
_selected_version: int | None = None
_active_info: RekordboxInstallation | None = None


def _parse_settings_db_dir(settings_file: pathlib.Path) -> pathlib.Path | None:
    """Extract masterDbDirectory from Rekordbox's rekordbox3.settings XML."""
    if not settings_file.exists():
        return None
    try:
        tree = ET.parse(settings_file)
        for elem in tree.getroot().iter("VALUE"):
            if elem.attrib.get("name") == "masterDbDirectory":
                val = elem.attrib.get("val", "").strip()
                if val:
                    return pathlib.Path(val)
    except Exception:
        pass
    return None


def _find_program_installs() -> dict[int, tuple[str, pathlib.Path]]:
    """Scan standard and custom drives on Windows/macOS for Rekordbox 6 & 7 installs."""
    found: dict[int, tuple[str, pathlib.Path]] = {}
    candidates: list[pathlib.Path] = []

    if sys.platform == "win32":
        roots: list[pathlib.Path] = []
        for env_key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
            val = os.environ.get(env_key)
            if val:
                roots.append(pathlib.Path(val.replace(" (x86)", "")))
        # Also scan common drives in case Rekordbox was installed on D:, E:, K:, etc.
        for drive in ("C:", "D:", "E:", "F:", "G:", "K:"):
            pf = pathlib.Path(f"{drive}/Program Files")
            if pf.exists() and pf not in roots:
                roots.append(pf)

        for r in roots:
            pioneer_dir = r / "Pioneer"
            if pioneer_dir.exists():
                candidates.extend(pioneer_dir.glob("rekordbox 6*"))
                candidates.extend(pioneer_dir.glob("rekordbox 7*"))
            rb_dir = r / "rekordbox"
            if rb_dir.exists():
                candidates.extend(rb_dir.glob("rekordbox 7*"))
                candidates.extend(rb_dir.glob("rekordbox 6*"))
    elif sys.platform == "darwin":
        apps = pathlib.Path("/Applications")
        if apps.exists():
            candidates.extend(apps.glob("rekordbox 6*"))
            candidates.extend(apps.glob("rekordbox 7*"))

    for c in candidates:
        name_lower = c.name.lower()
        ver = c.name.replace("rekordbox", "").replace(".app", "").strip()
        if ver.startswith("7") or " 7" in name_lower:
            found[7] = (ver or "7.x", c)
        elif ver.startswith("6") or " 6" in name_lower:
            found[6] = (ver or "6.x", c)

    return found


def detect_rekordbox_configs() -> list[RekordboxInstallation]:
    """Detect all available Rekordbox 6 and 7 installations and master.db files.

    Works even when pyrekordbox's built-in ProgramFiles scan fails (e.g. custom
    install drives, mismatched ProgramFiles(x86), or standalone DB folders).
    """
    installs: list[RekordboxInstallation] = []
    seen_keys: set[tuple[int, str]] = set()

    def _add(ver_major: int, ver_str: str, db_path: pathlib.Path, install_dir: pathlib.Path | None = None) -> None:
        if not db_path.exists() or not db_path.is_file():
            return
        norm = str(db_path.resolve()).lower() if sys.platform == "win32" else str(db_path.resolve())
        key = (ver_major, norm)
        if key not in seen_keys:
            seen_keys.add(key)
            installs.append(RekordboxInstallation(
                version_major=ver_major,
                version_str=ver_str,
                db_path=db_path,
                install_dir=install_dir,
            ))

    # 1. Check pyrekordbox's built-in config first
    for ver_major, cfg_name in ((7, "rekordbox7"), (6, "rekordbox6")):
        try:
            cfg = pyrekordbox.get_config(cfg_name)
            if cfg and cfg.get("db_path"):
                _add(
                    ver_major,
                    str(cfg.get("version") or f"{ver_major}.x"),
                    pathlib.Path(cfg["db_path"]),
                    pathlib.Path(cfg["install_dir"]) if cfg.get("install_dir") else None,
                )
        except Exception:
            pass

    # 2. Scan Pioneer app data & custom install drives
    app_roots: list[pathlib.Path] = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            app_roots.append(pathlib.Path(appdata) / "Pioneer")
    app_roots.append(pathlib.Path.home() / "Library/Pioneer")

    prog_installs = _find_program_installs()

    # Check options.json and rekordbox3.settings
    discovered_dbs: list[pathlib.Path] = []
    opts_ver: str = ""
    for root in app_roots:
        if not root.exists():
            continue
        opt_file = root / "rekordboxAgent/storage/options.json"
        if opt_file.exists():
            try:
                data = json.loads(opt_file.read_text(encoding="utf-8"))
                for pair in data.get("options", []):
                    if len(pair) == 2 and pair[0] == "db-path":
                        discovered_dbs.append(pathlib.Path(pair[1]))
                    elif len(pair) == 2 and pair[0] == "app_ver":
                        opts_ver = str(pair[1])
            except Exception:
                pass
        for sub in ("rekordbox7", "rekordbox6", "rekordbox"):
            s_dir = _parse_settings_db_dir(root / sub / "rekordbox3.settings")
            if s_dir:
                discovered_dbs.append(s_dir / "master.db")
            direct_db = root / sub / "master.db"
            if direct_db.exists():
                discovered_dbs.append(direct_db)

    valid_dbs = [p for p in discovered_dbs if p.exists() and p.is_file()]
    fallback_db = valid_dbs[0] if valid_dbs else None

    # Register detected program installations paired with valid DBs
    for ver_major in (7, 6):
        if ver_major in prog_installs and fallback_db is not None:
            ver_str, inst_dir = prog_installs[ver_major]
            _add(ver_major, ver_str, fallback_db, inst_dir)

    # If no Program Files folder was found at all, still register any valid master.db found
    if not installs and fallback_db is not None:
        inferred_ver = 7 if opts_ver.startswith("7") else 6
        _add(inferred_ver, opts_ver or f"{inferred_ver}.x (DB)", fallback_db, None)

    installs.sort(key=lambda i: (-i.version_major, i.version_str))
    return installs


def get_active_db_info() -> RekordboxInstallation | None:
    """Return metadata about the currently active Rekordbox DB connection."""
    return _active_info


def configure_db(
    version: int | None = None,
    db_path: str | pathlib.Path | None = None,
) -> RekordboxDatabase:
    """Explicitly select Rekordbox v6, v7, or a custom master.db path."""
    global _db, _selected_db_path, _selected_version, _active_info

    if _db is not None:
        try:
            _db.close()
        except Exception:
            pass
        _db = None

    _active_info = None
    _selected_version = version

    if db_path is not None:
        p = pathlib.Path(str(db_path).strip().strip('"').strip("'"))
        if p.is_dir():
            p = p / "master.db"
        if not p.exists():
            raise FileNotFoundError(f"Rekordbox Datenbank nicht gefunden: '{p}'")
        _selected_db_path = p
    else:
        _selected_db_path = None

    return get_db()


def get_db() -> RekordboxDatabase:
    """Get or create the shared database connection."""
    global _db, _active_info
    if _db is not None:
        return _db

    if _selected_db_path is not None:
        _db = RekordboxDatabase(path=_selected_db_path, db_dir=_selected_db_path.parent)
        ver = _selected_version or 7
        _active_info = RekordboxInstallation(
            version_major=ver,
            version_str=f"Custom (v{ver})",
            db_path=_selected_db_path,
        )
        return _db

    configs = detect_rekordbox_configs()
    if _selected_version is not None:
        matched = [c for c in configs if c.version_major == _selected_version]
        if matched:
            cfg = matched[0]
            _db = RekordboxDatabase(path=cfg.db_path, db_dir=cfg.db_path.parent)
            _active_info = cfg
            return _db
        if configs:
            cfg = configs[0]
            logger.warning("Rekordbox v%s not found; using v%s instead.", _selected_version, cfg.version_major)
            _db = RekordboxDatabase(path=cfg.db_path, db_dir=cfg.db_path.parent)
            _active_info = cfg
            return _db

    if configs:
        cfg = configs[0]
        _db = RekordboxDatabase(path=cfg.db_path, db_dir=cfg.db_path.parent)
        _active_info = cfg
        return _db

    # Final fallback to pyrekordbox default (also supports mocked MasterDatabase in tests)
    _db = RekordboxDatabase()
    return _db


def find_playlist(name: str) -> Any | None:
    """Find a playlist by exact name. Returns the pyrekordbox playlist object or None.

    Prefers actual playlists over folders when names collide.
    Attribute: 0 or -128 = playlist, 1 = folder.
    """
    db = get_db()
    folder_match = None
    for pl in db.get_playlist():
        if pl.Name == name:
            if pl.Attribute != 1:
                return pl  # actual playlist — return immediately
            folder_match = pl  # folder — keep as fallback
    return folder_match


def _extract_beat_grid(track_content: Any) -> BeatGrid:
    """Extract BPM and first beat position from a track's analysis files."""
    db = get_db()
    bpm = track_content.BPM / 100

    # Try to get first beat from ANLZ beat grid
    first_beat_ms = 0.0
    try:
        anlz_files = db.read_anlz_files(track_content)
        for path, af in anlz_files.items():
            if path.suffix == ".DAT":
                for tag in af.tags:
                    if type(tag).__name__ == "PQTZAnlzTag":
                        times = tag.get_times()
                        if len(times) > 0:
                            # times are in seconds, convert to ms
                            first_beat_ms = float(times[0]) * 1000
                        break
    except Exception as e:
        logger.warning("Could not read beat grid for %s: %s", track_content.Title, e)

    return BeatGrid(first_beat_ms=first_beat_ms, bpm=bpm)


def _extract_phrases(track_content: Any, beat_grid: BeatGrid) -> list[Phrase]:
    """Extract PSSI phrase structure from a track's ANLZ EXT file."""
    db = get_db()
    phrases: list[Phrase] = []

    try:
        anlz_files = db.read_anlz_files(track_content)
        for path, af in anlz_files.items():
            if path.suffix == ".EXT":
                for tag in af.tags:
                    if type(tag).__name__ == "PSSIAnlzTag":
                        content = tag.content
                        mood = content.mood
                        entries = list(content.entries)

                        for i, entry in enumerate(entries):
                            next_beat = (
                                entries[i + 1].beat
                                if i + 1 < len(entries)
                                else content.end_beat
                            )
                            label = resolve_phrase_label(mood, entry.kind)
                            pos_ms = beat_grid.beat_to_ms(entry.beat)
                            end_ms = beat_grid.beat_to_ms(next_beat)

                            phrases.append(Phrase(
                                beat_start=entry.beat,
                                beat_end=next_beat,
                                kind=entry.kind,
                                label=label,
                                position_ms=pos_ms,
                                duration_ms=end_ms - pos_ms,
                            ))
                        break  # only process first PSSI tag
    except Exception as e:
        logger.debug("Library PSSI parser failed for %s; trying raw decoder: %s", track_content.Title, e)

    if not phrases:
        try:
            paths = db.get_anlz_paths(track_content)
            path = paths.get("EXT")
            if path is not None and path.exists():
                phrases = _decode_phrase_file(path.read_bytes(), beat_grid)
        except Exception as e:
            logger.warning("Could not read phrases for %s: %s", track_content.Title, e)

    return phrases


def _decode_phrase_file(data: bytes, beat_grid: BeatGrid) -> list[Phrase]:
    """Decode PSSI tags from raw ANLZ bytes without unrelated tag parsing."""
    import struct

    pos = 0
    if data[:4] in (b"PMAI", b"ANLZ") and len(data) >= 8:
        file_header_len = struct.unpack_from(">I", data, 4)[0]
        if 12 <= file_header_len <= len(data):
            pos = file_header_len

    while pos + 12 <= len(data):
        tag_type = data[pos : pos + 4]
        if not tag_type.isascii():
            pos += 1
            continue
        header_len, tag_len = struct.unpack_from(">II", data, pos + 4)
        if header_len < 12 or tag_len < header_len or pos + tag_len > len(data):
            pos += 1
            continue
        if tag_type == b"PSSI":
            return _decode_phrase_tag(data[pos : pos + tag_len], header_len, beat_grid)
        pos += tag_len
    return []


def _decode_phrase_tag(tag_data: bytes, header_len: int, beat_grid: BeatGrid) -> list[Phrase]:
    """Decode one PSSI tag using its 24-byte entry records."""
    import struct

    content = tag_data[header_len:]
    if len(content) < 20:
        return []
    entry_bytes, entry_count, mood = struct.unpack_from(">IHH", content, 0)
    end_beat = struct.unpack_from(">H", content, 14)[0]
    if entry_bytes < 24:
        return []
    available = (len(content) - 20) // entry_bytes
    count = min(entry_count, available)
    entries: list[tuple[int, int]] = []
    for index in range(count):
        offset = 20 + index * entry_bytes
        beat, kind = struct.unpack_from(">HH", content, offset + 2)
        entries.append((beat, kind))

    phrases: list[Phrase] = []
    for index, (beat, kind) in enumerate(entries):
        next_beat = entries[index + 1][0] if index + 1 < len(entries) else end_beat
        if next_beat <= beat:
            continue
        position_ms = beat_grid.beat_to_ms(beat)
        end_ms = beat_grid.beat_to_ms(next_beat)
        phrases.append(Phrase(
            beat_start=beat,
            beat_end=next_beat,
            kind=kind,
            label=resolve_phrase_label(mood, kind),
            position_ms=position_ms,
            duration_ms=end_ms - position_ms,
        ))
    return phrases


def _extract_cues(track_content: Any) -> list[CuePoint]:
    """Extract cue points from the database."""
    db = get_db()
    cues: list[CuePoint] = []

    for c in db.get_cue(ContentID=track_content.ID):
        loop_end = None
        if c.OutMsec is not None and c.OutMsec > 0:
            loop_end = float(c.OutMsec)

        cues.append(CuePoint(
            kind=c.Kind,
            position_ms=float(c.InMsec),
            loop_end_ms=loop_end,
            color_table_index=c.ColorTableIndex,
            color=c.Color if c.Color is not None else -1,
            comment=c.Comment or "",
        ))

    return cues


def _extract_waveform(track_content: Any, max_points: int = 800) -> list[WaveformPoint] | None:
    """Extract waveforms from Rekordbox 6/7 ANLZ files.

    The complete pyrekordbox Construct parser can fail on one newer or
    malformed tag and then hide all other tags. We therefore scan the raw
    ANLZ framing and decode PWV3/PWV5 (EXT) plus PWV6/PWV7 (2EX) ourselves.
    """
    db = get_db()
    try:
        # This only resolves paths; unlike read_anlz_files it does not parse
        # every tag and survives a bad PWV5 block.
        paths = db.get_anlz_paths(track_content)
        for key in ("EXT", "2EX", "DAT"):
            path = paths.get(key)
            if path is None or not path.exists():
                continue
            points = _decode_waveform_file(path.read_bytes(), max_points)
            if points:
                return points
    except Exception as e:
        logger.warning("Could not read waveform for %s: %s", track_content.Title, e)
    return None


def _decode_waveform_file(data: bytes, max_points: int = 800) -> list[WaveformPoint]:
    """Decode waveform tags from raw ANLZ bytes without Construct parsing.

    Prefers the highest-resolution color/3-band waveform available in the file
    (PWV7 > PWV5 > PWV3 > PWV6 > PWV4) rather than concatenating multiple tags.
    """
    import struct

    decoded_by_tag: dict[str, list[WaveformPoint]] = {}
    pos = 0
    if data[:4] in (b"PMAI", b"ANLZ") and len(data) >= 8:
        file_header_len = struct.unpack_from(">I", data, 4)[0]
        if 12 <= file_header_len <= len(data):
            pos = file_header_len
    while pos + 12 <= len(data):
        tag_type = data[pos : pos + 4]
        if not tag_type.isascii():
            pos += 1
            continue
        header_len, tag_len = struct.unpack_from(">II", data, pos + 4)
        if header_len < 12 or tag_len < header_len or pos + tag_len > len(data):
            # Recover from an invalid block and search for a later valid tag.
            pos += 1
            continue
        if tag_type in (b"PWV3", b"PWV4", b"PWV5", b"PWV6", b"PWV7"):
            tag_name = tag_type.decode("ascii")
            pts = _decode_waveform_tag(tag_name, header_len, data[pos : pos + tag_len])
            if pts:
                decoded_by_tag[tag_name] = pts
        pos += tag_len

    for preferred in ("PWV7", "PWV5", "PWV3", "PWV6", "PWV4"):
        if preferred in decoded_by_tag:
            return _downsample_waveform(decoded_by_tag[preferred], max_points)
    return []


def _decode_waveform_tag(tag_type: str, header_len: int, tag_data: bytes) -> list[WaveformPoint]:
    """Decode one PWV tag, tolerating Rekordbox 6/7 header variants."""
    import struct

    if len(tag_data) < header_len:
        return []
    body = tag_data[header_len:]

    if tag_type == "PWV5":
        # Two-byte packed RGB/height entries. Trust payload size over a stale
        # entry count found in some Rekordbox-generated files.
        if len(body) >= 12:
            declared = struct.unpack_from(">I", body, 0)[0]
            usable_declared = declared * 2
            body = body[12 : 12 + usable_declared] if usable_declared <= len(body) - 12 else body[12:]
        usable = len(body) - (len(body) % 2)
        return [
            WaveformPoint(
                height=((value >> 2) & 0x1F) / 31,
                red=(value >> 12) & 0x07,
                green=(value >> 9) & 0x07,
                blue=(value >> 6) & 0x07,
            )
            for (value,) in struct.iter_unpack(">H", body[:usable])
        ]

    if tag_type == "PWV3":
        body = body[12:] if len(body) >= 12 else b""
        return [WaveformPoint(height=(value & 0x1F) / 31, red=1, green=2, blue=5) for value in body]

    if tag_type == "PWV6":
        body = body[8:] if len(body) >= 8 else b""
        usable = len(body) - (len(body) % 3)
        return [
            WaveformPoint(
                height=max(mid, high, low) / 255,
                red=round(low / 255 * 7),
                green=round(mid / 255 * 7),
                blue=round(high / 255 * 7),
            )
            for mid, high, low in zip(body[:usable:3], body[1:usable:3], body[2:usable:3])
        ]

    if tag_type == "PWV7":
        body = body[12:] if len(body) >= 12 else b""
        usable = len(body) - (len(body) % 3)
        return [
            WaveformPoint(
                height=max(mid, high, low) / 255,
                red=round(low / 255 * 7),
                green=round(mid / 255 * 7),
                blue=round(high / 255 * 7),
            )
            for mid, high, low in zip(body[:usable:3], body[1:usable:3], body[2:usable:3])
        ]

    if tag_type == "PWV4":
        body = body[12:] if len(body) >= 12 else b""
        usable = len(body) - (len(body) % 6)
        result: list[WaveformPoint] = []
        for i in range(0, usable, 6):
            _, d2, d3, d4, d5 = body[i + 1 : i + 6]
            result.append(WaveformPoint(
                height=max(d2, d3, d4, d5 & 0x7F) / 127,
                red=round((d3 & 0x7F) / 127 * 7),
                green=round((d4 & 0x7F) / 127 * 7),
                blue=round((d5 & 0x7F) / 127 * 7),
            ))
        return result
    return []


def _downsample_waveform(points: list[WaveformPoint], max_points: int) -> list[WaveformPoint]:
    """Keep peak points while limiting inline SVG size."""
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    return [
        max(points[int(i * step) : max(int((i + 1) * step), int(i * step) + 1)], key=lambda point: point.height)
        for i in range(max_points)
    ]


def _extract_vocal_track(track_content: Any) -> list[int] | None:
    """Extract PVDI vocal detection data from the .2EX ANLZ file.

    Returns a list of per-frame vocal confidence values (0-4),
    where each frame covers 1024/22050 ≈ 46.4ms.
    """
    import struct
    try:
        db = get_db()
        paths = db.get_anlz_paths(track_content)
        ex2_path = paths.get("2EX")
        if not ex2_path or not ex2_path.exists():
            return None
        with open(ex2_path, "rb") as f:
            data = f.read()
        pos = data.find(b"PVDI")
        if pos < 0:
            return None
        header_len = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
        tag_len = struct.unpack(">I", data[pos + 8 : pos + 12])[0]
        body = data[pos + header_len : pos + tag_len]
        return list(body)
    except Exception as e:
        logger.warning("Could not read vocal track for %s: %s", track_content.Title, e)
        return None


def load_track(track_content: Any) -> Track:
    """Load a single track with all analysis data."""
    beat_grid = _extract_beat_grid(track_content)
    phrases = _extract_phrases(track_content, beat_grid)
    cues = _extract_cues(track_content)
    waveform = _extract_waveform(track_content)
    vocal_track = _extract_vocal_track(track_content)

    artist_name = ""
    if track_content.Artist:
        artist_name = track_content.Artist.Name or ""

    return Track(
        id=track_content.ID,
        title=track_content.Title or "",
        artist=artist_name,
        bpm=track_content.BPM / 100,
        duration_ms=float(track_content.Length or 0) * 1000,
        analysis_path=track_content.AnalysisDataPath or "",
        cues=cues,
        phrases=phrases,
        beat_grid=beat_grid,
        waveform=waveform,
        vocal_track=vocal_track,
    )


def load_playlist_tracks(playlist_id: int) -> list[Track]:
    """Load all tracks from a playlist with full analysis data."""
    db = get_db()
    songs = list(db.get_playlist_songs(PlaylistID=playlist_id))
    tracks: list[Track] = []
    for song in songs:
        try:
            tracks.append(load_track(song.Content))
        except Exception as e:
            logger.warning("Skipping track %s: %s", song.Content.Title, e)
    return tracks
