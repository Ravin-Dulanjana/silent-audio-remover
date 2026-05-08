# Silent Lecture Remover

Silent Lecture Remover is a local Python app for trimming silence from lecture videos and audio recordings without adding watermarks. It was built as a practical alternative to tools like TimeBolt for students and anyone who wants faster, cleaner lecture playback.

The project includes:

- a desktop GUI built with `tkinter`
- a CLI for batch-style usage
- tunable silence-detection settings
- live progress percentage and ETA
- parallel rendering for faster accurate exports
- a calibration tool for matching a reference output

## Why this project exists

Many silence-removal tools are convenient, but free versions often watermark exported videos. This project focuses on keeping the workflow local and simple:

- select a lecture file
- detect silent parts
- export a shorter version without watermarking

It is especially useful for:

- recorded lectures
- screen captures with pauses
- tutorials with dead air
- spoken audio where silence should be reduced

## Features

- Watermark-free local processing
- Desktop app with file picker and editable detection settings
- CLI for scripting and repeatable runs
- Live progress reporting with ETA
- Accurate mode for precise cuts
- Parallel accurate mode for better speed on multi-core machines
- Fast mode for quicker but less exact cut timing
- Calibration utility to tune settings against a reference output
- JSON import for tuned settings in the GUI

## Default settings

The default detection values were chosen to mirror the TimeBolt-style setup used during development:

- `Filter Below Sound Level`: `-42.0 dB`
- `Remove Silences Longer Than`: `0.5 sec`
- `Ignore Detections Shorter Than`: `0.75 sec`
- `Left Padding`: `0.01 sec`
- `Right Padding`: `0.15 sec`

These are a reasonable starting point for lecture recordings, but you can tune them for noisier or quieter material.

## Requirements

- Python `3.10+`
- `ffmpeg`
- `ffprobe`

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/silent-lecture-remover.git
cd silent-lecture-remover
```

### 2. Install FFmpeg

#### macOS

```bash
brew install ffmpeg
```

#### Ubuntu / Debian

```bash
sudo apt update
sudo apt install ffmpeg
```

#### Windows

Install FFmpeg and make sure both `ffmpeg` and `ffprobe` are available in your `PATH`.

### 3. Verify the setup

```bash
python3 silence_remover.py --help
python3 calibrate_to_reference.py --help
```

## Quick start

### Launch the desktop app

```bash
python3 app.py
```

From the app you can:

- choose an input video or audio file
- choose an output path
- edit silence-detection settings
- use parallel rendering for faster accurate exports
- load tuned settings from a JSON file
- watch live progress and ETA

### Run from the CLI

```bash
python3 silence_remover.py input.mp4 output.mp4
```

## CLI usage

Basic example:

```bash
python3 silence_remover.py lecture.mp4 lecture_trimmed.mp4
```

Use custom silence settings:

```bash
python3 silence_remover.py lecture.mp4 lecture_trimmed.mp4 \
  --threshold-db -42 \
  --remove-silence-longer-than 0.5 \
  --ignore-detections-shorter-than 0.75 \
  --left-padding 0.01 \
  --right-padding 0.15
```

Disable hardware encode fallback attempts:

```bash
python3 silence_remover.py lecture.mp4 lecture_trimmed.mp4 --no-turbo
```

Use accurate mode with parallel workers:

```bash
python3 silence_remover.py lecture.mp4 lecture_trimmed.mp4 \
  --render-mode accurate \
  --parallel-jobs 4 \
  --no-turbo
```

Use fast mode:

```bash
python3 silence_remover.py lecture.mp4 lecture_trimmed_fast.mp4 \
  --render-mode fast \
  --fast-merge-gap 0.12 \
  --no-turbo
```

### CLI arguments

- `input`: input media file
- `output`: output media file
- `--threshold-db`: silence threshold in dB
- `--remove-silence-longer-than`: minimum silence duration to detect
- `--ignore-detections-shorter-than`: minimum speech segment length to keep
- `--left-padding`: audio/video padding before kept speech
- `--right-padding`: audio/video padding after kept speech
- `--render-mode accurate|fast`: choose between precision and speed
- `--fast-merge-gap`: merge nearby cuts in fast mode
- `--parallel-jobs`: number of workers for accurate parallel rendering
- `--no-turbo`: disable hardware encoder attempts

## GUI usage

The desktop app in [app.py](/Users/ravinfernando/dev/silent-audio-remover/app.py) is the easiest way to use the project.

### Main controls

- `Input Video/Audio`: the lecture or recording to process
- `Output Path`: destination file
- `Filter Below Sound Level`: silence threshold
- `Remove Silences Longer Than`: minimum silence duration to remove
- `Ignore Detections Shorter Than`: minimum non-silence duration to preserve
- `Left Padding` / `Right Padding`: padding around preserved speech
- `Turbo Encode`: attempts hardware encoding where possible
- `Super Fast Mode`: faster but less exact output timing
- `Parallel Jobs`: concurrent accurate rendering workers

### Progress display

The app shows:

- current completion percentage
- estimated time remaining
- elapsed processing time
- log messages for each stage

## Performance notes

There are two main rendering modes:

### Accurate mode

- Best choice for lecture videos
- Re-encodes the output for precise cuts
- Supports `--parallel-jobs` to speed up long exports

Recommended:

```bash
python3 silence_remover.py lecture.mp4 lecture_trimmed.mp4 --parallel-jobs 4 --no-turbo
```

### Fast mode

- Tries to reduce render overhead
- Cut timing can be less exact around boundaries
- Better when speed matters more than precise edit points

### Recommended practical defaults

For most users:

- keep `accurate` mode
- set `parallel-jobs` to `2` or `4`
- use `--no-turbo` if hardware encoding is unreliable on your machine

## Calibration against a reference output

If you already have a reference file, such as a TimeBolted version of the same lecture, you can auto-tune settings to get closer to that output.

### Generate tuned settings

```bash
python3 calibrate_to_reference.py original.mp4 reference.mp4 --save-json tuned_settings.json
```

### Render with tuned settings

```bash
python3 calibrate_to_reference.py original.mp4 reference.mp4 \
  --save-json tuned_settings.json \
  --render-output matched_output.mp4
```

### Load tuned settings in the GUI

Use the `Load Tuned JSON` button and select the generated `tuned_settings.json`.

## Project structure

- [app.py](/Users/ravinfernando/dev/silent-audio-remover/app.py): desktop GUI
- [silence_remover.py](/Users/ravinfernando/dev/silent-audio-remover/silence_remover.py): core processing engine and CLI
- [calibrate_to_reference.py](/Users/ravinfernando/dev/silent-audio-remover/calibrate_to_reference.py): reference-based tuning utility
- [test_segments.py](/Users/ravinfernando/dev/silent-audio-remover/test_segments.py): tests for segment calculation logic

## Testing

Run the test suite:

```bash
pytest -q
```

You can also verify the scripts compile:

```bash
python3 -m py_compile silence_remover.py app.py calibrate_to_reference.py test_segments.py
```

## Known limitations

- It is designed for local desktop usage, not cloud processing.
- Exact output will not be byte-for-byte identical to TimeBolt.
- Hardware encoding support depends on the machine and FFmpeg build.
- Fast mode trades precision for speed.
- Very noisy audio may need custom threshold tuning.

## GitHub repo suggestions

### Suggested repository description

Watermark-free Python app to remove silence from lecture videos with a GUI, CLI, progress ETA, and parallel processing.

### Suggested topics

- `python`
- `ffmpeg`
- `video-editing`
- `audio-processing`
- `silence-removal`
- `lecture-tools`
- `tkinter`

## License

Add the license you want before publishing. If you want a simple default, MIT is usually a good fit for a utility project like this.
