#!/usr/bin/env python3
from __future__ import annotations

import queue
import threading
import tkinter as tk
import json
import os
import time
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from silence_remover import ProcessResult, SilenceRemoverError, SilenceSettings, process_media


class SilentLectureRemoverApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Silent Lecture Remover")
        self.root.geometry("840x640")
        self.root.minsize(760, 560)

        self.log_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.progress_started_at = 0.0

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()

        self.threshold_var = tk.StringVar(value="-42.0")
        self.remove_longer_var = tk.StringVar(value="0.5")
        self.ignore_shorter_var = tk.StringVar(value="0.75")
        self.left_padding_var = tk.StringVar(value="0.01")
        self.right_padding_var = tk.StringVar(value="0.15")
        self.turbo_var = tk.BooleanVar(value=True)
        self.fast_mode_var = tk.BooleanVar(value=False)
        self.fast_gap_var = tk.StringVar(value="0.12")
        default_jobs = max(1, min(4, os.cpu_count() or 1))
        self.parallel_jobs_var = tk.StringVar(value=str(default_jobs))
        self.progress_text_var = tk.StringVar(value="Ready")

        self._build_ui()
        self._schedule_poll()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(
            frame,
            text="TimeBolt-style Silence Remover (No Watermark)",
            font=("Helvetica", 16, "bold"),
        )
        title.pack(anchor=tk.W, pady=(0, 12))

        file_frame = ttk.LabelFrame(frame, text="Files", padding=12)
        file_frame.pack(fill=tk.X, pady=(0, 12))

        self._file_row(file_frame, "Input Video/Audio", self.input_var, self._pick_input)
        self._file_row(file_frame, "Output Path", self.output_var, self._pick_output)

        settings_frame = ttk.LabelFrame(
            frame, text="Silence Detection Options (TimeBolt Defaults)", padding=12
        )
        settings_frame.pack(fill=tk.X, pady=(0, 12))

        self._setting_row(settings_frame, "Filter Below Sound Level (dB)", self.threshold_var)
        self._setting_row(
            settings_frame, "Remove Silences Longer Than (sec)", self.remove_longer_var
        )
        self._setting_row(
            settings_frame, "Ignore Detections Shorter Than (sec)", self.ignore_shorter_var
        )
        self._setting_row(settings_frame, "Left Padding (sec)", self.left_padding_var)
        self._setting_row(settings_frame, "Right Padding (sec)", self.right_padding_var)

        opts_frame = ttk.Frame(settings_frame)
        opts_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Checkbutton(
            opts_frame,
            text="Turbo Encode (use Apple hardware encoder if available)",
            variable=self.turbo_var,
        ).pack(anchor=tk.W)
        fast_row = ttk.Frame(opts_frame)
        fast_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Checkbutton(
            fast_row,
            text="Super Fast Mode (concat-based, less precise cuts)",
            variable=self.fast_mode_var,
        ).pack(side=tk.LEFT)
        ttk.Label(fast_row, text="Merge Gap (sec):").pack(side=tk.LEFT, padx=(12, 4))
        ttk.Entry(fast_row, textvariable=self.fast_gap_var, width=8).pack(side=tk.LEFT)
        parallel_row = ttk.Frame(opts_frame)
        parallel_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(parallel_row, text="Parallel Jobs (accurate mode):").pack(side=tk.LEFT)
        ttk.Entry(parallel_row, textvariable=self.parallel_jobs_var, width=8).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        actions = ttk.Frame(frame)
        actions.pack(fill=tk.X, pady=(0, 12))
        self.start_btn = ttk.Button(actions, text="Export Video", command=self._start)
        self.start_btn.pack(side=tk.LEFT)
        ttk.Button(actions, text="Reset Defaults", command=self._reset_defaults).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(actions, text="Load Tuned JSON", command=self._load_tuned_json).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        self.progress = ttk.Progressbar(frame, orient=tk.HORIZONTAL, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(frame, textvariable=self.progress_text_var).pack(anchor=tk.W, pady=(0, 8))

        log_frame = ttk.LabelFrame(frame, text="Log", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(log_frame, height=12, wrap="word")
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.configure(state=tk.DISABLED)

    def _file_row(
        self, parent: ttk.LabelFrame, label: str, variable: tk.StringVar, on_pick: callable
    ) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text=label, width=18).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=variable).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        ttk.Button(row, text="Browse", command=on_pick).pack(side=tk.LEFT)

    def _setting_row(self, parent: ttk.LabelFrame, label: str, variable: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text=label, width=38).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=variable, width=14).pack(side=tk.LEFT)

    def _pick_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Input",
            filetypes=[
                ("Media files", "*.mp4 *.mkv *.mov *.avi *.mp3 *.m4a *.wav"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self.input_var.set(path)
        self.output_var.set(self._default_output(path))

    def _pick_output(self) -> None:
        chosen = filedialog.asksaveasfilename(
            title="Select Output",
            initialfile=Path(self.output_var.get()).name if self.output_var.get() else None,
            defaultextension=".mp4",
            filetypes=[("MP4 Video", "*.mp4"), ("All files", "*.*")],
        )
        if chosen:
            self.output_var.set(chosen)

    @staticmethod
    def _default_output(input_path: str) -> str:
        src = Path(input_path)
        suffix = src.suffix if src.suffix else ".mp4"
        return str(src.with_name(f"{src.stem}_silentcut{suffix}"))

    def _reset_defaults(self) -> None:
        self.threshold_var.set("-42.0")
        self.remove_longer_var.set("0.5")
        self.ignore_shorter_var.set("0.75")
        self.left_padding_var.set("0.01")
        self.right_padding_var.set("0.15")
        self.turbo_var.set(True)
        self.fast_mode_var.set(False)
        self.fast_gap_var.set("0.12")
        self.parallel_jobs_var.set(str(max(1, min(4, os.cpu_count() or 1))))
        self._append_log("Reset to TimeBolt-style defaults.")
        self.progress_text_var.set("Ready")

    def _load_tuned_json(self) -> None:
        path = filedialog.askopenfilename(
            title="Load tuned settings JSON",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.threshold_var.set(str(float(data["threshold_db"])))
            self.remove_longer_var.set(str(float(data["remove_silences_longer_than"])))
            self.ignore_shorter_var.set(str(float(data["ignore_detections_shorter_than"])))
            self.left_padding_var.set(str(float(data["left_padding"])))
            self.right_padding_var.set(str(float(data["right_padding"])))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Invalid JSON", f"Could not load settings: {exc}")
            return
        self._append_log(f"Loaded tuned settings from {path}")

    def _append_log(self, line: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, f"{line}\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _parse_settings(self) -> SilenceSettings:
        try:
            return SilenceSettings(
                threshold_db=float(self.threshold_var.get()),
                remove_silences_longer_than=float(self.remove_longer_var.get()),
                ignore_detections_shorter_than=float(self.ignore_shorter_var.get()),
                left_padding=float(self.left_padding_var.get()),
                right_padding=float(self.right_padding_var.get()),
            )
        except ValueError as exc:
            raise SilenceRemoverError(f"Invalid numeric setting: {exc}") from exc

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("In Progress", "An export is already running.")
            return

        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()
        if not input_path:
            messagebox.showerror("Missing Input", "Select an input file.")
            return
        if not output_path:
            output_path = self._default_output(input_path)
            self.output_var.set(output_path)

        try:
            settings = self._parse_settings()
        except SilenceRemoverError as exc:
            messagebox.showerror("Invalid Settings", str(exc))
            return
        turbo = self.turbo_var.get()
        render_mode = "fast" if self.fast_mode_var.get() else "accurate"
        try:
            fast_merge_gap = float(self.fast_gap_var.get())
        except ValueError:
            messagebox.showerror("Invalid Fast Mode Gap", "Merge Gap must be a number.")
            return
        try:
            parallel_jobs = int(self.parallel_jobs_var.get())
            if parallel_jobs < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Parallel Jobs", "Parallel Jobs must be an integer >= 1.")
            return

        self.progress["value"] = 0.0
        self.progress_started_at = time.monotonic()
        self.progress_text_var.set("Starting...")
        self._append_log("-" * 60)
        self._append_log(f"Input: {input_path}")
        self._append_log(f"Output: {output_path}")
        self._append_log(f"Mode: {render_mode}")
        self._append_log(f"Parallel jobs: {parallel_jobs}")
        self._set_busy(True)

        self.worker = threading.Thread(
            target=self._run_export,
            args=(
                input_path,
                output_path,
                settings,
                turbo,
                render_mode,
                fast_merge_gap,
                parallel_jobs,
            ),
            daemon=True,
        )
        self.worker.start()

    def _set_busy(self, busy: bool) -> None:
        self.start_btn.configure(state=tk.DISABLED if busy else tk.NORMAL)

    def _run_export(
        self,
        input_path: str,
        output_path: str,
        settings: SilenceSettings,
        turbo: bool,
        render_mode: str,
        fast_merge_gap: float,
        parallel_jobs: int,
    ) -> None:
        try:
            result = process_media(
                input_path=input_path,
                output_path=output_path,
                settings=settings,
                turbo=turbo,
                render_mode=render_mode,
                fast_merge_gap=fast_merge_gap,
                parallel_jobs=parallel_jobs,
                log=lambda msg: self.log_queue.put(("log", msg)),
                progress=lambda pct: self.log_queue.put(("progress", pct)),
            )
            self.log_queue.put(("done", result))
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(("error", exc))

    def _schedule_poll(self) -> None:
        self._poll_queue()
        self.root.after(100, self._schedule_poll)

    def _poll_queue(self) -> None:
        while True:
            try:
                event, payload = self.log_queue.get_nowait()
            except queue.Empty:
                return

            if event == "log":
                self._append_log(str(payload))
            elif event == "progress":
                pct = float(payload)
                self.progress["value"] = pct
                elapsed = max(0.0, time.monotonic() - self.progress_started_at)
                if pct <= 0.0:
                    self.progress_text_var.set("Starting...")
                elif pct >= 100.0:
                    self.progress_text_var.set(f"100.0% | elapsed {elapsed:.0f}s")
                else:
                    eta = (elapsed * (100.0 - pct)) / max(pct, 0.001)
                    self.progress_text_var.set(
                        f"{pct:5.1f}% | ETA ~{eta:.0f}s | elapsed {elapsed:.0f}s"
                    )
            elif event == "done":
                self._set_busy(False)
                assert isinstance(payload, ProcessResult)
                self.progress["value"] = 100.0
                elapsed = max(0.0, time.monotonic() - self.progress_started_at)
                self.progress_text_var.set(f"Done in {elapsed:.1f}s")
                self._append_log(
                    f"Done. Output duration: {payload.output_duration:.2f}s "
                    f"(removed {payload.removed_duration:.2f}s)"
                )
                messagebox.showinfo("Completed", f"Export completed:\n{payload.output_path}")
            elif event == "error":
                self._set_busy(False)
                self.progress["value"] = 0.0
                self.progress_text_var.set("Failed")
                self._append_log(f"ERROR: {payload}")
                messagebox.showerror("Export Failed", str(payload))


def main() -> None:
    root = tk.Tk()
    app = SilentLectureRemoverApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
