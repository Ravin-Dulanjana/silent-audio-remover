# Silence Remover

Silence Remover is a local Python app for trimming silence from video and audio recordings without adding watermarks. It was built as a practical alternative to tools like TimeBolt for anyone who wants faster, cleaner playback while keeping the workflow fully local.

The project includes:

- a desktop GUI built with `tkinter`
- a CLI for batch-style usage
- tunable silence-detection settings
- live progress percentage and active processing status
- fast single-pass rendering for precise exports
- an adaptive speech-style detector for stronger silence removal
- a stop button for cancelling active exports
- a calibration tool for matching a reference output

## Why this project exists

Many silence-removal tools are convenient, but free versions often watermark exported videos. This project focuses on keeping the workflow local and simple:

- select a media file
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
- Live progress reporting with active processing status
- Standard mode for precise cuts
- Optional parallel chunk rendering for advanced cases
- Concat mode for quicker but less exact cut timing
- Adaptive detector as the default backend
- Calibration utility to tune settings against a reference output
- JSON import for tuned settings in the GUI

## Default settings

The default detection values were chosen to mirror the TimeBolt-style setup used during development:

- `Filter Below Sound Level`: `-38.0 dB`
- `Remove Silences Longer Than`: `0.5 sec`
- `Ignore Detections Shorter Than`: `0.85 sec`
- `Left Padding`: `0.01 sec`
- `Right Padding`: `0.15 sec`
- `Detector`: `adaptive`

These are a reasonable starting point for spoken-content recordings, but you can tune them for noisier or quieter material.

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
- use the default fast single-pass renderer
- use the adaptive detector by default
- stop an export that is already running
- load tuned settings from a JSON file
- watch live progress and current processing stage

### Run from the CLI

```bash
python3 silence_remover.py input.mp4 output.mp4
```

## CLI usage

Basic example:

```bash
python3 silence_remover.py input.mp4 trimmed.mp4
```

Use custom silence settings:

```bash
python3 silence_remover.py input.mp4 trimmed.mp4 \
  --threshold-db -38 \
  --remove-silence-longer-than 0.5 \
  --ignore-detections-shorter-than 0.85 \
  --left-padding 0.01 \
  --right-padding 0.15
```

Disable hardware encode fallback attempts:

```bash
python3 silence_remover.py input.mp4 trimmed.mp4 --no-turbo
```

Use the default standard mode:

```bash
python3 silence_remover.py input.mp4 trimmed.mp4 --no-turbo
```

Use concat mode:

```bash
python3 silence_remover.py input.mp4 trimmed_fast.mp4 \
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
- `--detector adaptive|ffmpeg`: choose the detection backend
- `--render-mode accurate|fast`: choose between the default single-pass renderer and concat mode
- `--fast-merge-gap`: merge nearby cuts in fast mode
- `--parallel-jobs`: advanced worker count for chunked rendering
- `--no-turbo`: disable hardware encoder attempts

## GUI usage

The desktop app in [app.py](/Users/ravinfernando/dev/silent-audio-remover/app.py) is the easiest way to use the project.

### Main controls

- `Input Video/Audio`: the media file to process
- `Output Path`: destination file
- `Filter Below Sound Level`: silence threshold
- `Remove Silences Longer Than`: minimum silence duration to remove
- `Ignore Detections Shorter Than`: minimum non-silence duration to preserve
- `Left Padding` / `Right Padding`: padding around preserved speech
- `Detector`: adaptive is the default and usually removes more silence
- `Turbo Encode`: attempts hardware encoding where possible
- `Concat Mode`: faster but less exact output timing
- `Parallel Jobs`: advanced chunk rendering workers
- `Stop`: cancels the active export and cleans up partial output

### Progress display

The app shows:

- current completion percentage
- current processing stage
- elapsed processing time
- log messages for each stage

## Performance notes

There are two main rendering modes:

### Standard mode

- Best choice for most files
- Uses a single-pass FFmpeg selection render for precise cuts
- Pairs well with the default adaptive detector for stronger silence trimming
- Usually faster than the older chunked render path
- Supports `--parallel-jobs` as an advanced option, though it can be slower on some machines

Recommended:

```bash
python3 silence_remover.py input.mp4 trimmed.mp4 --no-turbo
```

### Concat mode

- Tries to reduce render overhead
- Cut timing can be less exact around boundaries
- Better when speed matters more than precise edit points

### Recommended practical defaults

For most users:

- keep `accurate` mode
- keep `adaptive` detector
- leave `parallel-jobs` at `1` unless you have tested a benefit on your machine
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
- [packaging/build_mac.sh](/Users/ravinfernando/dev/silent-audio-remover/packaging/build_mac.sh): macOS standalone app build script
- [packaging/build_windows.bat](/Users/ravinfernando/dev/silent-audio-remover/packaging/build_windows.bat): Windows standalone app build script
- [packaging/generate_icons.py](/Users/ravinfernando/dev/silent-audio-remover/packaging/generate_icons.py): generates the packaged app icons
- [packaging/requirements-build.txt](/Users/ravinfernando/dev/silent-audio-remover/packaging/requirements-build.txt): build dependency list
- [packaging/version.txt](/Users/ravinfernando/dev/silent-audio-remover/packaging/version.txt): packaged app version number

## Standalone app builds

You can package the GUI as a standalone desktop app with `PyInstaller`.

### Install build dependency

```bash
pip install -r packaging/requirements-build.txt
```

### Build macOS app and DMG

```bash
bash packaging/build_mac.sh
```

This produces:

```text
dist/Silence Remover.app
dist/Silence-Remover-macOS-v0.1.0.dmg
```

The macOS build script also:

- generates the app icon automatically
- embeds version metadata from `packaging/version.txt`
- sets the macOS bundle identifier
- creates a distributable `.dmg`

### Build Windows app

Run this on a Windows machine:

```bat
packaging\build_windows.bat
```

This produces a Windows standalone app build under:

```text
dist\Silence Remover\
```

The Windows build script also generates an icon and version metadata for the packaged executable.

Note: the Windows standalone app path is included for users, but it has not been tested by the project author yet.

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

Watermark-free Python app to remove silence from video and audio files with a GUI, CLI, live progress, and fast local processing.

### Suggested topics

- `python`
- `ffmpeg`
- `video-editing`
- `audio-processing`
- `silence-removal`
- `media-tools`
- `tkinter`

## License

This project is licensed under the Apache License 2.0. See [LICENSE](/Users/ravinfernando/dev/silent-audio-remover/LICENSE) for details.
