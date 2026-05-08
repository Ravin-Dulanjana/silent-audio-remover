#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from silence_remover import (
    SilenceSettings,
    build_keep_segments,
    detect_silences,
    process_media,
)


def _probe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_entries",
        "format=duration",
        str(path),
    ]
    raw = subprocess.check_output(cmd, text=True)
    return float(json.loads(raw)["format"]["duration"])


def _frange(start: float, stop: float, step: float) -> list[float]:
    values: list[float] = []
    current = start
    while current <= stop + 1e-9:
        values.append(round(current, 6))
        current += step
    return values


def calibrate(
    input_path: Path,
    reference_output_path: Path,
    left_padding: float,
    right_padding: float,
    remove_silences_longer_than: float,
    detector: str,
) -> tuple[SilenceSettings, float, float]:
    target_duration = _probe_duration(reference_output_path)
    silence_cache: dict[tuple[float, float], tuple[float, list[tuple[float, float]]]] = {}

    def _get_detected(threshold_db: float, remove_longer: float) -> tuple[float, list[tuple[float, float]]]:
        key = (threshold_db, remove_longer)
        cached = silence_cache.get(key)
        if cached is not None:
            return cached
        settings = SilenceSettings(
            threshold_db=threshold_db,
            remove_silences_longer_than=remove_longer,
            ignore_detections_shorter_than=0.0,
            left_padding=0.0,
            right_padding=0.0,
        )
        duration, silences, _, _ = detect_silences(input_path, settings, detector=detector)
        silence_cache[key] = (duration, silences)
        return duration, silences

    best: tuple[float, float, float, int] | None = None
    for threshold_db in _frange(-48.0, -34.0, 1.0):
        for ignore_shorter in _frange(0.55, 1.15, 0.05):
            settings = SilenceSettings(
                threshold_db=threshold_db,
                remove_silences_longer_than=remove_silences_longer_than,
                ignore_detections_shorter_than=ignore_shorter,
                left_padding=left_padding,
                right_padding=right_padding,
            )
            duration, silences = _get_detected(
                threshold_db, remove_silences_longer_than
            )
            keep = build_keep_segments(duration, silences, settings)
            estimated_duration = sum(end - start for start, end in keep)
            kept_segments = len(keep)
            diff = abs(estimated_duration - target_duration)
            candidate = (diff, threshold_db, ignore_shorter, kept_segments)
            if best is None or candidate < best:
                best = candidate

    assert best is not None
    _, coarse_threshold, coarse_ignore, _ = best

    fine_best: tuple[float, float, float, int] | None = None
    for threshold_db in _frange(coarse_threshold - 1.0, coarse_threshold + 1.0, 0.25):
        for ignore_shorter in _frange(coarse_ignore - 0.12, coarse_ignore + 0.12, 0.02):
            settings = SilenceSettings(
                threshold_db=threshold_db,
                remove_silences_longer_than=remove_silences_longer_than,
                ignore_detections_shorter_than=max(0.0, ignore_shorter),
                left_padding=left_padding,
                right_padding=right_padding,
            )
            duration, silences = _get_detected(
                threshold_db, remove_silences_longer_than
            )
            keep = build_keep_segments(duration, silences, settings)
            estimated_duration = sum(end - start for start, end in keep)
            kept_segments = len(keep)
            diff = abs(estimated_duration - target_duration)
            candidate = (diff, threshold_db, ignore_shorter, kept_segments)
            if fine_best is None or candidate < fine_best:
                fine_best = candidate

    assert fine_best is not None
    best_diff, best_threshold, best_ignore, _ = fine_best
    tuned = SilenceSettings(
        threshold_db=best_threshold,
        remove_silences_longer_than=remove_silences_longer_than,
        ignore_detections_shorter_than=best_ignore,
        left_padding=left_padding,
        right_padding=right_padding,
    )
    return tuned, target_duration, best_diff


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Calibrate silence settings by matching output duration to a reference processed file."
        )
    )
    parser.add_argument("input", help="Original input media file")
    parser.add_argument("reference", help="Reference processed media file")
    parser.add_argument("--left-padding", type=float, default=0.01)
    parser.add_argument("--right-padding", type=float, default=0.15)
    parser.add_argument("--remove-silence-longer-than", type=float, default=0.5)
    parser.add_argument(
        "--detector",
        choices=["adaptive", "ffmpeg"],
        default="adaptive",
        help="Silence detector backend to use while calibrating.",
    )
    parser.add_argument(
        "--save-json",
        default="tuned_settings.json",
        help="Where to save tuned settings JSON",
    )
    parser.add_argument(
        "--render-output",
        help="Optional output file path to render input with tuned settings",
    )
    parser.add_argument(
        "--no-turbo",
        action="store_true",
        help="Disable hardware encode attempt while rendering.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    input_path = Path(args.input).expanduser().resolve()
    reference_path = Path(args.reference).expanduser().resolve()

    tuned, target_duration, best_diff = calibrate(
        input_path=input_path,
        reference_output_path=reference_path,
        left_padding=args.left_padding,
        right_padding=args.right_padding,
        remove_silences_longer_than=args.remove_silence_longer_than,
        detector=args.detector,
    )

    settings_path = Path(args.save_json).expanduser().resolve()
    settings_path.write_text(json.dumps(asdict(tuned), indent=2), encoding="utf-8")

    print("Calibration complete.")
    print(f"Target duration: {target_duration:.3f}s")
    print(f"Best estimated duration delta: {best_diff:.3f}s")
    print(
        "Tuned settings: "
        f"threshold_db={tuned.threshold_db:.3f}, "
        f"remove_silences_longer_than={tuned.remove_silences_longer_than:.3f}, "
        f"ignore_detections_shorter_than={tuned.ignore_detections_shorter_than:.3f}, "
        f"left_padding={tuned.left_padding:.3f}, "
        f"right_padding={tuned.right_padding:.3f}"
    )
    print(f"Saved: {settings_path}")

    if args.render_output:
        print(f"Rendering tuned output -> {args.render_output}")
        result = process_media(
            input_path=input_path,
            output_path=args.render_output,
            settings=tuned,
            detector=args.detector,
            turbo=not args.no_turbo,
            log=print,
        )
        print(f"Rendered duration: {result.output_duration:.3f}s")
        print(f"Duration delta vs reference: {abs(result.output_duration - target_duration):.3f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
