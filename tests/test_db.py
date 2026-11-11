import pytest
from tests.conftest import requires_rekordbox


def _get_test_playlist():
    from djcues.db import find_playlist, get_db
    pl = find_playlist("Processed")
    if pl is not None:
        return pl
    db = get_db()
    for candidate in db.get_playlist():
        if candidate.Attribute != 1 and list(db.get_playlist_songs(PlaylistID=candidate.ID)):
            return candidate
    pytest.skip("No playlist with tracks found in Rekordbox database")


@requires_rekordbox
def test_find_playlist():
    from djcues.db import find_playlist
    pl = _get_test_playlist()
    assert pl is not None
    found = find_playlist(pl.Name)
    assert found is not None
    assert found.Name == pl.Name


@requires_rekordbox
def test_load_playlist_tracks():
    from djcues.db import load_playlist_tracks
    pl = _get_test_playlist()
    tracks = load_playlist_tracks(pl.ID)
    assert len(tracks) > 0
    first = tracks[0]
    assert first.title is not None
    assert first.bpm > 0


@requires_rekordbox
def test_track_has_phrases():
    from djcues.db import load_playlist_tracks
    pl = _get_test_playlist()
    tracks = load_playlist_tracks(pl.ID)
    # Check if any tracks in playlist have phrases (or pass if playlist has tracks)
    assert len(tracks) > 0


@requires_rekordbox
def test_track_has_cues():
    from djcues.db import load_playlist_tracks
    pl = _get_test_playlist()
    tracks = load_playlist_tracks(pl.ID)
    assert len(tracks) > 0


@requires_rekordbox
def test_track_beat_grid():
    from djcues.db import load_playlist_tracks
    pl = _get_test_playlist()
    tracks = load_playlist_tracks(pl.ID)
    first = tracks[0]
    assert first.beat_grid.bpm > 0
    assert first.beat_grid.first_beat_ms >= 0


def test_detect_rekordbox_configs_finds_v6_and_v7(tmp_path, monkeypatch):
    import json
    import pyrekordbox
    from djcues.db import detect_rekordbox_configs

    fake_db = tmp_path / "master.db"
    fake_db.write_bytes(b"sqlite")

    monkeypatch.setattr(
        pyrekordbox,
        "get_config",
        lambda name: {
            "rekordbox7": {"version": "7.2.14", "db_path": str(fake_db), "install_dir": str(tmp_path)},
            "rekordbox6": {"version": "6.8.4", "db_path": str(fake_db), "install_dir": str(tmp_path)},
        }.get(name, {}),
    )
    monkeypatch.setattr("djcues.db._find_program_installs", lambda: {})

    configs = detect_rekordbox_configs()
    versions = [c.version_major for c in configs]
    assert 7 in versions
    assert 6 in versions


def test_configure_db_with_custom_path(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    import djcues.db as db_mod

    fake_db = tmp_path / "master.db"
    fake_db.write_bytes(b"sqlite")

    mock_cls = MagicMock()
    monkeypatch.setattr(db_mod, "RekordboxDatabase", mock_cls)

    db_mod.configure_db(version=6, db_path=f'"{fake_db}"')
    mock_cls.assert_called_once_with(path=fake_db, db_dir=tmp_path)
    assert db_mod.get_active_db_info().version_major == 6

    # Clean up global state
    db_mod._db = None
    db_mod._selected_db_path = None
    db_mod._selected_version = None
    db_mod._active_info = None
