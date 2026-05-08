#!/usr/bin/env python3
from silence_remover import SilenceSettings, build_keep_segments


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
        ignore_detections_shorter_than=1.0,
        left_padding=0.0,
        right_padding=0.0,
    )
    silences = [(0.0, 2.0), (2.3, 10.0)]
    keep = build_keep_segments(duration=10.0, silence_intervals=silences, settings=settings)
    assert keep == []


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
