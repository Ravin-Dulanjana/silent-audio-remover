#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np


LogFn = Callable[[str], None]
ProgressFn = Callable[[float], None]


@dataclass(frozen=True)
class SilenceSettings:
    threshold_db: float = -42.0
    remove_silences_longer_than: float = 0.5
    ignore_detections_shorter_than: float = 0.75
    left_padding: float = 0.01
    right_padding: float = 0.15


@dataclass(frozen=True)
class ProcessResult:
    input_duration: float
    output_duration: float
    removed_duration: float
    segments_kept: int
    silences_detected: int
    output_path: Path


class SilenceRemoverError(RuntimeError):
    pass


class ProcessingCancelled(SilenceRemoverError):
    pass


def _default_logger(message: str) -> None:
    print(message)


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ProcessingCancelled("Processing stopped.")


def _stop_process(proc: subprocess.Popen[object]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=1.0)


def _ensure_binaries() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise SilenceRemoverError(
            "ffmpeg and ffprobe are required but were not found in PATH.\n"
            "Install on macOS with: brew install ffmpeg"
        )
    return ffmpeg, ffprobe


def _run_command_collect(cmd: Sequence[str], include_stderr: bool = False) -> str:
    proc = subprocess.run(
        cmd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise SilenceRemoverError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}"
        )
    if include_stderr:
        return f"{proc.stdout}\n{proc.stderr}"
    return proc.stdout


def _probe_media(ffprobe: str, input_path: Path) -> tuple[float, bool, bool]:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_entries",
        "format=duration:stream=codec_type",
        str(input_path),
    ]
    raw = _run_command_collect(cmd)
    data = json.loads(raw)
    duration = float(data["format"]["duration"])
    codec_types = [stream.get("codec_type", "") for stream in data.get("streams", [])]
    has_video = "video" in codec_types
    has_audio = "audio" in codec_types
    return duration, has_video, has_audio


def _merge_intervals(intervals: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    sorted_intervals = sorted((start, end) for start, end in intervals if end > start)
    if not sorted_intervals:
        return []

    merged: list[list[float]] = [[sorted_intervals[0][0], sorted_intervals[0][1]]]
    for start, end in sorted_intervals[1:]:
        tail = merged[-1]
        if start <= tail[1]:
            tail[1] = max(tail[1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _parse_silence_intervals(text: str, duration: float) -> list[tuple[float, float]]:
    start_pat = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
    end_pat = re.compile(
        r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)\s*\|\s*silence_duration:\s*([0-9]+(?:\.[0-9]+)?)"
    )

    starts: list[float] = []
    intervals: list[tuple[float, float]] = []
    for line in text.splitlines():
        m_start = start_pat.search(line)
        if m_start:
            starts.append(float(m_start.group(1)))
            continue

        m_end = end_pat.search(line)
        if m_end:
            end = float(m_end.group(1))
            silence_duration = float(m_end.group(2))
            if starts:
                start = starts.pop(0)
            else:
                start = max(0.0, end - silence_duration)
            intervals.append((start, end))

    for dangling_start in starts:
        if dangling_start < duration:
            intervals.append((dangling_start, duration))

    return _merge_intervals(intervals)


def _pcm_to_speech_mask(
    pcm: np.ndarray,
    sample_rate: int,
    settings: SilenceSettings,
) -> tuple[np.ndarray, float]:
    if pcm.size == 0:
        return np.zeros(0, dtype=bool), 0.02

    frame_sec = 0.02
    frame_size = max(1, int(sample_rate * frame_sec))
    frame_count = pcm.size // frame_size
    if frame_count <= 0:
        return np.zeros(0, dtype=bool), frame_sec

    trimmed = pcm[: frame_count * frame_size].reshape(frame_count, frame_size)
    rms = np.sqrt(np.mean(trimmed * trimmed, axis=1) + 1e-12)
    peak = np.max(np.abs(trimmed), axis=1) + 1e-12
    rms_db = 20.0 * np.log10(rms)
    peak_db = 20.0 * np.log10(peak)
    return _frame_stats_to_speech_mask(rms_db, peak_db, settings), frame_sec


def _frame_stats_to_speech_mask(
    rms_db: np.ndarray,
    peak_db: np.ndarray,
    settings: SilenceSettings,
    frame_sec: float = 0.02,
) -> np.ndarray:
    if rms_db.size == 0 or peak_db.size == 0:
        return np.zeros(0, dtype=bool)
    if rms_db.size != peak_db.size:
        raise ValueError("rms_db and peak_db must have the same length")

    # Blend RMS and peak so we catch speech onset more reliably than pure volume gating.
    energy_db = (rms_db * 0.82) + (peak_db * 0.18)

    smooth_window = 5
    kernel = np.ones(smooth_window, dtype=np.float32) / smooth_window
    smoothed = np.convolve(energy_db, kernel, mode="same")

    noise_floor = float(np.percentile(smoothed, 20))
    adaptive_threshold = max(settings.threshold_db, noise_floor + 7.5)
    open_threshold = adaptive_threshold
    close_threshold = adaptive_threshold - 2.0

    speech = np.zeros(rms_db.size, dtype=bool)
    active = False
    for idx, value in enumerate(smoothed):
        if active:
            active = value >= close_threshold
        else:
            active = value >= open_threshold
        speech[idx] = active

    min_silence_frames = max(
        1, int(round(settings.remove_silences_longer_than / frame_sec))
    )
    if min_silence_frames > 1:
        idx = 0
        while idx < speech.size:
            if speech[idx]:
                idx += 1
                continue
            start = idx
            while idx < speech.size and not speech[idx]:
                idx += 1
            if 0 < (idx - start) < min_silence_frames:
                speech[start:idx] = True

    return speech


def _speech_mask_to_silences(
    speech: np.ndarray,
    frame_sec: float,
    duration: float,
) -> list[tuple[float, float]]:
    if speech.size == 0:
        return [(0.0, duration)] if duration > 0 else []

    silences: list[tuple[float, float]] = []
    idx = 0
    frame_count = speech.size
    while idx < frame_count:
        if speech[idx]:
            idx += 1
            continue
        start = idx
        while idx < frame_count and not speech[idx]:
            idx += 1
        silences.append((start * frame_sec, min(duration, idx * frame_sec)))

    covered = frame_count * frame_sec
    if covered < duration and (not speech.size or not speech[-1]):
        if silences:
            tail_start, _tail_end = silences[-1]
            silences[-1] = (tail_start, duration)
        else:
            silences.append((covered, duration))
    return _merge_intervals(silences)


def _detect_silences_adaptive(
    ffmpeg: str,
    ffprobe: str,
    input_path: Path,
    settings: SilenceSettings,
    cancel_event: threading.Event | None = None,
    progress: ProgressFn | None = None,
) -> tuple[float, list[tuple[float, float]], bool, bool]:
    duration, has_video, has_audio = _probe_media(ffprobe, input_path)
    if not has_audio:
        raise SilenceRemoverError("Input has no audio track, cannot run silence detection.")

    sample_rate = 16000
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        str(max(1, os.cpu_count() or 1)),
        "-i",
        str(input_path),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    expected_bytes = max(1.0, duration * sample_rate * 2.0)
    chunks: list[bytes] = []
    bytes_read = 0
    while True:
        _check_cancel(cancel_event)
        chunk = proc.stdout.read(65536)
        if not chunk:
            break
        chunks.append(chunk)
        bytes_read += len(chunk)
        if progress is not None:
            progress(min(100.0, (bytes_read / expected_bytes) * 100.0))
    code = proc.wait()
    if cancel_event is not None and cancel_event.is_set():
        _stop_process(proc)
        raise ProcessingCancelled("Processing stopped.")
    if code != 0:
        raise SilenceRemoverError(f"ffmpeg adaptive detection failed with exit code {code}.")
    raw = b"".join(chunks)
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    speech, frame_sec = _pcm_to_speech_mask(pcm, sample_rate, settings)
    silences = _speech_mask_to_silences(speech, frame_sec, duration)
    if progress is not None:
        progress(100.0)
    return duration, silences, has_video, has_audio


def detect_silences(
    input_path: Path,
    settings: SilenceSettings,
    detector: str = "adaptive",
    cancel_event: threading.Event | None = None,
    progress: ProgressFn | None = None,
) -> tuple[float, list[tuple[float, float]], bool, bool]:
    ffmpeg, ffprobe = _ensure_binaries()
    if detector == "adaptive":
        return _detect_silences_adaptive(
            ffmpeg, ffprobe, input_path, settings, cancel_event, progress
        )
    if detector != "ffmpeg":
        raise SilenceRemoverError("detector must be 'adaptive' or 'ffmpeg'.")
    duration, has_video, has_audio = _probe_media(ffprobe, input_path)

    if not has_audio:
        raise SilenceRemoverError("Input has no audio track, cannot run silence detection.")

    silencedetect_cmd = [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-threads",
        str(max(1, os.cpu_count() or 1)),
        "-i",
        str(input_path),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-af",
        f"silencedetect=n={settings.threshold_db}dB:d={settings.remove_silences_longer_than}",
        "-progress",
        "pipe:1",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.Popen(
        silencedetect_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        _check_cancel(cancel_event)
        line = line.strip()
        if not line:
            continue
        lines.append(line)
        if progress is not None and line.startswith("out_time_ms="):
            try:
                done = int(line.split("=", 1)[1]) / 1_000_000.0
                progress(max(0.0, min(100.0, (done / max(duration, 0.001)) * 100.0)))
            except ValueError:
                pass

    code = proc.wait()
    if cancel_event is not None and cancel_event.is_set():
        _stop_process(proc)
        raise ProcessingCancelled("Processing stopped.")
    if code != 0:
        raise SilenceRemoverError(f"ffmpeg silencedetect failed with exit code {code}.")
    raw = "\n".join(lines)
    silences = _parse_silence_intervals(raw, duration)
    if progress is not None:
        progress(100.0)
    return duration, silences, has_video, has_audio


def build_keep_segments(
    duration: float,
    silence_intervals: Sequence[tuple[float, float]],
    settings: SilenceSettings,
) -> list[tuple[float, float]]:
    if duration <= 0:
        return []

    silences = _merge_intervals(
        [
            (start, end)
            for start, end in silence_intervals
            if (end - start) >= settings.ignore_detections_shorter_than
        ]
    )
    keep: list[tuple[float, float]] = []

    cursor = 0.0
    for start, end in silences:
        if start > cursor:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        keep.append((cursor, duration))
    if not keep:
        return []

    padded = [
        (max(0.0, start - settings.left_padding), min(duration, end + settings.right_padding))
        for start, end in keep
    ]
    return _merge_intervals(padded)


def _supports_encoder(ffmpeg: str, encoder: str) -> bool:
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output = f"{proc.stdout}\n{proc.stderr}"
    return encoder in output


def _format_time(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_seconds = total_ms // 1000
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _merge_short_gaps(
    keep_segments: Sequence[tuple[float, float]], max_gap_seconds: float
) -> list[tuple[float, float]]:
    if max_gap_seconds <= 0 or not keep_segments:
        return list(keep_segments)

    merged: list[list[float]] = [[keep_segments[0][0], keep_segments[0][1]]]
    for start, end in keep_segments[1:]:
        tail = merged[-1]
        if start - tail[1] <= max_gap_seconds:
            tail[1] = max(tail[1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _apply_render_segment_mode(
    keep_segments: Sequence[tuple[float, float]],
    render_mode: str,
    fast_merge_gap: float,
    accurate_merge_gap: float,
) -> list[tuple[float, float]]:
    render_segments = list(keep_segments)
    if render_mode == "fast":
        return _merge_short_gaps(render_segments, max(0.0, fast_merge_gap))
    if render_mode == "accurate":
        if accurate_merge_gap > 0.0:
            return _merge_short_gaps(render_segments, accurate_merge_gap)
        return render_segments
    raise SilenceRemoverError("render_mode must be 'accurate' or 'fast'.")


def _run_ffmpeg_progress(
    cmd: Sequence[str],
    duration: float,
    log: LogFn,
    cancel_event: threading.Event | None = None,
    progress: ProgressFn | None = None,
) -> int:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    progress_keys = {
        "frame",
        "fps",
        "stream_0_0_q",
        "bitrate",
        "total_size",
        "out_time_us",
        "out_time_ms",
        "out_time",
        "dup_frames",
        "drop_frames",
        "speed",
        "progress",
    }

    assert proc.stdout is not None
    for line in proc.stdout:
        _check_cancel(cancel_event)
        line = line.strip()
        if not line:
            continue

        if "=" in line:
            key, value = line.split("=", 1)
            if key in progress_keys:
                if progress is not None and key == "out_time_ms":
                    try:
                        done = int(value) / 1_000_000.0
                        percent = max(0.0, min(100.0, (done / max(duration, 0.001)) * 100.0))
                        progress(percent)
                    except ValueError:
                        pass
                continue

        if "Non-monotonic DTS" in line or "out of order" in line:
            continue
        if "Queue input is backward in time" in line:
            continue

        log(line)
    code = proc.wait()
    if cancel_event is not None and cancel_event.is_set():
        _stop_process(proc)
        raise ProcessingCancelled("Processing stopped.")
    return code


def _segment_duration(segments: Sequence[tuple[float, float]]) -> float:
    return sum(end - start for start, end in segments)


def _segment_source_span(segments: Sequence[tuple[float, float]]) -> tuple[float, float]:
    if not segments:
        return 0.0, 0.0
    return segments[0][0], segments[-1][1]


def _split_segments_by_count(
    keep_segments: Sequence[tuple[float, float]], max_segments_per_group: int
) -> list[list[tuple[float, float]]]:
    if max_segments_per_group <= 0:
        raise ValueError("max_segments_per_group must be >= 1")
    if not keep_segments:
        return []
    if len(keep_segments) <= max_segments_per_group:
        return [list(keep_segments)]
    return [
        list(keep_segments[idx : idx + max_segments_per_group])
        for idx in range(0, len(keep_segments), max_segments_per_group)
    ]


def _render_with_concat_copy(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    keep_segments: Sequence[tuple[float, float]],
    has_video: bool,
    has_audio: bool,
    duration: float,
    turbo: bool,
    log: LogFn,
    cancel_event: threading.Event | None = None,
    progress: ProgressFn | None = None,
) -> None:
    if not keep_segments:
        raise SilenceRemoverError("No non-silent segments remained after applying settings.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    input_escaped = str(input_path).replace("'", r"'\''")
    with tempfile.TemporaryDirectory(prefix="silent-fast-") as tmpdir:
        concat_path = Path(tmpdir) / "segments.ffconcat"
        lines = ["ffconcat version 1.0"]
        for start, end in keep_segments:
            lines.append(f"file '{input_escaped}'")
            lines.append(f"inpoint {start:.6f}")
            lines.append(f"outpoint {end:.6f}")
        concat_path.write_text("\n".join(lines), encoding="utf-8")

        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-nostats",
            "-progress",
            "pipe:1",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-fflags",
            "+genpts",
            "-avoid_negative_ts",
            "make_zero",
        ]

        use_hw_encode = has_video and turbo and _supports_encoder(ffmpeg, "h264_videotoolbox")
        cpu_threads = max(1, os.cpu_count() or 1)

        def _finish_cmd(use_hw: bool) -> list[str]:
            c = list(cmd)
            c.extend(["-threads", str(cpu_threads)])
            if has_video:
                if use_hw:
                    c.extend(["-c:v", "h264_videotoolbox", "-allow_sw", "1", "-b:v", "8M"])
                else:
                    c.extend(["-c:v", "libx264", "-preset", "ultrafast", "-crf", "24"])
            if has_audio:
                c.extend(["-c:a", "aac", "-b:a", "160k"])
            c.extend(["-movflags", "+faststart", str(output_path)])
            return c

        code = _run_ffmpeg_progress(
            _finish_cmd(use_hw_encode),
            duration=duration,
            log=log,
            cancel_event=cancel_event,
            progress=progress,
        )
        if code != 0 and use_hw_encode:
            log("Fast mode hardware encode failed, retrying with software encoder (libx264).")
            code = _run_ffmpeg_progress(
                _finish_cmd(False),
                duration=duration,
                log=log,
                cancel_event=cancel_event,
                progress=progress,
            )
        if code != 0:
            raise SilenceRemoverError(f"ffmpeg fast render failed with exit code {code}.")


def _render_with_ffmpeg_singlepass(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    keep_segments: Sequence[tuple[float, float]],
    has_video: bool,
    has_audio: bool,
    duration: float,
    turbo: bool,
    log: LogFn,
    cancel_event: threading.Event | None = None,
    progress: ProgressFn | None = None,
) -> None:
    if not keep_segments:
        raise SilenceRemoverError("No non-silent segments remained after applying settings.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="silent-cut-") as tmpdir:
        script_path = Path(tmpdir) / "filter_complex.txt"
        filter_lines: list[str] = []
        if has_video and has_audio:
            expr = "+".join(
                f"between(t\\,{start:.6f}\\,{end:.6f})" for start, end in keep_segments
            )
            filter_lines.append(
                f"[0:v]select='{expr}',setpts=N/FRAME_RATE/TB[outv];"
            )
            filter_lines.append(
                f"[0:a]aselect='{expr}',asetpts=N/SR/TB[outa]"
            )
            maps = ["-map", "[outv]", "-map", "[outa]"]
        elif has_audio:
            expr = "+".join(
                f"between(t\\,{start:.6f}\\,{end:.6f})" for start, end in keep_segments
            )
            filter_lines.append(
                f"[0:a]aselect='{expr}',asetpts=N/SR/TB[outa]"
            )
            maps = ["-map", "[outa]"]
        else:
            expr = "+".join(
                f"between(t\\,{start:.6f}\\,{end:.6f})" for start, end in keep_segments
            )
            filter_lines.append(
                f"[0:v]select='{expr}',setpts=N/FRAME_RATE/TB[outv]"
            )
            maps = ["-map", "[outv]"]

        script_path.write_text("\n".join(filter_lines), encoding="utf-8")

        use_hw_encode = has_video and turbo and _supports_encoder(ffmpeg, "h264_videotoolbox")
        cpu_threads = max(1, os.cpu_count() or 1)

        def _build_cmd(use_hw: bool) -> list[str]:
            cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "warning",
                "-nostats",
                "-progress",
                "pipe:1",
                "-threads",
                str(cpu_threads),
                "-y",
                "-i",
                str(input_path),
                "-/filter_complex",
                str(script_path),
                *maps,
            ]
            if has_video:
                if use_hw:
                    cmd.extend(["-c:v", "h264_videotoolbox", "-allow_sw", "1", "-b:v", "8M"])
                else:
                    cmd.extend(["-c:v", "libx264", "-preset", "superfast", "-crf", "21"])
            if has_audio:
                cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            cmd.extend(["-movflags", "+faststart", str(output_path)])
            return cmd

        cmd = _build_cmd(use_hw=use_hw_encode)
        code = _run_ffmpeg_progress(
            cmd, duration=duration, log=log, cancel_event=cancel_event, progress=progress
        )
        if code != 0 and use_hw_encode:
            log("Hardware encode failed, retrying with software encoder (libx264).")
            cmd = _build_cmd(use_hw=False)
            code = _run_ffmpeg_progress(
                cmd, duration=duration, log=log, cancel_event=cancel_event, progress=progress
            )

        if code != 0:
            raise SilenceRemoverError(f"ffmpeg render failed with exit code {code}.")

    if progress is not None:
        progress(100.0)


def _render_with_ffmpeg_batched(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    keep_segments: Sequence[tuple[float, float]],
    has_video: bool,
    has_audio: bool,
    duration: float,
    turbo: bool,
    log: LogFn,
    cancel_event: threading.Event | None = None,
    progress: ProgressFn | None = None,
    max_segments_per_pass: int = 48,
) -> None:
    groups = _split_segments_by_count(keep_segments, max_segments_per_pass)
    if len(groups) <= 1:
        _render_with_ffmpeg_singlepass(
            ffmpeg=ffmpeg,
            input_path=input_path,
            output_path=output_path,
            keep_segments=keep_segments,
            has_video=has_video,
            has_audio=has_audio,
            duration=duration,
            turbo=turbo,
            log=log,
            cancel_event=cancel_event,
            progress=progress,
        )
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    log(
        "Batch render enabled: "
        f"{len(keep_segments)} kept segments split into {len(groups)} passes"
    )
    group_weights = [_segment_duration(group) for group in groups]
    total_weight = max(0.001, sum(group_weights))

    with tempfile.TemporaryDirectory(prefix="silent-batched-") as tmpdir:
        part_paths = [Path(tmpdir) / f"batch_{idx:03d}.mp4" for idx in range(len(groups))]
        completed_weight = 0.0

        for idx, group in enumerate(groups):
            _check_cancel(cancel_event)
            span_start, span_end = _segment_source_span(group)
            label = (
                f"Batch {idx + 1}/{len(groups)} "
                f"({_format_time(span_start)} -> {_format_time(span_end)})"
            )
            log(f"{label} started")

            def _batch_progress(pct: float) -> None:
                if progress is None:
                    return
                current = completed_weight + (group_weights[idx] * max(0.0, min(100.0, pct)) / 100.0)
                progress(min(95.0, (current / total_weight) * 95.0))

            _render_with_ffmpeg_singlepass(
                ffmpeg=ffmpeg,
                input_path=input_path,
                output_path=part_paths[idx],
                keep_segments=group,
                has_video=has_video,
                has_audio=has_audio,
                duration=max(0.001, group_weights[idx]),
                turbo=turbo,
                log=lambda _msg: None,
                cancel_event=cancel_event,
                progress=_batch_progress,
            )
            completed_weight += group_weights[idx]
            log(f"{label} completed")

        if progress is not None:
            progress(96.0)
        log("Combining rendered batches...")
        _concat_parts_copy(
            ffmpeg=ffmpeg,
            part_paths=part_paths,
            output_path=output_path,
            duration=duration,
            log=log,
            cancel_event=cancel_event,
            progress=progress,
        )


def _render_with_ffmpeg(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    keep_segments: Sequence[tuple[float, float]],
    has_video: bool,
    has_audio: bool,
    duration: float,
    turbo: bool,
    log: LogFn,
    cancel_event: threading.Event | None = None,
    progress: ProgressFn | None = None,
) -> None:
    max_segments_per_pass = 48
    if len(keep_segments) > max_segments_per_pass:
        _render_with_ffmpeg_batched(
            ffmpeg=ffmpeg,
            input_path=input_path,
            output_path=output_path,
            keep_segments=keep_segments,
            has_video=has_video,
            has_audio=has_audio,
            duration=duration,
            turbo=turbo,
            log=log,
            cancel_event=cancel_event,
            progress=progress,
            max_segments_per_pass=max_segments_per_pass,
        )
        return
    _render_with_ffmpeg_singlepass(
        ffmpeg=ffmpeg,
        input_path=input_path,
        output_path=output_path,
        keep_segments=keep_segments,
        has_video=has_video,
        has_audio=has_audio,
        duration=duration,
        turbo=turbo,
        log=log,
        cancel_event=cancel_event,
        progress=progress,
    )


def _split_segments_for_parallel(
    keep_segments: Sequence[tuple[float, float]], parallel_jobs: int
) -> list[list[tuple[float, float]]]:
    if parallel_jobs <= 1 or len(keep_segments) <= 1:
        return [list(keep_segments)]

    total_keep = sum(end - start for start, end in keep_segments)
    target = max(0.001, total_keep / parallel_jobs)

    groups: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    current_duration = 0.0
    for segment in keep_segments:
        seg_duration = segment[1] - segment[0]
        if current and len(groups) < (parallel_jobs - 1) and current_duration >= target:
            groups.append(current)
            current = []
            current_duration = 0.0
        current.append(segment)
        current_duration += seg_duration
    if current:
        groups.append(current)
    return groups


def _concat_parts_copy(
    ffmpeg: str,
    part_paths: Sequence[Path],
    output_path: Path,
    duration: float,
    log: LogFn,
    cancel_event: threading.Event | None = None,
    progress: ProgressFn | None = None,
) -> None:
    if not part_paths:
        raise SilenceRemoverError("No rendered parts found for concat.")

    with tempfile.TemporaryDirectory(prefix="silent-concat-") as tmpdir:
        concat_path = Path(tmpdir) / "parts.ffconcat"
        lines = ["ffconcat version 1.0"]
        for part in part_paths:
            escaped = str(part).replace("'", r"'\''")
            lines.append(f"file '{escaped}'")
        concat_path.write_text("\n".join(lines), encoding="utf-8")

        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-nostats",
            "-progress",
            "pipe:1",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        code = _run_ffmpeg_progress(
            cmd, duration=duration, log=log, cancel_event=cancel_event, progress=progress
        )
        if code != 0:
            raise SilenceRemoverError(f"ffmpeg concat failed with exit code {code}.")


def _render_with_ffmpeg_parallel(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    keep_segments: Sequence[tuple[float, float]],
    has_video: bool,
    has_audio: bool,
    duration: float,
    parallel_jobs: int,
    log: LogFn,
    cancel_event: threading.Event | None = None,
    progress: ProgressFn | None = None,
) -> None:
    groups = _split_segments_for_parallel(keep_segments, parallel_jobs)
    if len(groups) <= 1:
        _render_with_ffmpeg(
            ffmpeg=ffmpeg,
            input_path=input_path,
            output_path=output_path,
            keep_segments=keep_segments,
            has_video=has_video,
            has_audio=has_audio,
            duration=duration,
            turbo=False,
            log=log,
            cancel_event=cancel_event,
            progress=progress,
        )
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    log(f"Parallel boost enabled: {len(groups)} chunks, {parallel_jobs} workers")

    with tempfile.TemporaryDirectory(prefix="silent-parallel-") as tmpdir:
        part_paths = [Path(tmpdir) / f"part_{idx:03d}.mp4" for idx in range(len(groups))]
        done_counter = 0
        lock = threading.Lock()
        chunk_weights = [_segment_duration(chunk) for chunk in groups]
        total_weight = max(0.001, sum(chunk_weights))
        chunk_progress = [0.0 for _ in groups]
        chunk_buckets = [-1 for _ in groups]

        def _publish_progress_locked() -> None:
            if progress is None:
                return
            weighted = sum(w * p for w, p in zip(chunk_weights, chunk_progress, strict=False))
            progress(min(95.0, (weighted / total_weight) * 95.0))

        def _worker(idx: int, chunk: Sequence[tuple[float, float]]) -> None:
            nonlocal done_counter
            span_start, span_end = _segment_source_span(chunk)
            label = (
                f"Chunk {idx + 1}/{len(groups)} "
                f"({_format_time(span_start)} -> {_format_time(span_end)})"
            )
            log(f"{label} started")

            def _chunk_progress(pct: float) -> None:
                _check_cancel(cancel_event)
                with lock:
                    chunk_progress[idx] = max(0.0, min(1.0, pct / 100.0))
                    bucket = int(pct // 10)
                    if bucket > chunk_buckets[idx] and bucket < 10:
                        chunk_buckets[idx] = bucket
                        log(f"{label} processing {bucket * 10}%")
                    _publish_progress_locked()

            _render_with_ffmpeg(
                ffmpeg=ffmpeg,
                input_path=input_path,
                output_path=part_paths[idx],
                keep_segments=chunk,
                has_video=has_video,
                has_audio=has_audio,
                duration=max(0.001, chunk_weights[idx]),
                turbo=False,
                log=lambda _msg: None,
                cancel_event=cancel_event,
                progress=_chunk_progress,
            )
            with lock:
                done_counter += 1
                chunk_progress[idx] = 1.0
                log(f"{label} completed")
                _publish_progress_locked()

        max_workers = max(1, min(parallel_jobs, len(groups)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_worker, idx, chunk) for idx, chunk in enumerate(groups)]
            for future in concurrent.futures.as_completed(futures):
                future.result()

        if progress is not None:
            progress(96.0)
        log("Combining rendered chunks...")
        _concat_parts_copy(
            ffmpeg=ffmpeg,
            part_paths=part_paths,
            output_path=output_path,
            duration=duration,
            log=log,
            cancel_event=cancel_event,
            progress=progress,
        )


def process_media(
    input_path: str | Path,
    output_path: str | Path,
    settings: SilenceSettings = SilenceSettings(),
    detector: str = "adaptive",
    turbo: bool = True,
    render_mode: str = "accurate",
    fast_merge_gap: float = 0.12,
    accurate_merge_gap: float = 0.08,
    parallel_jobs: int = 1,
    log: LogFn = _default_logger,
    cancel_event: threading.Event | None = None,
    progress: ProgressFn | None = None,
) -> ProcessResult:
    input_file = Path(input_path).expanduser().resolve()
    output_file = Path(output_path).expanduser().resolve()

    if not input_file.exists():
        raise SilenceRemoverError(f"Input file does not exist: {input_file}")

    if progress is not None:
        progress(0.0)

    try:
        ffmpeg, ffprobe = _ensure_binaries()
        _check_cancel(cancel_event)
        if detector == "adaptive":
            log("Analyzing audio track with adaptive speech detection...")
        else:
            log("Analyzing audio track for silence...")
        duration, silences, has_video, has_audio = detect_silences(
            input_file,
            settings,
            detector=detector,
            cancel_event=cancel_event,
            progress=(lambda p: progress(min(20.0, p * 0.2))) if progress is not None else None,
        )
        _check_cancel(cancel_event)
        keep_segments = build_keep_segments(duration, silences, settings)

        if not keep_segments:
            raise SilenceRemoverError(
                "All detected segments were below the minimum keep length.\n"
                "Try reducing 'Ignore Detections Shorter Than'."
            )

        render_segments = _apply_render_segment_mode(
            keep_segments=keep_segments,
            render_mode=render_mode,
            fast_merge_gap=fast_merge_gap,
            accurate_merge_gap=accurate_merge_gap,
        )
        if render_mode == "fast":
            log(
                f"Fast mode merged close cuts: {len(keep_segments)} -> {len(render_segments)} segments"
            )
        elif len(render_segments) != len(keep_segments):
            log(
                "Speed merge applied in standard mode: "
                f"{len(keep_segments)} -> {len(render_segments)} segments "
                f"(gap <= {accurate_merge_gap:.2f}s)"
            )

        kept_duration = sum(end - start for start, end in render_segments)
        removed_duration = max(0.0, duration - kept_duration)

        log(f"Input: {input_file.name}")
        log(f"Input duration: {_format_time(duration)}")
        log(f"Detected silences: {len(silences)}")
        log(f"Kept segments: {len(render_segments)}")
        log(f"Estimated removed: {_format_time(removed_duration)}")

        render_progress = (
            (lambda p: progress(min(100.0, 20.0 + (p * 0.8)))) if progress is not None else None
        )

        if render_mode == "fast":
            log("Rendering output with concat-based pass...")
            _render_with_concat_copy(
                ffmpeg=ffmpeg,
                input_path=input_file,
                output_path=output_file,
                keep_segments=render_segments,
                has_video=has_video,
                has_audio=has_audio,
                duration=max(0.001, kept_duration),
                turbo=turbo,
                log=log,
                cancel_event=cancel_event,
                progress=render_progress,
            )
        else:
            if parallel_jobs > 1:
                if turbo:
                    log("Turbo is disabled in parallel mode for stability.")
                _render_with_ffmpeg_parallel(
                    ffmpeg=ffmpeg,
                    input_path=input_file,
                    output_path=output_file,
                    keep_segments=render_segments,
                    has_video=has_video,
                    has_audio=has_audio,
                    duration=max(0.001, kept_duration),
                    parallel_jobs=parallel_jobs,
                    log=log,
                    cancel_event=cancel_event,
                    progress=render_progress,
                )
            else:
                log("Rendering selected spans in a single pass...")
                _render_with_ffmpeg(
                    ffmpeg=ffmpeg,
                    input_path=input_file,
                    output_path=output_file,
                    keep_segments=render_segments,
                    has_video=has_video,
                    has_audio=has_audio,
                    duration=max(0.001, kept_duration),
                    turbo=turbo,
                    log=log,
                    cancel_event=cancel_event,
                    progress=render_progress,
                )

        _check_cancel(cancel_event)
        output_duration, _, _ = _probe_media(ffprobe, output_file)
        if progress is not None:
            progress(100.0)

        return ProcessResult(
            input_duration=duration,
            output_duration=output_duration,
            removed_duration=max(0.0, duration - output_duration),
            segments_kept=len(render_segments),
            silences_detected=len(silences),
            output_path=output_file,
        )
    except ProcessingCancelled:
        if output_file.exists():
            output_file.unlink(missing_ok=True)
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove silent parts from video and audio files."
    )
    parser.add_argument("input", help="Input video/audio path")
    parser.add_argument("output", help="Output path")
    parser.add_argument("--threshold-db", type=float, default=-42.0)
    parser.add_argument("--remove-silence-longer-than", type=float, default=0.5)
    parser.add_argument("--ignore-detections-shorter-than", type=float, default=0.75)
    parser.add_argument("--left-padding", type=float, default=0.01)
    parser.add_argument("--right-padding", type=float, default=0.15)
    parser.add_argument(
        "--detector",
        choices=["adaptive", "ffmpeg"],
        default="adaptive",
        help="Silence detector backend. adaptive uses a NumPy speech-style detector and is the default.",
    )
    parser.add_argument(
        "--render-mode",
        choices=["accurate", "fast"],
        default="accurate",
        help="accurate = single-pass precise cuts; fast = concat-based render with less exact boundaries.",
    )
    parser.add_argument(
        "--fast-merge-gap",
        type=float,
        default=0.12,
        help="In fast mode, merge cuts separated by <= this many seconds to boost speed.",
    )
    parser.add_argument(
        "--accurate-merge-gap",
        type=float,
        default=0.08,
        help="In standard mode, merge tiny gaps <= this many seconds to reduce cut count and speed up rendering.",
    )
    parser.add_argument(
        "--parallel-jobs",
        type=int,
        default=1,
        help="Advanced option: split the render into worker chunks, then concat them.",
    )
    parser.add_argument(
        "--no-turbo",
        action="store_true",
        help="Disable hardware encode attempt (h264_videotoolbox).",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    settings = SilenceSettings(
        threshold_db=args.threshold_db,
        remove_silences_longer_than=args.remove_silence_longer_than,
        ignore_detections_shorter_than=args.ignore_detections_shorter_than,
        left_padding=args.left_padding,
        right_padding=args.right_padding,
    )
    started = time.monotonic()
    last_progress = {"pct": -1.0, "ts": started}

    def _cli_progress(pct: float) -> None:
        now = time.monotonic()
        pct = max(0.0, min(100.0, pct))
        if pct >= 100.0 and last_progress["pct"] >= 100.0:
            return
        if pct < 100.0 and (pct - last_progress["pct"]) < 1.5 and (now - last_progress["ts"]) < 3.0:
            return
        elapsed = now - started
        print(f"[{pct:5.1f}%] elapsed {_format_time(elapsed)}")
        last_progress["pct"] = pct
        last_progress["ts"] = now

    try:
        result = process_media(
            input_path=args.input,
            output_path=args.output,
            settings=settings,
            detector=args.detector,
            turbo=not args.no_turbo,
            render_mode=args.render_mode,
            fast_merge_gap=args.fast_merge_gap,
            accurate_merge_gap=max(0.0, args.accurate_merge_gap),
            parallel_jobs=max(1, args.parallel_jobs),
            log=_default_logger,
            cancel_event=None,
            progress=_cli_progress,
        )
    except SilenceRemoverError as exc:
        print(f"ERROR: {exc}")
        return 1

    print(
        "Done.\n"
        f"Output: {result.output_path}\n"
        f"Input duration: {_format_time(result.input_duration)}\n"
        f"Output duration: {_format_time(result.output_duration)}\n"
        f"Removed: {_format_time(result.removed_duration)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
