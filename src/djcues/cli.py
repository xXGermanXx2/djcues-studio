"""CLI for djcues — propose and compare cue placements."""

from __future__ import annotations

import json
import logging
import sys
import warnings
import click

if sys.platform == "win32":
    # Ensure Windows console handles UTF-8 for track titles and special characters
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Suppress noisy pyrekordbox warnings (PVDI tag, rekordbox running, etc.)
for _name in ("pyrekordbox", "pyrekordbox.db6", "pyrekordbox.anlz", "pyrekordbox.masterdb"):
    logging.getLogger(_name).setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", module="pyrekordbox")

from djcues.constants import CUE_SYSTEM_BY_PAD, KIND_TO_PAD, GENRE_PROFILES, get_genre_profile
from djcues.db import (
    configure_db,
    detect_rekordbox_configs,
    find_playlist,
    get_active_db_info,
    get_db,
    load_playlist_tracks,
    load_track,
)
from djcues.strategy import CueStrategy

_rb_session_selected: bool = False


def _format_time(ms: float) -> str:
    """Format milliseconds as M:SS.s"""
    total_seconds = ms / 1000
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:04.1f}"


def _print_proposal(proposal, track):
    """Print a full cue proposal for a single track."""
    click.echo(f"\n{'=' * 60}")
    click.echo(f"  {track.title} — {track.artist}")
    click.echo(f"  BPM: {track.bpm:.1f}")
    click.echo(f"{'=' * 60}")

    # Phrases
    click.echo(f"\n  Phrases ({len(track.phrases)}):")
    for p in track.phrases:
        bars = p.beat_length // 4
        click.echo(
            f"    {p.label:<12s}  beat {p.beat_start:>4d}–{p.beat_end:<4d}"
            f"  ({bars:>2d} bars)  {_format_time(p.position_ms)}"
        )

    # Hot cues (sorted by kind)
    click.echo(f"\n  Hot Cues ({len(proposal.hot_cues)}):")
    for hc in sorted(proposal.hot_cues, key=lambda c: c.kind):
        pad = KIND_TO_PAD.get(hc.kind, "?")
        conf = proposal.confidence.get(pad, 0.0)
        beat = track.beat_grid.ms_to_beat(hc.position_ms)
        loop_info = ""
        if hc.is_loop and hc.loop_end_ms is not None:
            loop_info = f"  loop→{_format_time(hc.loop_end_ms)}"
        click.echo(
            f"    [{pad}] {hc.comment:<20s}  {_format_time(hc.position_ms)}"
            f"  beat {beat:>4d}  conf={conf:.0%}{loop_info}"
        )

    # Memory cues (sorted by position)
    click.echo(f"\n  Memory Cues ({len(proposal.memory_cues)}):")
    for i, mc in enumerate(sorted(proposal.memory_cues, key=lambda c: c.position_ms)):
        slot_info = ""
        # Find which slot this memory cue belongs to by matching comment
        for pad, slot in CUE_SYSTEM_BY_PAD.items():
            if slot.memory_cue_label == mc.comment:
                if slot.memory_offset_bars > 0:
                    slot_info = f"  ({slot.memory_offset_bars} bars before {slot.hot_cue_label})"
                else:
                    slot_info = f"  (same as {slot.hot_cue_label})"
                break
        loop_info = ""
        if mc.is_loop and mc.loop_end_ms is not None:
            tag = "AUTO-LOOP→" if getattr(mc, "active_loop", False) else "loop→"
            loop_info = f"  {tag}{_format_time(mc.loop_end_ms)}"
        active_badge = " [ACTIVE BACKUP]" if getattr(mc, "active_loop", False) else ""
        click.echo(
            f"    [{i + 1}] {mc.comment:<24s}  {_format_time(mc.position_ms)}"
            f"{slot_info}{loop_info}{active_badge}"
        )

    # Notes
    if proposal.notes:
        click.echo(f"\n  Notes:")
        for note in proposal.notes:
            click.echo(f"    • {note}")


def _print_comparison(proposal, track):
    """Print side-by-side comparison of existing vs proposed hot cues."""
    click.echo(f"\n{'=' * 60}")
    click.echo(f"  {track.title} — {track.artist}")
    click.echo(f"  BPM: {track.bpm:.1f}")
    click.echo(f"{'=' * 60}")

    # Build lookup of existing hot cues by kind
    existing_by_kind = {}
    for c in track.cues:
        if c.kind > 0:  # hot cues only (kind > 0)
            existing_by_kind[c.kind] = c

    # Build lookup of proposed hot cues by kind
    proposed_by_kind = {}
    for c in proposal.hot_cues:
        proposed_by_kind[c.kind] = c

    # Get all kinds present in either set
    all_kinds = sorted(set(existing_by_kind.keys()) | set(proposed_by_kind.keys()))

    matches = 0
    total = 0

    click.echo(f"\n  {'Pad':<5s} {'Label':<20s} {'Existing':<12s} {'Proposed':<12s} {'Delta':>8s}")
    click.echo(f"  {'-' * 5} {'-' * 20} {'-' * 12} {'-' * 12} {'-' * 8}")

    for kind in all_kinds:
        pad = KIND_TO_PAD.get(kind, "?")
        slot = CUE_SYSTEM_BY_PAD.get(pad)
        label = slot.hot_cue_label if slot else f"Kind {kind}"

        existing = existing_by_kind.get(kind)
        proposed = proposed_by_kind.get(kind)

        existing_str = _format_time(existing.position_ms) if existing else "—"
        proposed_str = _format_time(proposed.position_ms) if proposed else "—"

        delta_str = ""
        if existing and proposed:
            total += 1
            delta_ms = proposed.position_ms - existing.position_ms
            delta_str = f"{delta_ms:+.0f}ms"
            if abs(delta_ms) <= 1000:
                matches += 1
                delta_str += " ✓"
        elif existing:
            total += 1
            delta_str = "missing"
        elif proposed:
            delta_str = "new"

        click.echo(
            f"  [{pad}]   {label:<20s} {existing_str:<12s} {proposed_str:<12s} {delta_str:>8s}"
        )

    if total > 0:
        pct = matches / total * 100
        click.echo(f"\n  Match rate: {matches}/{total} ({pct:.0f}%) within 1s tolerance")
    else:
        click.echo(f"\n  No existing hot cues to compare.")

    return matches, total


def _menu_choice(title: str, values: list[str]) -> int:
    """Show numbered values and return a zero-based selection."""
    click.echo(f"\n{title}")
    click.echo("-" * len(title))
    for index, value in enumerate(values, start=1):
        click.echo(f"{index}) {value}")
    return click.prompt("Auswahl", type=click.IntRange(1, len(values))) - 1


def _menu_scope() -> tuple[str, str | None, bool]:
    """Select a playlist and then all tracks or one track from that playlist."""
    db = get_db()
    try:
        playlists = [
            pl for pl in db.get_playlist()
            if pl.Attribute != 1 and getattr(pl, "Name", None)
        ]
        playlist_names = list(dict.fromkeys(pl.Name for pl in playlists))
    except Exception:
        playlist_names = []

    if playlist_names:
        playlist = playlist_names[_menu_choice("Playlist auswählen", playlist_names)]
    else:
        click.echo("Keine Playlists konnten automatisch gelesen werden.")
        playlist = click.prompt("Playlist-Name")

    pl_obj = find_playlist(playlist)
    if pl_obj is None:
        raise click.ClickException(f"Playlist '{playlist}' wurde nicht gefunden.")

    songs = list(db.get_playlist_songs(PlaylistID=pl_obj.ID))
    if not songs:
        raise click.ClickException(f"Playlist '{playlist}' enthält keine Tracks.")

    def _song_label(s):
        title = s.Content.Title or "Unbekannt"
        artist = s.Content.Artist.Name if s.Content.Artist else ""
        return f"{title} — {artist}" if artist else title

    track_options = ["Alle Tracks"] + [_song_label(s) for s in songs]
    track_index = _menu_choice("Tracks auswählen", track_options)
    if track_index == 0:
        return playlist, None, True
    return playlist, songs[track_index - 1].Content.Title, False


def _get_tracks_for_scope(playlist, track_name: str | None, all_tracks: bool) -> list[Track]:
    """Retrieve tracks for a CLI command scope efficiently."""
    if all_tracks:
        return load_playlist_tracks(playlist.ID)
    if track_name:
        db = get_db()
        songs = list(db.get_playlist_songs(PlaylistID=playlist.ID))
        matched = [s for s in songs if track_name.lower() in (s.Content.Title or "").lower()]
        if not matched:
            click.echo(f"Error: no track matching '{track_name}' in playlist.", err=True)
            raise SystemExit(1)
        return [load_track(s.Content) for s in matched]
    click.echo("Error: provide a track name or use --all.", err=True)
    raise SystemExit(1)


def _menu_genre() -> tuple[str, dict]:
    """Walkthrough Step 1: Select music genre for personalized cue placement."""
    click.echo("\n--- SCHRITT 1: MUSIK-GENRE AUSWÄHLEN ---")
    click.echo("Wähle dein Genre, um Cues, Loops & Offsets optimal zu personalisieren:\n")
    genre_list = [
        ("industrial", "Industrial Techno", "145–165 BPM | Verzerrte Kicks, Dark Rumbles, 8-Takt-Loops"),
        ("hard_techno", "Hard Techno", "148–165 BPM | Gnadenloser Drive & wuchtige Drops"),
        ("schranz", "Schranz / Emotional", "150–175 BPM | Treibende Schranz-Loops, Vocal-Breaks & Drops"),
        ("hypnotic_groove", "Hypnotic Groove", "136–144 BPM | Modulare Polyrhythmen, 16-Takt-Loops, 32-Takt-Warnung"),
        ("hard_groove", "Hard Groove", "140–150 BPM | Tribal 909 Funk & Percussion Rolls"),
        ("bounce", "Bounce / Hard Bounce", "142–155 BPM | Offbeat-Basslines, Vocal Cuts & zackige Drops"),
        ("trance", "Trance / Hard Trance", "138–148 BPM | Epische Breakdowns, Euphoric Drops & 32-Takt-Warnung"),
        ("auto", "Automatisch nach BPM", "Wählt das Profil anhand des gemessenen Tempos"),
        ("general", "Standard / All-Round", "Klassisches 8-Cue-System für House, EDM, Pop"),
    ]
    options = [f"{name:<22} ({desc})" for _, name, desc in genre_list]
    choice_idx = _menu_choice("Genre auswählen", options)
    key = genre_list[choice_idx][0]
    profile = get_genre_profile(key)
    return key, profile


def _select_rekordbox_version(force_prompt: bool = False) -> None:
    """Detect Rekordbox 6 & 7 and let the user choose which version or DB path to use."""
    global _rb_session_selected
    if _rb_session_selected and not force_prompt:
        return

    configs = detect_rekordbox_configs()

    if not configs:
        click.echo("\n[HINWEIS] Es wurde kein Rekordbox v6/v7 Verzeichnis automatisch gefunden.")
        ver_idx = _menu_choice(
            "Rekordbox Version manuell wählen",
            [
                "Rekordbox 7 (Pfad zu master.db angeben)",
                "Rekordbox 6 (Pfad zu master.db angeben)",
            ],
        )
        ver = 7 if ver_idx == 0 else 6
        custom_path = click.prompt("Pfad zur Rekordbox master.db (Datei reinziehen oder Pfad eingeben)")
        try:
            configure_db(version=ver, db_path=custom_path)
            _rb_session_selected = True
            click.echo(f"[OK] Verbunden mit Rekordbox {ver} Datenbank.")
        except Exception as exc:
            raise click.ClickException(f"Datenbank konnte nicht geöffnet werden: {exc}")
        return

    if len(configs) == 1 and not force_prompt:
        cfg = configs[0]
        configure_db(version=cfg.version_major, db_path=cfg.db_path)
        _rb_session_selected = True
        click.echo(f"[Rekordbox erkannt] Rekordbox {cfg.version_major} (v{cfg.version_str}) — {cfg.db_path}")
        return

    options = [
        f"Rekordbox {c.version_major} (v{c.version_str}) — {c.db_path}"
        for c in configs
    ]
    options.append("Eigenen Pfad zu master.db angeben (v6/v7)")
    idx = _menu_choice("Rekordbox-Version / Datenbank auswählen", options)

    if idx < len(configs):
        chosen = configs[idx]
        configure_db(version=chosen.version_major, db_path=chosen.db_path)
        _rb_session_selected = True
        click.echo(f"[Aktiviert] Rekordbox {chosen.version_major} (v{chosen.version_str})")
    else:
        ver_idx = _menu_choice("Welche Rekordbox Version?", ["Rekordbox 7", "Rekordbox 6"])
        ver = 7 if ver_idx == 0 else 6
        custom_path = click.prompt("Pfad zur master.db")
        try:
            configure_db(version=ver, db_path=custom_path)
            _rb_session_selected = True
            click.echo(f"[Aktiviert] Rekordbox {ver} ({custom_path})")
        except Exception as exc:
            raise click.ClickException(f"Datenbank konnte nicht geöffnet werden: {exc}")


def _menu_cue_options(profile: dict, ask_tuning: bool = True) -> tuple[int, bool, bool, int, int]:
    """Ask user for Hot Cue count (4, 8, 12, 16), normal Loops, and Auto-Backup End Loop."""
    click.echo("\n--- HOT CUE & LOOP EINSTELLUNGEN ---")
    cue_choices = [
        "8 Hot Cues  (Standard: Pads A–H)",
        "4 Hot Cues  (Kompakt: Start, Bassline, Main Drop, Outro)",
        "12 Hot Cues (Erweitert: Pads A–L inkl. 2. Drop & 2. Breakdown)",
        "16 Hot Cues (Maximum: Pads A–P für Rekordbox 6/7 Bank I–P)",
    ]
    c_idx = _menu_choice("Wie viele Hot Cues sollen gesetzt werden?", cue_choices)
    max_hot_cues = [8, 4, 12, 16][c_idx]

    loop_idx = _menu_choice(
        "Sollen normale Loops erstellt werden?",
        [
            "Ja — mit Loops (z. B. für Bassline-Intro & Outro)",
            "Nein — keine Loops (nur normale Cue-Punkte)",
        ],
    )
    use_loops = loop_idx == 0

    auto_end_idx = _menu_choice(
        "Auto-Loop am Ende als Backup (Active Loop — greift automatisch am Trackende)?",
        [
            "Ja — Auto-Backup-Loop am Ende aktivieren (verhindert plötzliches Track-Ende)",
            "Nein — kein automatischer Backup-Loop am Ende",
        ],
    )
    auto_end_loop = auto_end_idx == 0

    def_loop = profile.get("default_loop_bars", 8)
    def_offset = profile.get("default_memory_offset_bars", 16)

    if ask_tuning:
        offset = click.prompt(f"Memory-Cue-Abstand in Takten ({profile['name']} Standard)", default=def_offset, type=int)
        loop_bars = (
            click.prompt(f"Loop-Länge in Takten ({profile['name']} Standard)", default=def_loop, type=int)
            if (use_loops or auto_end_loop)
            else def_loop
        )
    else:
        offset = def_offset
        loop_bars = def_loop

    return max_hot_cues, use_loops, auto_end_loop, offset, loop_bars


_EXISTING_POLICY_LABELS = {
    "skip": "Behalten (Skip)",
    "overwrite": "Überschreiben",
    "ask": "Nachfragen",
}


def _menu_existing_cues_policy() -> str:
    """Ask user whether existing Hot/Memory cues in Rekordbox may be overwritten."""
    idx = _menu_choice(
        "Dürfen vorhandene Hot Cues / Memory Cues überschrieben werden?",
        [
            "Nein — vorhandene Cues behalten (Tracks mit Cues überspringen)",
            "Ja — vorhandene Cues überschreiben (alte Cues ersetzen)",
            "Jedes Mal beim Anwenden nachfragen (Track-Liste prüfen & entscheiden)",
        ],
    )
    return ["skip", "overwrite", "ask"][idx]


def _print_walkthrough_header(subtitle: str | None = None, details: list[str] | None = None) -> None:
    """Clear the screen and render a clean walkthrough status header."""
    click.clear()
    click.echo("=" * 68)
    title = "djcues — Rekordbox Genre & Cue Walkthrough"
    if subtitle:
        title = f"{title} | {subtitle}"
    click.echo(f"  {title}")
    if details:
        click.echo("-" * 68)
        for line in details:
            click.echo(f"  {line}")
    click.echo("=" * 68)


def _run_walkthrough_flow() -> None:
    """Run the interactive walkthrough with a persistent, clean action loop."""
    import pathlib

    _print_walkthrough_header("Setup")

    # 0. Rekordbox Version (v6 / v7 / custom)
    _select_rekordbox_version()
    active_db = get_active_db_info()
    rb_line = f"Rekordbox {active_db.version_major} ({active_db.version_str})" if active_db else None

    # 1. Genre
    _print_walkthrough_header("Genre", [rb_line] if rb_line else None)
    genre_key, profile = _menu_genre()

    # 2. Hot Cue Count, Loops, Auto-End-Loop & Overwrite Policy
    _print_walkthrough_header(
        "Cues & Loops",
        [f"Genre: {profile['name']} ({profile['bpm_range']})"],
    )
    max_hot_cues, use_loops, auto_end_loop, offset, loop_bars = _menu_cue_options(profile, ask_tuning=False)

    loop_txt = f"{loop_bars} Takte" if use_loops else "Aus"
    auto_txt = f"Aktiv ({loop_bars} Takte)" if auto_end_loop else "Aus"
    _print_walkthrough_header(
        "Vorhandene Cues",
        [
            f"Genre: {profile['name']} | Hot Cues: {max_hot_cues} | Loops: {loop_txt} | Auto-End-Loop: {auto_txt}",
        ],
    )
    existing_policy = _menu_existing_cues_policy()

    # 3. Playlist & Tracks
    _print_walkthrough_header(
        "Playlist & Tracks",
        [
            f"Genre: {profile['name']} | Hot Cues: {max_hot_cues} | Loops: {loop_txt} | Auto-End-Loop: {auto_txt}",
            f"Vorhandene Cues: {_EXISTING_POLICY_LABELS[existing_policy]}",
        ],
    )
    playlist, track_name, all_tracks = _menu_scope()

    # 4. Persistent Action Loop (clears screen each turn so nothing piles up above)
    while True:
        loop_txt = f"{loop_bars} Takte" if use_loops else "Aus"
        auto_txt = f"Aktiv ({loop_bars} Takte)" if auto_end_loop else "Aus"
        scope_txt = "Alle Tracks" if all_tracks else (track_name or "Auswahl")
        status_lines = [
            f"Aktiv: {profile['name']} | Playlist: {playlist} ({scope_txt})",
            f"Cues: {max_hot_cues} | Loops: {loop_txt} | Auto-End-Loop: {auto_txt} | Vorhandene: {_EXISTING_POLICY_LABELS[existing_policy]}",
        ]
        _print_walkthrough_header("Aktionen", status_lines)

        actions = [
            "Im Webbrowser visualisieren        (Waveform, Phrasen & Cue-Pads)",
            "Cue-Vorschläge im Terminal         (Propose / Details)",
            "Review-Studio im Browser öffnen    (Cues prüfen & anpassen)",
            "Bestehende Cues vergleichen        (Compare Match-Rate)",
            "Review-Session anwenden            (in Rekordbox schreiben + Backup)",
            "Einstellungen ändern               (Genre / Cues / Loops / Überschreiben / Playlist)",
            "Zurück zum Hauptmenü",
        ]
        action_idx = _menu_choice("Aktion auswählen", actions)

        if action_idx == 6:
            return
        elif action_idx == 5:
            _print_walkthrough_header("Einstellungen ändern", status_lines)
            sub_idx = _menu_choice(
                "Was möchtest du ändern?",
                [
                    "Genre ändern",
                    "Hot Cue Anzahl / Loops / Auto-End-Loop / Takte ändern",
                    "Umgang mit vorhandenen Cues ändern (Überschreiben / Behalten / Nachfragen)",
                    "Playlist / Tracks ändern",
                    "Rekordbox Version (v6 / v7) wechseln",
                    "Abbrechen / Zurück",
                ],
            )
            if sub_idx == 0:
                _print_walkthrough_header("Genre ändern", status_lines)
                genre_key, profile = _menu_genre()
                offset = profile.get("default_memory_offset_bars", 16)
                loop_bars = profile.get("default_loop_bars", 8)
            elif sub_idx == 1:
                _print_walkthrough_header("Cues & Loops ändern", status_lines)
                max_hot_cues, use_loops, auto_end_loop, offset, loop_bars = _menu_cue_options(profile, ask_tuning=True)
            elif sub_idx == 2:
                _print_walkthrough_header("Vorhandene Cues ändern", status_lines)
                existing_policy = _menu_existing_cues_policy()
            elif sub_idx == 3:
                _print_walkthrough_header("Playlist & Tracks ändern", status_lines)
                playlist, track_name, all_tracks = _menu_scope()
            elif sub_idx == 4:
                _print_walkthrough_header("Rekordbox-Version wechseln", status_lines)
                _select_rekordbox_version(force_prompt=True)
            continue

        try:
            if action_idx == 0:
                viz.callback(playlist, track_name, all_tracks, False, offset, loop_bars, None, genre_key, max_hot_cues, use_loops, auto_end_loop)
            elif action_idx == 1:
                propose.callback(playlist, track_name, all_tracks, offset, loop_bars, genre_key, max_hot_cues, use_loops, auto_end_loop)
            elif action_idx == 2:
                review.callback(playlist, track_name, all_tracks, offset, loop_bars, None, genre_key, max_hot_cues, use_loops, auto_end_loop)
            elif action_idx == 3:
                compare.callback(playlist, track_name, all_tracks, offset, loop_bars, genre_key, max_hot_cues, use_loops, auto_end_loop)
            elif action_idx == 4:
                _print_walkthrough_header("Review-Session anwenden", status_lines)
                safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in playlist).strip().replace(" ", "-").lower()
                default_session = pathlib.Path(f"{safe_name}-session.json")
                if default_session.exists():
                    session_file = click.prompt("Pfad zur Session-Datei", default=str(default_session), type=click.Path(exists=True, dir_okay=False))
                else:
                    session_file = click.prompt("Pfad zur Session-Datei", type=click.Path(exists=True, dir_okay=False))
                dry_run = click.confirm("Nur testen (Dry Run)?", default=True)
                apply_policy = existing_policy
                if not dry_run:
                    click.echo(f"Aktuelle Einstellung für vorhandene Cues: {_EXISTING_POLICY_LABELS[apply_policy]}")
                    if not click.confirm("Diese Einstellung verwenden?", default=True):
                        apply_policy = _menu_existing_cues_policy()
                apply.callback(session_file, dry_run, False, None, apply_policy)
        except click.Abort:
            click.echo("\nVorgang abgebrochen.")
        except (click.ClickException, SystemExit) as exc:
            if isinstance(exc, click.ClickException):
                click.echo(f"Fehler: {exc}", err=True)
            else:
                click.echo("Der Vorgang konnte nicht abgeschlossen werden.", err=True)

        click.echo()
        click.pause("Enter drücken, um weitere Aktionen zu wählen")


def _run_menu() -> None:
    """Run the beginner-friendly interactive walkthrough menu."""
    while True:
        click.clear()
        click.echo("djcues — Rekordbox Cue Assistant")
        click.echo("=" * 38)
        active = get_active_db_info()
        if active:
            click.echo(f"Aktiv: Rekordbox {active.version_major} ({active.version_str}) | {active.db_path}")
            click.echo("-" * 38)
        click.echo("1) Walkthrough starten             (Rekordbox -> Genre -> Playlist -> Aktion)")
        click.echo("2) Cue-Vorschläge anzeigen         (Propose)")
        click.echo("3) Visualisierung im Browser       (Viz)")
        click.echo("4) Cues im Browser prüfen/anpassen (Review Studio)")
        click.echo("5) Review-Session anwenden / DB-Backup erstellen")
        click.echo("6) Beenden")
        click.echo("7) Rekordbox-Version wechseln      (v6 / v7 / eigener Pfad)")
        click.echo()

        try:
            choice = click.prompt("Auswahl", type=click.Choice(["1", "2", "3", "4", "5", "6", "7"]))
            if choice == "6":
                click.echo("Auf Wiedersehen.")
                return

            if choice == "7":
                click.clear()
                _select_rekordbox_version(force_prompt=True)
            elif choice == "1":
                _run_walkthrough_flow()
                continue
            elif choice == "5":
                click.clear()
                _select_rekordbox_version()
                sub = _menu_choice(
                    "Datenbank-Aktion",
                    [
                        "Review-Session anwenden (fragt vorher nach Backup in Dokumente)",
                        "Sofortiges Rekordbox Datenbank-Backup in Dokumente erstellen",
                    ],
                )
                if sub == 1:
                    backup.callback()
                else:
                    session_file = click.prompt("Pfad zur Session-Datei", type=click.Path(exists=True, dir_okay=False))
                    dry_run = click.confirm("Nur testen (Dry Run)?", default=True)
                    apply_policy = "ask" if dry_run else _menu_existing_cues_policy()
                    apply.callback(session_file, dry_run, False, None, apply_policy)
            else:
                click.clear()
                _select_rekordbox_version()
                # --- SCHRITT 1: Genre auswählen ---
                genre_key, profile = _menu_genre()

                # --- SCHRITT 2: Hot Cues, Loops & Auto-End-Loop ---
                click.clear()
                click.echo(f"[Aktiviert] Genre: {profile['name']} ({profile['bpm_range']})")
                max_hot_cues, use_loops, auto_end_loop, offset, loop_bars = _menu_cue_options(profile, ask_tuning=True)

                # --- SCHRITT 3: Playlist & Tracks ---
                click.clear()
                click.echo(f"[Aktiviert] Genre: {profile['name']} | Hot Cues: {max_hot_cues}")
                click.echo("\n--- PLAYLIST & TRACKS AUSWÄHLEN ---")
                playlist, track_name, all_tracks = _menu_scope()

                click.clear()

                if choice == "2":
                    propose.callback(playlist, track_name, all_tracks, offset, loop_bars, genre_key, max_hot_cues, use_loops, auto_end_loop)
                elif choice == "3":
                    compare_mode = click.confirm("Bestehende und vorgeschlagene Cues vergleichen?", default=False)
                    output = click.prompt("Ausgabedatei (leer = automatisch)", default="", show_default=False) or None
                    viz.callback(playlist, track_name, all_tracks, compare_mode, offset, loop_bars, output, genre_key, max_hot_cues, use_loops, auto_end_loop)
                elif choice == "4":
                    output = click.prompt("Ausgabeordner (leer = aktueller Ordner)", default="", show_default=False) or None
                    review.callback(playlist, track_name, all_tracks, offset, loop_bars, output, genre_key, max_hot_cues, use_loops, auto_end_loop)

            click.echo()
            click.pause("Enter drücken, um zum Menü zurückzukehren")
        except (click.Abort, KeyboardInterrupt):
            click.echo("\nMenü beendet.")
            return
        except (click.ClickException, SystemExit) as exc:
            if isinstance(exc, click.ClickException):
                click.echo(f"Fehler: {exc}", err=True)
            else:
                click.echo("Der Vorgang konnte nicht abgeschlossen werden.", err=True)
            click.pause("Enter drücken, um zum Menü zurückzukehren")


@click.group(invoke_without_command=True)
@click.option("--rb-version", type=click.Choice(["6", "7", "auto"]), default="auto", help="Rekordbox version to use (6, 7, or auto).")
@click.option("--db-path", default=None, help="Optional custom path to master.db.")
@click.pass_context
def cli(ctx, rb_version="auto", db_path=None):
    """djcues — automated rekordbox cue placement based on phrase analysis."""
    global _rb_session_selected
    if db_path is not None or rb_version != "auto":
        ver = int(rb_version) if rb_version in ("6", "7") else None
        configure_db(version=ver, db_path=db_path)
        _rb_session_selected = True
    if ctx.invoked_subcommand is None:
        _run_menu()


@cli.command("menu")
def menu():
    """Open the interactive terminal menu."""
    _run_menu()


@cli.command()
@click.argument("playlist_name")
@click.argument("track_name", required=False)
@click.option("--all", "all_tracks", is_flag=True, help="Process all tracks in the playlist.")
@click.option("--offset", default=16, show_default=True, help="Memory cue offset in bars.")
@click.option("--loop-bars", default=4, show_default=True, help="Loop length in bars.")
@click.option("--genre", "-g", default="auto", show_default=True, help="Genre profile (industrial, hard_techno, schranz, hypnotic_groove, hard_groove, bounce, trance, general)")
@click.option("--hot-cues", "-c", default=8, show_default=True, type=int, help="Number of hot cues (4, 8, 12, or 16).")
@click.option("--loops/--no-loops", default=True, show_default=True, help="Enable or disable loop cues.")
@click.option("--auto-end-loop/--no-auto-end-loop", default=False, show_default=True, help="Add an Active Auto-Backup Loop at track end.")
def propose(playlist_name, track_name, all_tracks, offset, loop_bars, genre="auto", hot_cues=8, loops=True, auto_end_loop=False):
    """Propose cue placements for tracks in a playlist."""
    playlist = find_playlist(playlist_name)
    if playlist is None:
        click.echo(f"Error: playlist '{playlist_name}' not found.", err=True)
        raise SystemExit(1)

    tracks = _get_tracks_for_scope(playlist, track_name, all_tracks)
    strategy = CueStrategy(
        genre=genre,
        memory_offset_bars=offset,
        loop_length_bars=loop_bars,
        max_hot_cues=hot_cues,
        use_loops=loops,
        auto_end_loop=auto_end_loop,
    )

    for t in tracks:
        proposal = strategy.propose(t)
        _print_proposal(proposal, t)


@cli.command()
@click.argument("playlist_name")
@click.argument("track_name", required=False)
@click.option("--all", "all_tracks", is_flag=True, help="Compare all tracks in the playlist.")
@click.option("--offset", default=16, show_default=True, help="Memory cue offset in bars.")
@click.option("--loop-bars", default=4, show_default=True, help="Loop length in bars.")
@click.option("--genre", "-g", default="auto", show_default=True, help="Genre profile (industrial, hard_techno, schranz, hypnotic_groove, hard_groove, bounce, trance, general)")
@click.option("--hot-cues", "-c", default=8, show_default=True, type=int, help="Number of hot cues (4, 8, 12, or 16).")
@click.option("--loops/--no-loops", default=True, show_default=True, help="Enable or disable loop cues.")
@click.option("--auto-end-loop/--no-auto-end-loop", default=False, show_default=True, help="Add an Active Auto-Backup Loop at track end.")
def compare(playlist_name, track_name, all_tracks, offset, loop_bars, genre="auto", hot_cues=8, loops=True, auto_end_loop=False):
    """Compare existing cues with proposed placements."""
    playlist = find_playlist(playlist_name)
    if playlist is None:
        click.echo(f"Error: playlist '{playlist_name}' not found.", err=True)
        raise SystemExit(1)

    tracks = _get_tracks_for_scope(playlist, track_name, all_tracks)
    strategy = CueStrategy(
        genre=genre,
        memory_offset_bars=offset,
        loop_length_bars=loop_bars,
        max_hot_cues=hot_cues,
        use_loops=loops,
        auto_end_loop=auto_end_loop,
    )

    total_matches = 0
    total_cues = 0

    for t in tracks:
        proposal = strategy.propose(t)
        m, c = _print_comparison(proposal, t)
        total_matches += m
        total_cues += c
    if total_cues > 0:
        pct = total_matches / total_cues * 100
        click.echo(f"\n{'=' * 60}")
        click.echo(f"  Overall accuracy: {total_matches}/{total_cues} ({pct:.0f}%)")
        click.echo(f"{'=' * 60}")


@cli.command()
@click.argument("playlist")
@click.argument("track_name", required=False)
@click.option("--all", "all_tracks", is_flag=True, help="Visualize all tracks in playlist")
@click.option("--compare", "compare_mode", is_flag=True, help="Show existing vs proposed")
@click.option("--offset", default=16, help="Memory cue offset in bars (default: 16)")
@click.option("--loop-bars", default=4, help="Loop length in bars (default: 4)")
@click.option("--output", "-o", default=None, help="Output file path (default: auto-generated)")
@click.option("--genre", "-g", default="auto", show_default=True, help="Genre profile (industrial, hard_techno, schranz, hypnotic_groove, hard_groove, bounce, trance, general)")
@click.option("--hot-cues", "-c", default=8, show_default=True, type=int, help="Number of hot cues (4, 8, 12, or 16).")
@click.option("--loops/--no-loops", default=True, show_default=True, help="Enable or disable loop cues.")
@click.option("--auto-end-loop/--no-auto-end-loop", default=False, show_default=True, help="Add an Active Auto-Backup Loop at track end.")
def viz(playlist, track_name, all_tracks, compare_mode, offset, loop_bars, output, genre="auto", hot_cues=8, loops=True, auto_end_loop=False):
    """Generate an HTML timeline visualization."""
    import pathlib
    import webbrowser
    from djcues.viz import render_timeline, render_playlist

    pl = find_playlist(playlist)
    if pl is None:
        click.echo(f"Playlist '{playlist}' not found.", err=True)
        raise SystemExit(1)

    tracks = _get_tracks_for_scope(pl, track_name, all_tracks)
    strategy = CueStrategy(
        genre=genre,
        memory_offset_bars=offset,
        loop_length_bars=loop_bars,
        max_hot_cues=hot_cues,
        use_loops=loops,
        auto_end_loop=auto_end_loop,
    )

    if all_tracks:
        pairs = [(t, strategy.propose(t)) for t in tracks]
        click.echo(f"Rendering {len(pairs)} tracks...")
        page_html = render_playlist(playlist, pairs, compare=compare_mode)
        if output:
            out_path = pathlib.Path(output)
        else:
            safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in playlist).strip().replace(" ", "-").lower()
            out_path = pathlib.Path(f"{safe_name}-cues.html")
    else:
        track = tracks[0]
        proposal = strategy.propose(track)
        page_html = render_timeline(track, proposal, compare=compare_mode)
        if output:
            out_path = pathlib.Path(output)
        else:
            safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in track.title).strip().replace(" ", "-").lower()
            out_path = pathlib.Path(f"{safe_name}-cues.html")

    out_path.write_text(page_html, encoding="utf-8")
    click.echo(f"Written to {out_path}")
    webbrowser.open(f"file://{out_path.resolve()}")


@cli.command()
@click.argument("playlist")
@click.argument("track_name", required=False)
@click.option("--all", "all_tracks", is_flag=True, help="Review all tracks in playlist")
@click.option("--offset", default=16, help="Memory cue offset in bars (default: 16)")
@click.option("--loop-bars", default=4, help="Loop length in bars (default: 4)")
@click.option("--output", "-o", default=None, help="Output directory (default: current dir)")
@click.option("--genre", "-g", default="auto", show_default=True, help="Genre profile (industrial, hard_techno, schranz, hypnotic_groove, hard_groove, bounce, trance, general)")
@click.option("--hot-cues", "-c", default=8, show_default=True, type=int, help="Number of hot cues (4, 8, 12, or 16).")
@click.option("--loops/--no-loops", default=True, show_default=True, help="Enable or disable loop cues.")
@click.option("--auto-end-loop/--no-auto-end-loop", default=False, show_default=True, help="Add an Active Auto-Backup Loop at track end.")
def review(playlist, track_name, all_tracks, offset, loop_bars, output, genre="auto", hot_cues=8, loops=True, auto_end_loop=False):
    """Launch interactive review session in browser."""
    import pathlib
    import time
    import webbrowser
    from djcues.review import create_session, format_apply_command, render_review_html
    from djcues.server import start_server

    pl = find_playlist(playlist)
    if pl is None:
        click.echo(f"Playlist '{playlist}' not found.", err=True)
        raise SystemExit(1)

    selected = _get_tracks_for_scope(pl, track_name, all_tracks)
    strategy = CueStrategy(
        genre=genre,
        memory_offset_bars=offset,
        loop_length_bars=loop_bars,
        max_hot_cues=hot_cues,
        use_loops=loops,
        auto_end_loop=auto_end_loop,
    )
    pairs = [(t, strategy.propose(t)) for t in selected]

    if not pairs:
        click.echo("No tracks found to review.", err=True)
        raise SystemExit(1)

    # Generate session
    session = create_session(
        playlist_name=playlist,
        playlist_id=pl.ID,
        tracks_and_proposals=pairs,
        memory_offset_bars=offset,
        loop_length_bars=loop_bars,
    )

    # Determine output directory and safe name
    safe_name = "".join(
        c if c.isalnum() or c in " -_" else "" for c in playlist
    ).strip().replace(" ", "-").lower()

    if output:
        out_dir = pathlib.Path(output)
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = pathlib.Path(".")

    session_path = out_dir / f"{safe_name}-session.json"
    session_path.write_text(
        json.dumps(session, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Start local server
    html_path = out_dir / f"{safe_name}-review.html"
    server, port = start_server(
        html_path=html_path,
        session_path=session_path,
    )
    server_url = f"http://127.0.0.1:{port}"

    # Generate review HTML with server URL embedded
    review_html = render_review_html(
        playlist_name=playlist,
        tracks_and_proposals=pairs,
        session_path=str(session_path),
        server_url=server_url,
    )
    html_path.write_text(review_html, encoding="utf-8")

    # Open browser
    webbrowser.open(server_url)

    # Print info
    click.echo(f"Session: {session_path}")
    click.echo(f"Server:  {server_url}")
    click.echo(f"Apply:   {format_apply_command(str(session_path))}")
    click.echo("Tipp:    Im Browser prüfen -> danach hier Strg+C drücken & im Menü Option 5 wählen!")

    # Block until interrupted
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\nServer stopped.")


@cli.command()
def backup():
    """Backup the rekordbox database to Documents/rekordbox databse backup/<date_time>."""
    from djcues.writer import backup_database_to_documents

    db = get_db()
    db_path = db.db_directory / "master.db"
    dest = backup_database_to_documents(db_path)
    click.echo(f"Backup erfolgreich erstellt unter:\n  {dest.parent}")


@cli.command()
@click.argument("session_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Show what would be written without making changes")
@click.option("--force", is_flag=True, help="Skip overwrite confirmation (alias for --existing overwrite)")
@click.option("--backup/--no-backup", "do_backup", default=None, help="Backup DB to Documents before writing (asks by default)")
@click.option(
    "--existing",
    "existing_cues",
    type=click.Choice(["ask", "overwrite", "skip"], case_sensitive=False),
    default="ask",
    show_default=True,
    help="How to handle tracks that already have cues in Rekordbox (ask, overwrite, or skip).",
)
def apply(session_file, dry_run, force, do_backup=None, existing_cues="ask"):
    """Apply a review session to the rekordbox database."""
    import pathlib
    from djcues.writer import apply_session

    apply_session(
        session_path=pathlib.Path(session_file),
        dry_run=dry_run,
        force=force,
        backup=do_backup,
        existing_cues=existing_cues.lower(),
    )


if __name__ == "__main__":
    cli()
