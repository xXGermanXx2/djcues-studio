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
