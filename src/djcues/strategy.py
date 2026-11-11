"""Cue placement strategy engine — maps PSSI phrases to cue points."""

from __future__ import annotations

from djcues.constants import ALL_CUE_SLOTS, CUE_SYSTEM, CUE_SYSTEM_BY_PAD, get_genre_profile
from djcues.models import BeatGrid, CuePoint, CueProposal, Phrase, Track


def _phrase_bass_energy(track: Track, phrase: Phrase) -> float | None:
    """Return average bass (red) energy (0.0-7.0) across a phrase from waveform data."""
    if not track.waveform or track.duration_ms <= 0:
        return None
    n = len(track.waveform)
    i0 = max(0, min(n - 1, int(n * phrase.position_ms / track.duration_ms)))
    i1 = max(i0 + 1, min(n, int(n * (phrase.position_ms + phrase.duration_ms) / track.duration_ms)))
    pts = track.waveform[i0:i1]
    return sum(pt.red for pt in pts) / len(pts) if pts else None


def _spectral_similarity(wf_points: list, i0: int, i_mid: int, i1: int) -> float:
    """Compare the RGB (bass/mid/treble) profile of two halves of a waveform section.

    Returns a similarity score from 0.0 (completely different) to 1.0 (identical).
    Uses mean-squared-error of the per-point RGB values, normalized.
    """
    half_len = min(i_mid - i0, i1 - i_mid)
    if half_len < 2:
        return 0.0

    first_half = wf_points[i0 : i0 + half_len]
    second_half = wf_points[i_mid : i_mid + half_len]

    total_mse = 0.0
    for a, b in zip(first_half, second_half):
        # RGB values are 0-7, normalize to 0-1
        dr = (a.red - b.red) / 7
        dg = (a.green - b.green) / 7
        db = (a.blue - b.blue) / 7
        dh = a.height - b.height  # already 0-1
        total_mse += dr * dr + dg * dg + db * db + dh * dh

    # Max possible MSE per point = 4 (all channels off by 1.0)
    mse = total_mse / half_len / 4
    return max(0.0, 1.0 - mse)


def _find_stable_loop(
    track: Track,
    search_start_ms: float,
    search_end_ms: float,
    bar_sizes: tuple[int, ...] = (8, 4, 2, 1),
    min_energy: float = 0.05,
    min_similarity: float = 0.7,
) -> tuple[float, int, float] | None:
    """Find a stable, loopable region using waveform energy and spectral similarity.

    Scans bar-aligned windows from search_start_ms forward. Tries 8 bars first,
    then falls back to 4, 2, 1. A good loop has non-trivial energy AND the
    second half spectrally matches the first half (so the loop repeats cleanly).

    Returns (position_ms, loop_bars, similarity_score) or None if nothing found.
    """
    if not track.waveform:
        return None

    bg = track.beat_grid
    n = len(track.waveform)
    total_ms = track.duration_ms
    if total_ms <= 0 or n == 0:
        return None

    for loop_bars in bar_sizes:
        loop_ms = bg.bars_to_ms(loop_bars)
        best_pos = None
        best_score = 0.0

        # Snap search start to bar boundary
        start_beat = bg.ms_to_beat(search_start_ms)
        bar_start = ((start_beat - 1) // 4) * 4 + 1
        pos_ms = bg.beat_to_ms(bar_start)

        while pos_ms + loop_ms <= search_end_ms and pos_ms + loop_ms <= total_ms:
            # Map to waveform indices
            i0 = int(n * pos_ms / total_ms)
            i1 = int(n * (pos_ms + loop_ms) / total_ms)
            i_mid = (i0 + i1) // 2
            if i1 - i0 < 4:
                pos_ms += bg.bars_to_ms(1)
                continue

            # Check energy
            heights = [p.height for p in track.waveform[i0:i1]]
            mean_e = sum(heights) / len(heights)
            if mean_e < min_energy:
                pos_ms += bg.bars_to_ms(1)
                continue

            # Check spectral similarity between halves
            similarity = _spectral_similarity(track.waveform, i0, i_mid, i1)
            if similarity > best_score:
                best_score = similarity
                best_pos = pos_ms

            pos_ms += bg.bars_to_ms(1)

        if best_pos is not None and best_score >= min_similarity:
            return (best_pos, loop_bars, best_score)

            pos_ms += bg.bars_to_ms(1)  # slide by 1 bar

    return None


class CueStrategy:
    """Proposes cue placements based on phrase analysis, genre profiles, and cue system.

    Supports genre personalization for Industrial Techno, Hard Techno/Schranz,
    Hypnotic Groove, Hard Groove, Bounce, Trance, and general dance music.
    """

    def __init__(
        self,
        memory_offset_bars: int | None = None,
        loop_length_bars: int | None = None,
        genre: str = "auto",
        tempo_adaptive: bool = True,
        max_hot_cues: int = 8,
        use_loops: bool = True,
        auto_end_loop: bool = False,
    ) -> None:
        self.genre = genre
        self._user_memory_offset = memory_offset_bars
        self._user_loop_bars = loop_length_bars
        self.tempo_adaptive = tempo_adaptive
        self.max_hot_cues = max(1, min(16, max_hot_cues))
        self.use_loops = use_loops
        self.auto_end_loop = auto_end_loop

    @property
    def memory_offset_bars(self) -> int:
        return self._user_memory_offset if self._user_memory_offset is not None else 16

    @property
    def loop_length_bars(self) -> int:
        return self._user_loop_bars if self._user_loop_bars is not None else 4

    def _resolve_profile(self, track: Track) -> dict:
        """Resolve active genre profile — either explicitly chosen or auto-detected by BPM."""
        if self.genre and self.genre.lower() != "auto":
            return get_genre_profile(self.genre)
        # Automatic detection based on track BPM
        if track.bpm >= 158.0:
            return get_genre_profile("schranz")
        elif track.bpm >= 150.0:
            return get_genre_profile("industrial")
        elif track.bpm >= 142.0:
            return get_genre_profile("hard_groove")
        elif track.bpm >= 135.0:
            return get_genre_profile("hypnotic_groove")
        return get_genre_profile("general")

    def propose(self, track: Track) -> CueProposal:
        """Generate a cue proposal for a track based on phrase, beat structure, and genre."""
        bg = track.beat_grid
        phrases = track.phrases
        hot_cues: list[CuePoint] = []
        memory_cues: list[CuePoint] = []
        confidence: dict[str, float] = {}
        notes: list[str] = []

        profile = self._resolve_profile(track)
        labels = profile["labels"]

        # Loop length resolution: explicit user override > profile default
        if self._user_loop_bars is not None:
            effective_loop_bars = self._user_loop_bars
        else:
            effective_loop_bars = profile.get("default_loop_bars", 8 if track.bpm >= 140 else 4)

        # Memory offset resolution: explicit user override > profile default
        if self._user_memory_offset is not None:
            effective_offset_bars = self._user_memory_offset
        else:
            effective_offset_bars = profile.get("default_memory_offset_bars", 16)

        pre_drop_d = profile.get("pre_drop_d_beats", 8)
        pre_drop_f = profile.get("pre_drop_f_beats", 32)

        loop_status = f"{effective_loop_bars} Takte" if self.use_loops else "Aus (nur Cue-Punkte)"
        auto_end_status = "Aktiv" if self.auto_end_loop else "Aus"
        notes.append(
            f"Genre-Profil: {profile['name']} ({profile['bpm_range']}) "
            f"— Hot Cues: {self.max_hot_cues}, Loops: {loop_status}, Auto-End-Loop: {auto_end_status}, Offset: {effective_offset_bars} Takte"
        )

        positions: dict[str, float] = {}

        # --- A: First Beat ---
        positions["A"] = bg.beat_to_ms(1)
        confidence["A"] = 1.0
        notes.append(f"A ({labels['A']}): beat 1")

        # --- B: Bassline / Rumble / Groove Entry ---
        intro_end = max(
            (p.position_ms + p.duration_ms for p in phrases if p.label == "Intro"),
            default=positions["A"],
        )
        bass_candidates = [p for p in phrases if p.position_ms >= intro_end and p.label == "Up"]
        if not bass_candidates:
            bass_candidates = [
                p for p in phrases
                if p.position_ms > positions["A"] and p.label not in ("Intro", "Unknown")
            ]
        if bass_candidates:
            bass_phrase = bass_candidates[0]
            positions["B"] = bass_phrase.position_ms
            confidence["B"] = 0.70
            notes.append(f"B ({labels['B']}): {bass_phrase.label} at beat {bass_phrase.beat_start}")
        elif phrases:
            positions["B"] = positions["A"]
            confidence["B"] = 0.25
            notes.append(f"B ({labels['B']}): no post-intro phrase found — using beat 1")
        else:
            # Fallback for tracks without PSSI analysis
            default_b_beat = 65 if track.duration_ms >= 120_000 else 33
            positions["B"] = min(bg.beat_to_ms(default_b_beat), track.duration_ms * 0.2)
            confidence["B"] = 0.50
            notes.append(f"B ({labels['B']}): grid-based fallback at beat {default_b_beat} (no PSSI phrases)")

        # --- G: Main Drop / Climax Detection ---
        choruses = [p for p in phrases if p.label == "Chorus"]
        min_drop_ms = track.duration_ms * 0.20
        late_choruses = [p for p in choruses if p.position_ms >= min_drop_ms]

        main_drop: Phrase | None = None

        if late_choruses:
            main_drop = late_choruses[0]
            positions["G"] = main_drop.position_ms
            confidence["G"] = 0.85
            notes.append(f"G ({labels['G']}): first Chorus after 20% at beat {main_drop.beat_start}")
        elif choruses:
            main_drop = choruses[-1]
            positions["G"] = main_drop.position_ms
            confidence["G"] = 0.60
            notes.append(f"G ({labels['G']}): fallback to last Chorus at beat {main_drop.beat_start}")
        elif phrases:
            # Techno / Groove / Underground fallback: Mood 2 (Verse/Bridge) without "Chorus" tag
            breakdowns = [
                p for p in phrases
                if p.label in ("Down", "Bridge") and p.position_ms >= min_drop_ms
            ]
            post_breakdown_drop: Phrase | None = None
            if breakdowns:
                for bd in breakdowns:
                    candidates = [
                        p for p in phrases
                        if p.beat_start >= bd.beat_end and p.label not in ("Down", "Bridge", "Outro", "Intro")
                    ]
                    if candidates:
                        post_breakdown_drop = candidates[0]
                        break

            if post_breakdown_drop is not None:
                main_drop = post_breakdown_drop
                positions["G"] = main_drop.position_ms
                confidence["G"] = 0.75
                notes.append(f"G ({labels['G']}): climax after breakdown at beat {main_drop.beat_start} ({main_drop.label})")
            else:
                # Search for the longest or most energetic phrase in the 25%-60% zone
                mid_phrases = [
                    p for p in phrases
                    if p.position_ms >= min_drop_ms and p.position_ms <= track.duration_ms * 0.65
                    and p.label not in ("Intro", "Outro")
                ]
                if mid_phrases:
                    chosen = max(mid_phrases, key=lambda p: (p.duration_ms, p.position_ms))
                    main_drop = chosen
                    positions["G"] = chosen.position_ms
                    confidence["G"] = 0.35
                    notes.append(f"G ({labels['G']}): phrase-energy fallback at beat {chosen.beat_start} ({chosen.label})")
                else:
                    main_drop = None
                    confidence["G"] = 0.0
                    notes.append(f"G ({labels['G']}): no suitable phrase found — skipped")
        else:
            # Fallback for tracks without PSSI
            drop_beat = ((bg.ms_to_beat(track.duration_ms * 0.33) - 1) // 16) * 16 + 1
            positions["G"] = bg.beat_to_ms(max(65, drop_beat))
            confidence["G"] = 0.35
            notes.append(f"G ({labels['G']}): grid-based 33% fallback at beat {drop_beat} (no PSSI phrases)")

        # --- C: First Breakdown ---
        # Must be strictly after Pad B and before Pad G
        min_c_ms = positions.get("B", positions["A"]) + bg.bars_to_ms(4)
        if "G" in positions:
            before_drop = [
                p for p in phrases
                if p.position_ms < positions["G"] and p.position_ms >= min_c_ms
            ]
        else:
            before_drop = [p for p in phrases if p.position_ms >= min_c_ms]

        early_breakdowns = [p for p in before_drop if p.label in ("Down", "Bridge")]
        if early_breakdowns:
            first_breakdown = early_breakdowns[0]
            positions["C"] = first_breakdown.position_ms
            confidence["C"] = 0.80
            notes.append(f"C ({labels['C']}): {first_breakdown.label} at beat {first_breakdown.beat_start}")
        else:
            # Fallback: distinct pre-drop Up/Verse phrase, or early transition strictly between B and G
            pre_drop_phrases = [
                p for p in before_drop
                if p.label in ("Up", "Verse1", "Verse2", "Verse3", "Verse4", "Verse5", "Verse6")
                and p.position_ms >= min_c_ms
            ]
            if pre_drop_phrases:
                fallback = pre_drop_phrases[-1]
                positions["C"] = fallback.position_ms
                confidence["C"] = 0.50
                notes.append(f"C ({labels['C']}): no Down/Bridge; fallback to {fallback.label} at beat {fallback.beat_start}")
            elif before_drop and "G" in positions:
                # e.g. early intro drop / transition before the main climax
                early_transitions = [
                    p for p in before_drop
                    if p.position_ms <= positions["G"] - bg.bars_to_ms(4)
                ]
                if early_transitions:
                    fallback = early_transitions[0]
                    positions["C"] = fallback.position_ms
                    confidence["C"] = 0.45
                    notes.append(f"C ({labels['C']}): pre-drop transition ({fallback.label}) at beat {fallback.beat_start}")
                else:
                    confidence["C"] = 0.0
                    notes.append(f"C ({labels['C']}): no suitable pre-drop phrase found")
            elif not phrases and "G" in positions and positions["G"] > min_c_ms:
                # Grid fallback for tracks without PSSI
                mid_beat = ((bg.ms_to_beat((positions["B"] + positions["G"]) / 2) - 1) // 8) * 8 + 1
                positions["C"] = bg.beat_to_ms(mid_beat)
                confidence["C"] = 0.40
                notes.append(f"C ({labels['C']}): grid midpoint fallback at beat {mid_beat}")
            else:
                confidence["C"] = 0.0
                notes.append(f"C ({labels['C']}): no suitable pre-drop phrase found")

        # --- D and F: Pre-Drop Waypoints ---
        if "G" in positions:
            positions["D"] = max(bg.beat_to_ms(1), positions["G"] - bg.ms_per_beat * pre_drop_d)
            positions["F"] = max(bg.beat_to_ms(1), positions["G"] - bg.ms_per_beat * pre_drop_f)
            d_conf = confidence["G"] if confidence["G"] < 0.5 else min(0.95, confidence["G"] + 0.1)
            confidence["D"] = d_conf
            confidence["F"] = d_conf
            notes.append(f"D ({labels['D']}): {pre_drop_d} beats before G")
            notes.append(f"F ({labels['F']}): {pre_drop_f} beats before G")

            # --- E: Main Breakdown ---
            after_drop = [
                p for p in phrases
                if p.position_ms > positions["G"] and p.label in ("Down", "Bridge")
            ]
            if after_drop:
                main_breakdown = max(after_drop, key=lambda p: (p.duration_ms, -p.position_ms))
                positions["E"] = main_breakdown.position_ms
                confidence["E"] = 0.85
                notes.append(f"E ({labels['E']}): {main_breakdown.label} at beat {main_breakdown.beat_start}")
            elif phrases:
                # In Emotional Schranz & Hard Techno, Rekordbox often tags loud vocal/synth
                # breakdowns between Choruses as "Up" or "Verse" instead of "Down".
                # Identify them by checking phrases between drops or checking waveform bass drop!
                mid_breaks = [
                    p for p in phrases
                    if p.position_ms > positions["G"]
                    and p.label not in ("Chorus", "Intro", "Outro")
                ]
                if mid_breaks:
                    # Prefer phrase with lowest bass energy (if waveform exists) or longest duration
                    def _break_score(ph: Phrase) -> tuple:
                        bass = _phrase_bass_energy(track, ph)
                        # Higher score = better breakdown: lower bass, longer duration
                        bass_score = -(bass if bass is not None else 4.0)
                        is_before_last_chorus = 1 if (choruses and ph.position_ms < choruses[-1].position_ms) else 0
                        return (is_before_last_chorus, bass_score, ph.duration_ms)

                    best_break = max(mid_breaks, key=_break_score)
                    bass_val = _phrase_bass_energy(track, best_break)
                    # Accept if it sits between drops or shows a real bass drop
                    if (choruses and best_break.position_ms < choruses[-1].position_ms) or (bass_val is not None and bass_val <= 3.5):
                        positions["E"] = best_break.position_ms
                        confidence["E"] = 0.75 if bass_val is not None and bass_val <= 3.5 else 0.65
                        notes.append(
                            f"E ({labels['E']}): vocal/emotional breakdown ({best_break.label}) at beat {best_break.beat_start}"
                        )
                    else:
                        confidence["E"] = 0.0
                        notes.append(f"E ({labels['E']}): no breakdown found after Main Drop")
                else:
                    confidence["E"] = 0.0
                    notes.append(f"E ({labels['E']}): no Down/Bridge found after Main Drop")
            elif not phrases:
                # Grid fallback
                e_beat = ((bg.ms_to_beat(track.duration_ms * 0.65) - 1) // 16) * 16 + 1
                positions["E"] = bg.beat_to_ms(e_beat)
                confidence["E"] = 0.40
                notes.append(f"E ({labels['E']}): grid-based 65% fallback at beat {e_beat}")
        else:
            confidence["D"] = confidence["F"] = 0.0
            notes.append("D/F: no Main Drop available for beat-offset markers")

        # --- H: Final Drop / Outro ---
        if choruses:
            final_drop = choruses[-1]
            positions["H"] = final_drop.position_ms
            confidence["H"] = 0.85
            notes.append(f"H ({labels['H']}): final Chorus at beat {final_drop.beat_start}")
        elif phrases:
            positions["H"] = next((p.position_ms for p in phrases if p.label == "Outro"), phrases[-1].position_ms)
            confidence["H"] = 0.65
            notes.append(f"H ({labels['H']}): using Outro/last phrase")
        else:
            # Fallback: 32 bars before end of track
            outro_beat = max(1, bg.ms_to_beat(track.duration_ms) - 128)
            outro_beat = ((outro_beat - 1) // 16) * 16 + 1
            positions["H"] = bg.beat_to_ms(outro_beat)
            confidence["H"] = 0.45
            notes.append(f"H ({labels['H']}): grid-based 32-bar mix-out at beat {outro_beat}")

        # --- Extended Pads (I–P) when max_hot_cues > 8 ---
        if self.max_hot_cues > 8:
            total_beats = max(65, bg.ms_to_beat(track.duration_ms))

            # I: 16 Bars Before Main Drop
            if "G" in positions:
                positions["I"] = max(bg.beat_to_ms(1), positions["G"] - bg.bars_to_ms(16))
                confidence["I"] = confidence.get("G", 0.8)
                notes.append("I (16 Bars Before Main Drop): long mix-in waypoint")

            # J: Second Drop / Peak 2
            min_j_ms = positions.get("E", positions.get("G", bg.beat_to_ms(1)) + bg.bars_to_ms(16))
            second_choruses = [p for p in choruses if p.position_ms > min_j_ms and ("H" not in positions or p.position_ms < positions["H"])]
            if second_choruses:
                j_phrase = second_choruses[0]
                positions["J"] = j_phrase.position_ms
                confidence["J"] = 0.80
                notes.append(f"J (Second Drop / Peak 2): Chorus at beat {j_phrase.beat_start}")
            else:
                late_up = [p for p in phrases if p.position_ms > min_j_ms and p.label in ("Up", "Verse4", "Verse5", "Verse6")]
                if late_up:
                    positions["J"] = late_up[0].position_ms
                    confidence["J"] = 0.65
                else:
                    j_beat = ((int(total_beats * 0.70) - 1) // 16) * 16 + 1
                    positions["J"] = bg.beat_to_ms(max(65, j_beat))
                    confidence["J"] = 0.45

            # K: 16 Beats Before Drop 2
            if "J" in positions:
                positions["K"] = max(bg.beat_to_ms(1), positions["J"] - bg.ms_per_beat * 16)
                confidence["K"] = confidence.get("J", 0.7)

            # L: Second Breakdown
            extra_breaks = [
                p for p in phrases
                if p.label in ("Down", "Bridge")
                and p.position_ms != positions.get("C")
                and p.position_ms != positions.get("E")
            ]
            if extra_breaks:
                positions["L"] = extra_breaks[-1].position_ms
                confidence["L"] = 0.75
            else:
                l_beat = ((int(total_beats * 0.48) - 1) // 16) * 16 + 1
                positions["L"] = bg.beat_to_ms(max(33, l_beat))
                confidence["L"] = 0.40

            # M: Vocal Hook (PVDI) or Mid Shift
            vocal_ms = None
            if track.vocal_track:
                for idx, val in enumerate(track.vocal_track):
                    if val >= 2:
                        raw_ms = idx * (1024 / 22050) * 1000
                        v_beat = bg.ms_to_beat(raw_ms)
                        vocal_ms = bg.beat_to_ms(v_beat)
                        break
            if vocal_ms is not None:
                positions["M"] = vocal_ms
                confidence["M"] = 0.80
                notes.append(f"M (Vocal Hook): PVDI vocal onset at beat {bg.ms_to_beat(vocal_ms)}")
            else:
                m_beat = ((int(total_beats * 0.55) - 1) // 16) * 16 + 1
                positions["M"] = bg.beat_to_ms(max(33, m_beat))
                confidence["M"] = 0.40

            # N: Final Buildup (32 beats before H)
            if "H" in positions:
                positions["N"] = max(bg.beat_to_ms(1), positions["H"] - bg.ms_per_beat * 32)
                confidence["N"] = 0.80

            # O: Mix-Out Trigger (16 bars before end)
            o_beat = max(1, total_beats - 64)
            o_beat = ((o_beat - 1) // 8) * 8 + 1
            positions["O"] = bg.beat_to_ms(o_beat)
            confidence["O"] = 0.75

            # P: Safety Outro Loop (8 bars before end)
            p_beat = max(1, total_beats - 32)
            p_beat = ((p_beat - 1) // 8) * 8 + 1
            positions["P"] = bg.beat_to_ms(p_beat)
            confidence["P"] = 0.75

        # --- Build CuePoint objects according to max_hot_cues & use_loops ---
        if self.max_hot_cues <= 4:
            # Compact 4-Hot-Cue mode: map Start (A), Bassline (B), Main Drop (G->C), Outro (H->D)
            compact_map = [
                ("A", "A", CUE_SYSTEM_BY_PAD["A"], False),
                ("B", "B", CUE_SYSTEM_BY_PAD["B"], True),
                ("C", "G" if "G" in positions else "C", CUE_SYSTEM_BY_PAD["G" if "G" in positions else "C"], False),
                ("D", "H" if "H" in positions else "E", CUE_SYSTEM_BY_PAD["H" if "H" in positions else "E"], True),
            ]
            target_slots = []
            for pad_out, src_key, style_slot, loop_flag in compact_map[: self.max_hot_cues]:
                if src_key not in positions:
                    continue
                target_slot = CUE_SYSTEM_BY_PAD[pad_out]
                pos_ms = positions[src_key]
                hot_label = labels.get(src_key, style_slot.hot_cue_label)
                mem_label = labels.get(src_key, style_slot.memory_cue_label)
                target_slots.append((
                    target_slot.kind,
                    pos_ms,
                    style_slot.hot_cue_color_table_index,
                    style_slot.hot_cue_color,
                    style_slot.memory_cue_color_table_index,
                    style_slot.memory_cue_color,
                    hot_label,
                    mem_label,
                    loop_flag,
                    style_slot.memory_offset_bars,
                ))
        else:
            active_slots = ALL_CUE_SLOTS[: self.max_hot_cues]
            target_slots = []
            for slot in active_slots:
                pad = slot.pad
                if pad not in positions:
                    continue
                pos_ms = positions[pad]
                hot_label = labels.get(pad, slot.hot_cue_label)
                mem_label = labels.get(pad, slot.memory_cue_label)
                target_slots.append((
                    slot.kind,
                    pos_ms,
                    slot.hot_cue_color_table_index,
                    slot.hot_cue_color,
                    slot.memory_cue_color_table_index,
                    slot.memory_cue_color,
                    hot_label,
                    mem_label,
                    slot.is_loop,
                    slot.memory_offset_bars,
                ))

        for (
            kind_val,
            pos_ms,
            hc_color_idx,
            hc_color,
            mc_color_idx,
            mc_color,
            hot_label,
            mem_label,
            slot_is_loop,
            slot_mem_offset,
        ) in target_slots:
            is_loop_active = slot_is_loop and self.use_loops
            loop_end = (pos_ms + bg.bars_to_ms(effective_loop_bars)) if is_loop_active else None

            hot_cues.append(CuePoint(
                kind=kind_val,
                position_ms=pos_ms,
                loop_end_ms=loop_end,
                color_table_index=hc_color_idx,
                color=hc_color,
                comment=hot_label,
            ))

            # Memory cue
            if slot_mem_offset == 0:
                mem_pos = pos_ms
            else:
                mem_pos = pos_ms - bg.bars_to_ms(effective_offset_bars)
                first_beat_ms = bg.beat_to_ms(1)
                if mem_pos < first_beat_ms:
                    mem_pos = first_beat_ms
                else:
                    mem_beat = bg.ms_to_beat(mem_pos)
                    bar_beat = ((mem_beat - 1) // 4) * 4 + 1
                    mem_pos = bg.beat_to_ms(bar_beat)

            mem_loop_end = (mem_pos + bg.bars_to_ms(effective_loop_bars)) if is_loop_active else None

            memory_cues.append(CuePoint(
                kind=0,
                position_ms=mem_pos,
                loop_end_ms=mem_loop_end,
                color_table_index=mc_color_idx,
                color=mc_color,
                comment=mem_label,
            ))

        # --- Auto-End-Loop (Rekordbox Active Loop Backup at track end) ---
        if self.auto_end_loop and track.duration_ms > 0:
            search_start = max(bg.beat_to_ms(1), track.duration_ms - bg.bars_to_ms(24))
            search_end = max(search_start + bg.bars_to_ms(2), track.duration_ms - bg.bars_to_ms(1))
            stable = _find_stable_loop(
                track,
                search_start_ms=search_start,
                search_end_ms=search_end,
                bar_sizes=(effective_loop_bars, 8, 4, 2),
                min_energy=0.05,
                min_similarity=0.65,
            )
            if stable is not None:
                auto_pos_ms, auto_bars, _ = stable
            else:
                # Place safely effective_loop_bars + 1 bars before track end, aligned to bar start
                auto_bars = effective_loop_bars
                total_beats = bg.ms_to_beat(track.duration_ms)
                while auto_bars > 2 and bg.bars_to_ms(auto_bars + 1) >= track.duration_ms * 0.4:
                    auto_bars //= 2
                target_beat = max(1, total_beats - (auto_bars * 4) - 4)
                bar_beat = ((target_beat - 1) // 4) * 4 + 1
                auto_pos_ms = bg.beat_to_ms(bar_beat)

            auto_end_ms = min(track.duration_ms, auto_pos_ms + bg.bars_to_ms(auto_bars))
            memory_cues.append(CuePoint(
                kind=0,
                position_ms=auto_pos_ms,
                loop_end_ms=auto_end_ms,
                color_table_index=0,
                color=5,  # Red (Rekordbox Active Loop indicator)
                comment="Auto-Backup Loop (Active)",
                active_loop=True,
            ))
            notes.append(
                f"Auto-End-Loop (Active Loop): {auto_bars} Takte Backup-Loop ab Beat "
                f"{bg.ms_to_beat(auto_pos_ms)} (aktiviert automatisch am Ende)"
            )

        return CueProposal(
            track=track,
            hot_cues=hot_cues,
            memory_cues=memory_cues,
            confidence=confidence,
            notes=notes,
        )
