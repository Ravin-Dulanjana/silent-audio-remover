#!/usr/bin/env python3
import numpy as np

from silence_remover import (
    SilenceSettings,
    _apply_render_segment_mode,
    _frame_stats_to_speech_mask,
    _pcm_to_speech_mask,
    _split_segments_by_count,
    _speech_mask_to_silences,
    build_keep_segments,
)


def test_basic_complement() -> None:
    settings = SilenceSettings(
        threshold_db=-42.0,
        remove_silences_longer_than=0.5,
        ignore_detections_shorter_than=0.75,
        left_padding=0.0,
        right_padding=0.0,
    )
    silences = [(0.0, 2.0), (5.0, 6.0), (8.0, 10.0)]
    keep = build_keep_segments(duration=10.0, silence_intervals=silences, settings=settings)
    assert keep == [(2.0, 5.0), (6.0, 8.0)]


def test_ignore_short_detections() -> None:
    settings = SilenceSettings(
        threshold_db=-42.0,
        remove_silences_longer_than=0.5,
        ignore_detections_shorter_than=0.5,
        left_padding=0.0,
        right_padding=0.0,
    )
    silences = [(0.0, 2.0), (5.0, 5.4), (8.0, 10.0)]
    keep = build_keep_segments(duration=10.0, silence_intervals=silences, settings=settings)
    assert keep == [(2.0, 8.0)]


def test_padding_and_merge() -> None:
    settings = SilenceSettings(
        threshold_db=-42.0,
        remove_silences_longer_than=0.5,
        ignore_detections_shorter_than=0.1,
        left_padding=0.2,
        right_padding=0.2,
    )
    silences = [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0)]
    keep = build_keep_segments(duration=5.0, silence_intervals=silences, settings=settings)
    assert keep == [(0.8, 2.2), (2.8, 4.2)]


def test_speech_mask_to_silences() -> None:
    speech = np.array([False, False, True, True, False, True], dtype=bool)
    silences = _speech_mask_to_silences(speech, frame_sec=0.5, duration=3.0)
    assert silences == [(0.0, 1.0), (2.0, 2.5)]


def test_pcm_detector_fills_short_silent_gap() -> None:
    settings = SilenceSettings(
        threshold_db=-38.0,
        remove_silences_longer_than=0.08,
        ignore_detections_shorter_than=0.1,
        left_padding=0.0,
        right_padding=0.0,
    )
    sample_rate = 1000
    frame_amplitudes = [0.0] * 5 + [0.8] * 5 + [0.0] + [0.8] * 4 + [0.0] * 5
    pcm = np.concatenate(
        [
            np.ones(int(sample_rate * 0.02), dtype=np.float32) * amplitude
            for amplitude in frame_amplitudes
        ]
    )
    speech, frame_sec = _pcm_to_speech_mask(pcm, sample_rate=sample_rate, settings=settings)
    assert frame_sec == 0.02
    assert speech[6:14].all()


def test_split_segments_by_count() -> None:
    segments = [(float(idx), float(idx + 1)) for idx in range(7)]
    groups = _split_segments_by_count(segments, max_segments_per_group=3)
    assert groups == [
        [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)],
        [(3.0, 4.0), (4.0, 5.0), (5.0, 6.0)],
        [(6.0, 7.0)],
    ]


def test_frame_stats_to_speech_mask_matches_pcm_path() -> None:
    settings = SilenceSettings(remove_silences_longer_than=0.08)
    sample_rate = 1000
    frame_amplitudes = [0.0] * 4 + [0.7] * 5 + [0.0] + [0.7] * 4
    pcm = np.concatenate(
        [
            np.ones(int(sample_rate * 0.02), dtype=np.float32) * amplitude
            for amplitude in frame_amplitudes
        ]
    )
    pcm_mask, _frame_sec = _pcm_to_speech_mask(pcm, sample_rate=sample_rate, settings=settings)

    frame_size = int(sample_rate * 0.02)
    frames = pcm.reshape(len(frame_amplitudes), frame_size)
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    peak = np.max(np.abs(frames), axis=1) + 1e-12
    frame_mask = _frame_stats_to_speech_mask(
        20.0 * np.log10(rms),
        20.0 * np.log10(peak),
        settings,
    )
    assert np.array_equal(frame_mask, pcm_mask)


def test_apply_render_segment_mode_merges_short_gaps() -> None:
    segments = [(1.0, 2.0), (2.04, 3.0), (4.0, 5.0)]
    merged = _apply_render_segment_mode(
        keep_segments=segments,
        render_mode="accurate",
        fast_merge_gap=0.12,
        accurate_merge_gap=0.05,
    )
    assert merged == [(1.0, 3.0), (4.0, 5.0)]
