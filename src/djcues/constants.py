"""Lookup tables for PSSI phrase mapping and cue system definition."""

from __future__ import annotations

from djcues.models import CueSlot

# PSSI mood → kind → label
# Reference: https://djl-analysis.deepsymmetry.org/djl-analysis/anlz.html#song-structure-tag
MOOD_PHRASE_MAP: dict[int, dict[int, str]] = {
    1: {  # High
        1: "Intro",
        2: "Up",
        3: "Down",
        5: "Chorus",
        6: "Outro",
    },
    2: {  # Mid
        1: "Intro",
        2: "Verse1",
        3: "Verse2",
        4: "Verse3",
        5: "Verse4",
        6: "Verse5",
        7: "Verse6",
        8: "Bridge",
        9: "Chorus",
        10: "Outro",
    },
    3: {  # Low
        1: "Intro",
        2: "Verse1",
        3: "Verse1",
        4: "Verse1",
        5: "Verse2",
        6: "Verse2",
        7: "Verse2",
        8: "Bridge",
        9: "Chorus",
        10: "Outro",
    },
}

MOOD_NAMES: dict[int, str] = {1: "High", 2: "Mid", 3: "Low"}


def resolve_phrase_label(mood: int, kind: int) -> str:
    """Resolve a PSSI phrase kind to a human-readable label given the mood."""
    return MOOD_PHRASE_MAP.get(mood, {}).get(kind, "Unknown")


# Cue system definition — matches cue-system.csv and verified DB values.
# Hot cue colors use ColorTableIndex. Memory cue colors use Color field.
CUE_SYSTEM: list[CueSlot] = [
    CueSlot(
        pad="A", kind=1,
        hot_cue_label="First Beat", memory_cue_label="First Beat",
        hot_cue_color_table_index=18, hot_cue_color=-1,
        memory_cue_color_table_index=None, memory_cue_color=4,
        is_loop=False, memory_offset_bars=0,
    ),
    CueSlot(
        pad="B", kind=2,
        hot_cue_label="Bassline Introduction", memory_cue_label="Bassline Introduction",
        hot_cue_color_table_index=18, hot_cue_color=255,
        memory_cue_color_table_index=0, memory_cue_color=4,
        is_loop=True, memory_offset_bars=0,
    ),
    CueSlot(
        pad="C", kind=3,
        hot_cue_label="First Breakdown", memory_cue_label="First Breakdown",
        hot_cue_color_table_index=1, hot_cue_color=-1,
        memory_cue_color_table_index=None, memory_cue_color=3,
        is_loop=False, memory_offset_bars=16,
    ),
    CueSlot(
        pad="D", kind=5,
        hot_cue_label="8 Beats Before Main Drop", memory_cue_label="8 Beats Before Main Drop",
        hot_cue_color_table_index=0, hot_cue_color=255,
        memory_cue_color_table_index=None, memory_cue_color=1,
        is_loop=False, memory_offset_bars=16,
    ),
    CueSlot(
        pad="E", kind=6,
        hot_cue_label="Main Breakdown", memory_cue_label="Main Breakdown",
        hot_cue_color_table_index=1, hot_cue_color=-1,
        memory_cue_color_table_index=None, memory_cue_color=6,
        is_loop=False, memory_offset_bars=16,
    ),
    CueSlot(
        pad="F", kind=7,
        hot_cue_label="32 Beats Before Main Drop", memory_cue_label="32 Beats Before Main Drop",
        hot_cue_color_table_index=0, hot_cue_color=255,
        memory_cue_color_table_index=None, memory_cue_color=7,
        is_loop=False, memory_offset_bars=16,
    ),
    CueSlot(
        pad="G", kind=8,
        hot_cue_label="Main Drop", memory_cue_label="Main Drop",
        hot_cue_color_table_index=42, hot_cue_color=-1,
        memory_cue_color_table_index=None, memory_cue_color=5,
        is_loop=False, memory_offset_bars=16,
    ),
    CueSlot(
        pad="H", kind=9,
        hot_cue_label="Final Drop / Outro", memory_cue_label="Final Drop / Outro",
        hot_cue_color_table_index=1, hot_cue_color=-1,
        memory_cue_color_table_index=0, memory_cue_color=2,
        is_loop=True, memory_offset_bars=0,
    ),
]

# Extended Hot Cue slots (Bank I–P, Kinds 10–17) for 12/16-Hot-Cue mode in Rekordbox 6/7
EXTENDED_CUE_SLOTS: list[CueSlot] = [
    CueSlot(
        pad="I", kind=10,
        hot_cue_label="16 Bars Before Main Drop", memory_cue_label="16 Bars Before Main Drop",
        hot_cue_color_table_index=0, hot_cue_color=255,
        memory_cue_color_table_index=None, memory_cue_color=7,
        is_loop=False, memory_offset_bars=16,
    ),
    CueSlot(
        pad="J", kind=11,
        hot_cue_label="Second Drop / Peak 2", memory_cue_label="Second Drop / Peak 2",
        hot_cue_color_table_index=42, hot_cue_color=-1,
        memory_cue_color_table_index=None, memory_cue_color=5,
        is_loop=False, memory_offset_bars=16,
    ),
    CueSlot(
        pad="K", kind=12,
        hot_cue_label="16 Beats Before Drop 2", memory_cue_label="16 Beats Before Drop 2",
        hot_cue_color_table_index=0, hot_cue_color=255,
        memory_cue_color_table_index=None, memory_cue_color=1,
        is_loop=False, memory_offset_bars=16,
    ),
    CueSlot(
        pad="L", kind=13,
        hot_cue_label="Second Breakdown", memory_cue_label="Second Breakdown",
        hot_cue_color_table_index=1, hot_cue_color=-1,
        memory_cue_color_table_index=None, memory_cue_color=6,
        is_loop=False, memory_offset_bars=16,
    ),
    CueSlot(
        pad="M", kind=14,
        hot_cue_label="Vocal Hook / Mid Shift", memory_cue_label="Vocal Hook / Mid Shift",
        hot_cue_color_table_index=56, hot_cue_color=-1,
        memory_cue_color_table_index=None, memory_cue_color=3,
        is_loop=False, memory_offset_bars=16,
    ),
    CueSlot(
        pad="N", kind=15,
        hot_cue_label="Final Buildup", memory_cue_label="Final Buildup",
        hot_cue_color_table_index=0, hot_cue_color=255,
        memory_cue_color_table_index=None, memory_cue_color=1,
        is_loop=False, memory_offset_bars=16,
    ),
    CueSlot(
        pad="O", kind=16,
        hot_cue_label="Mix-Out Trigger (16 Bars Left)", memory_cue_label="Mix-Out Trigger (16 Bars Left)",
        hot_cue_color_table_index=1, hot_cue_color=-1,
        memory_cue_color_table_index=None, memory_cue_color=2,
        is_loop=False, memory_offset_bars=0,
    ),
    CueSlot(
        pad="P", kind=17,
        hot_cue_label="Safety Outro Loop", memory_cue_label="Safety Outro Loop",
        hot_cue_color_table_index=18, hot_cue_color=-1,
        memory_cue_color_table_index=0, memory_cue_color=4,
        is_loop=True, memory_offset_bars=0,
    ),
]

ALL_CUE_SLOTS: list[CueSlot] = CUE_SYSTEM + EXTENDED_CUE_SLOTS

# Quick lookups (covers all 16 pads A–P; CUE_SYSTEM stays 8 slots A–H for compatibility)
KIND_TO_PAD: dict[int, str] = {s.kind: s.pad for s in ALL_CUE_SLOTS}
PAD_TO_KIND: dict[str, int] = {s.pad: s.kind for s in ALL_CUE_SLOTS}
CUE_SYSTEM_BY_PAD: dict[str, CueSlot] = {s.pad: s for s in ALL_CUE_SLOTS}

# ---------------------------------------------------------------------------
# Genre Profiles — personalized cue strategies, phrasing & loop lengths
# ---------------------------------------------------------------------------
GENRE_PROFILES: dict[str, dict] = {
    "industrial": {
        "key": "industrial",
        "name": "Industrial Techno",
        "bpm_range": "145–165 BPM",
        "description": "Verzerrte Kicks, dunkle Sub-Rumbles, harte metallische Texturen",
        "default_loop_bars": 8,
        "default_memory_offset_bars": 16,
        "pre_drop_d_beats": 8,
        "pre_drop_f_beats": 32,
        "labels": {
            "A": "First Beat",
            "B": "Kick / Rumble Entry",
            "C": "First Breakdown / Tension",
            "D": "8 Beats Before Climax",
            "E": "Industrial Breakdown",
            "F": "32 Beats Before Climax",
            "G": "Main Industrial Drop",
            "H": "Outro Rumble Loop",
        },
    },
    "hard_techno": {
        "key": "hard_techno",
        "name": "Hard Techno",
        "bpm_range": "148–165 BPM",
        "description": "Unerbittlicher Drive, schnelle harte Percussion & wuchtige Drops",
        "default_loop_bars": 8,
        "default_memory_offset_bars": 16,
        "pre_drop_d_beats": 8,
        "pre_drop_f_beats": 32,
        "labels": {
            "A": "First Beat",
            "B": "Hard Kick Entry",
            "C": "First Tension Build",
            "D": "8 Beats Before Drop",
            "E": "Peak Breakdown",
            "F": "32 Beats Before Drop",
            "G": "Hard Techno Climax",
            "H": "Outro Hard Loop",
        },
    },
    "schranz": {
        "key": "schranz",
        "name": "Schranz / Emotional Schranz",
        "bpm_range": "150–175 BPM",
        "description": "Treibende verzerrte Schranz-Loops, emotionale Vocal-Breaks & kompromisslose Drops",
        "default_loop_bars": 8,
        "default_memory_offset_bars": 16,
        "pre_drop_d_beats": 8,
        "pre_drop_f_beats": 32,
        "labels": {
            "A": "First Beat",
            "B": "Schranz Kick / Loop Entry",
            "C": "First Break / Tension",
            "D": "8 Beats Before Drop",
            "E": "Emotional / Vocal Breakdown",
            "F": "32 Beats Before Drop",
            "G": "Main Schranz Drop",
            "H": "Outro Schranz Loop",
        },
    },
    "hypnotic_groove": {
        "key": "hypnotic_groove",
        "name": "Hypnotic Groove",
        "bpm_range": "136–144 BPM",
        "description": "Tiefe polyrhythmische Synth-Loops, rollender Bass, 16-Takt-Schleifen für lange Blends",
        "default_loop_bars": 16,
        "default_memory_offset_bars": 32,
        "pre_drop_d_beats": 16,
        "pre_drop_f_beats": 32,
        "labels": {
            "A": "First Beat",
            "B": "Rolling Groove Entry",
            "C": "Percussion Layer / Filter",
            "D": "16 Beats Before Energy Lift",
            "E": "Deep Ambient Breakdown",
            "F": "32 Beats Before Climax",
            "G": "Peak Hypnotic Groove",
            "H": "Outro Seamless Loop",
        },
    },
    "hard_groove": {
        "key": "hard_groove",
        "name": "Hard Groove",
        "bpm_range": "140–150 BPM",
        "description": "Tribal 909 Funk, federnde Percussion-Rolls & syncopierte Grooves",
        "default_loop_bars": 8,
        "default_memory_offset_bars": 16,
        "pre_drop_d_beats": 16,
        "pre_drop_f_beats": 32,
        "labels": {
            "A": "First Beat",
            "B": "Tribal Groove & Sub",
            "C": "Vocal Chop / Fill Break",
            "D": "16 Beats Before Roll",
            "E": "Mid-Track Breakdown",
            "F": "32 Beats Before Drop",
            "G": "Peak Rolling Groove",
            "H": "Outro Percussion Loop",
        },
    },
    "bounce": {
        "key": "bounce",
        "name": "Bounce / Hard Bounce",
        "bpm_range": "142–155 BPM",
        "description": "Offbeat-Basslines, gummige Kicks, Vocals & zackige Pre-Drop Waypoints",
        "default_loop_bars": 8,
        "default_memory_offset_bars": 16,
        "pre_drop_d_beats": 8,
        "pre_drop_f_beats": 16,
        "labels": {
            "A": "First Beat",
            "B": "Offbeat Bass Entry",
            "C": "Vocal Breakdown",
            "D": "8 Beats Before Bounce",
            "E": "Main Vocal Build",
            "F": "16 Beats Pre-Drop Fill",
            "G": "Main Bouncy Drop",
            "H": "Outro Bounce Loop",
        },
    },
    "trance": {
        "key": "trance",
        "name": "Trance / Hard Trance",
        "bpm_range": "138–148 BPM",
        "description": "Euphorische Supersaw-Leads, monumentale Breakdowns & 32-Takt-Phrasierung",
        "default_loop_bars": 16,
        "default_memory_offset_bars": 32,
        "pre_drop_d_beats": 16,
        "pre_drop_f_beats": 32,
        "labels": {
            "A": "First Beat",
            "B": "Rolling Bassline Entry",
            "C": "Melodic Theme Intro",
            "D": "16 Beats Before Anthemic Drop",
            "E": "Euphoric Breakdown",
            "F": "32 Beats Supersaw Riser",
            "G": "Euphoric Climax / Drop",
            "H": "Melodic Outro Loop",
        },
    },
    "general": {
        "key": "general",
        "name": "Standard / All-Round",
        "bpm_range": "120–135 BPM",
        "description": "Standard 8 Hot Cue System für House, EDM, Pop und allgemeines Mixing",
        "default_loop_bars": 4,
        "default_memory_offset_bars": 16,
        "pre_drop_d_beats": 8,
        "pre_drop_f_beats": 32,
        "labels": {
            "A": "First Beat",
            "B": "Bassline Introduction",
            "C": "First Breakdown",
            "D": "8 Beats Before Main Drop",
            "E": "Main Breakdown",
            "F": "32 Beats Before Main Drop",
            "G": "Main Drop",
            "H": "Final Drop / Outro",
        },
    },
}


def get_genre_profile(name_or_key: str | None) -> dict:
    """Normalize input and return the matching genre profile."""
    if not name_or_key or name_or_key.lower() in ("auto", "none"):
        return GENRE_PROFILES["industrial"]
    clean = name_or_key.lower().replace("-", "_").replace(" ", "_")
    for key, profile in GENRE_PROFILES.items():
        if clean in (key, profile["name"].lower().replace("-", "_").replace(" ", "_")):
            return profile
        if key in clean:
            return profile
    return GENRE_PROFILES["general"]
