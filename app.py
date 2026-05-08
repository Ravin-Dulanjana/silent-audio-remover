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

from silence_remover import (
    ProcessResult,
    ProcessingCancelled,
    SilenceRemoverError,
    SilenceSettings,
    process_media,
)


class SilenceRemoverApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Silence Remover")
        self.root.geometry("920x860")
        self.root.minsize(860, 720)

        self.log_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_event: threading.Event | None = None
        self.progress_started_at = 0.0

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()

        self.threshold_var = tk.StringVar(value="-38.0")
        self.remove_longer_var = tk.StringVar(value="0.5")
        self.ignore_shorter_var = tk.StringVar(value="0.85")
        self.left_padding_var = tk.StringVar(value="0.01")
        self.right_padding_var = tk.StringVar(value="0.15")
        self.detector_var = tk.StringVar(value="adaptive")
        self.turbo_var = tk.BooleanVar(value=True)
        self.fast_mode_var = tk.BooleanVar(value=False)
        self.fast_gap_var = tk.StringVar(value="0.12")
        self.accurate_merge_gap_var = tk.StringVar(value="0.08")
        self.parallel_jobs_var = tk.StringVar(value="1")
        self.progress_text_var = tk.StringVar(value="Ready")
        self.current_status = "Ready"

        self._configure_styles()
        self._build_ui()
        self._bind_shortcuts()
        self._activate_window()
        self._schedule_poll()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            if "aqua" in style.theme_names():
                style.theme_use("aqua")
        except tk.TclError:
            pass

        style.configure("Card.TLabelframe", padding=12)
        style.configure("Card.TLabelframe.Label", font=("Helvetica", 11, "bold"))
        style.configure("Title.TLabel", font=("Helvetica", 16, "bold"))
        style.configure("Action.TButton", padding=(16, 10), font=("Helvetica", 12, "bold"))
        style.configure("Stop.TButton", padding=(16, 10), font=("Helvetica", 12, "bold"))
        style.configure("Secondary.TButton", padding=(12, 9), font=("Helvetica", 11))
        style.configure("Browse.TButton", padding=(12, 8), font=("Helvetica", 11))
        style.configure("Wide.TEntry", padding=(8, 7))
        style.configure("Wide.TCombobox", padding=(6, 6))
        style.configure("TCheckbutton", padding=(2, 4))

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Return>", lambda _event: self._start())
        self.root.bind("<KP_Enter>", lambda _event: self._start())
        self.root.bind("<Command-Return>", lambda _event: self._start())

    def _activate_window(self) -> None:
        def _activate() -> None:
            try:
                self.root.deiconify()
                self.root.lift()
                self.root.attributes("-topmost", True)
                self.root.focus_force()
                self.root.after(150, lambda: self.root.attributes("-topmost", False))
            except tk.TclError:
                pass

        self.root.after(100, _activate)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.content = ttk.Frame(self.canvas, padding=8)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mousewheel(self.canvas)
        self._bind_mousewheel(self.content)

        title = ttk.Label(
            self.content,
            text="Silence Remover",
            style="Title.TLabel",
        )
        title.pack(anchor=tk.W, pady=(0, 12))

        file_frame = ttk.LabelFrame(self.content, text="Files", style="Card.TLabelframe")
        file_frame.pack(fill=tk.X, pady=(0, 12))

        self._file_row(file_frame, "Input Video/Audio", self.input_var, self._pick_input)
        self._file_row(file_frame, "Output Path", self.output_var, self._pick_output)

        settings_frame = ttk.LabelFrame(
            self.content, text="Silence Detection Options", style="Card.TLabelframe"
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
        detector_row = ttk.Frame(settings_frame)
        detector_row.pack(fill=tk.X, pady=4)
        ttk.Label(detector_row, text="Detector", width=38).pack(side=tk.LEFT)
        detector_box = ttk.Combobox(
            detector_row,
            textvariable=self.detector_var,
            values=("adaptive", "ffmpeg"),
            state="readonly",
            width=12,
            style="Wide.TCombobox",
        )
        detector_box.pack(side=tk.LEFT)
        self._make_widget_easy_to_focus(detector_box)

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
            text="Concat Mode (faster, less precise boundaries)",
            variable=self.fast_mode_var,
        ).pack(side=tk.LEFT)
        ttk.Label(fast_row, text="Merge Gap (sec):").pack(side=tk.LEFT, padx=(12, 4))
        ttk.Entry(fast_row, textvariable=self.fast_gap_var, width=8).pack(side=tk.LEFT)
        parallel_row = ttk.Frame(opts_frame)
        parallel_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(parallel_row, text="Parallel Jobs (advanced):").pack(side=tk.LEFT)
        ttk.Entry(parallel_row, textvariable=self.parallel_jobs_var, width=8).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        merge_row = ttk.Frame(opts_frame)
        merge_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(merge_row, text="Standard Merge Gap (sec):").pack(side=tk.LEFT)
        ttk.Entry(merge_row, textvariable=self.accurate_merge_gap_var, width=8).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        actions = ttk.Frame(self.content)
        actions.pack(fill=tk.X, pady=(0, 12))
        self.start_btn = ttk.Button(
            actions, text="Export Video", command=self._start, style="Action.TButton", default="active"
        )
        self.start_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(
            actions, text="Stop", command=self._request_stop, style="Stop.TButton", state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            actions, text="Reset Defaults", command=self._reset_defaults, style="Secondary.TButton"
        ).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(
            actions, text="Load Tuned JSON", command=self._load_tuned_json, style="Secondary.TButton"
        ).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        self.progress = ttk.Progressbar(self.content, orient=tk.HORIZONTAL, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(self.content, textvariable=self.progress_text_var).pack(anchor=tk.W, pady=(0, 8))

        log_frame = ttk.LabelFrame(self.content, text="Log", style="Card.TLabelframe")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.log = tk.Text(log_frame, height=12, wrap="word")
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.configure(state=tk.DISABLED)
        self._bind_mousewheel(self.log)

    def _on_content_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.canvas_window, width=event.width)

    def _bind_mousewheel(self, widget: tk.Widget) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
        widget.bind("<Shift-MouseWheel>", self._on_shift_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_mousewheel_linux_up, add="+")
        widget.bind("<Button-5>", self._on_mousewheel_linux_down, add="+")

    def _on_mousewheel(self, event: tk.Event) -> str:
        delta = getattr(event, "delta", 0)
        if delta:
            step = -1 * int(delta / 120 if abs(delta) >= 120 else (1 if delta > 0 else -1))
            self.canvas.yview_scroll(step, "units")
        return "break"

    def _on_shift_mousewheel(self, event: tk.Event) -> str:
        delta = getattr(event, "delta", 0)
        if delta:
            step = -1 * int(delta / 120 if abs(delta) >= 120 else (1 if delta > 0 else -1))
            self.canvas.xview_scroll(step, "units")
        return "break"

    def _on_mousewheel_linux_up(self, _event: tk.Event) -> str:
        self.canvas.yview_scroll(-1, "units")
        return "break"

    def _on_mousewheel_linux_down(self, _event: tk.Event) -> str:
        self.canvas.yview_scroll(1, "units")
        return "break"

    def _file_row(
        self, parent: ttk.LabelFrame, label: str, variable: tk.StringVar, on_pick: callable
    ) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=6)
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text=label, width=18).grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(row, textvariable=variable, style="Wide.TEntry")
        entry.grid(row=0, column=1, sticky="ew", padx=(10, 10))
        self._make_widget_easy_to_focus(entry)
        ttk.Button(row, text="Browse", command=on_pick, style="Browse.TButton", width=10).grid(
            row=0, column=2, sticky="e"
        )

    def _setting_row(self, parent: ttk.LabelFrame, label: str, variable: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=5)
        ttk.Label(row, text=label, width=38).pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=variable, width=16, style="Wide.TEntry")
        entry.pack(side=tk.LEFT, padx=(8, 0))
        self._make_widget_easy_to_focus(entry)

    def _make_widget_easy_to_focus(self, widget: tk.Widget) -> None:
        widget.bind("<Button-1>", lambda _event: widget.focus_set(), add="+")
        widget.bind("<FocusIn>", lambda _event: self._select_all_if_text_widget(widget), add="+")

    @staticmethod
    def _select_all_if_text_widget(widget: tk.Widget) -> None:
        if isinstance(widget, ttk.Entry):
            widget.selection_range(0, tk.END)
            widget.icursor(tk.END)

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
        self.threshold_var.set("-38.0")
        self.remove_longer_var.set("0.5")
        self.ignore_shorter_var.set("0.85")
        self.left_padding_var.set("0.01")
        self.right_padding_var.set("0.15")
        self.detector_var.set("adaptive")
        self.turbo_var.set(True)
        self.fast_mode_var.set(False)
        self.fast_gap_var.set("0.12")
        self.accurate_merge_gap_var.set("0.08")
        self.parallel_jobs_var.set("1")
        self._append_log("Reset to default values.")
        self.progress_text_var.set("Ready")
        self.current_status = "Ready"

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
        detector = self.detector_var.get().strip() or "adaptive"
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
        try:
            accurate_merge_gap = float(self.accurate_merge_gap_var.get())
            if accurate_merge_gap < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Invalid Standard Merge Gap",
                "Standard Merge Gap must be a number >= 0.",
            )
            return

        self.progress["value"] = 0.0
        self.progress_started_at = time.monotonic()
        self.progress_text_var.set("Starting...")
        self.current_status = "Starting..."
        self.cancel_event = threading.Event()
        self._append_log("-" * 60)
        self._append_log(f"Input: {input_path}")
        self._append_log(f"Output: {output_path}")
        self._append_log(f"Detector: {detector}")
        self._append_log(f"Mode: {render_mode}")
        self._append_log(f"Parallel jobs: {parallel_jobs}")
        self._append_log(f"Standard merge gap: {accurate_merge_gap:.2f}s")
        self._set_busy(True)

        self.worker = threading.Thread(
            target=self._run_export,
            args=(
                input_path,
                output_path,
                settings,
                detector,
                turbo,
                render_mode,
                fast_merge_gap,
                accurate_merge_gap,
                parallel_jobs,
            ),
            daemon=True,
        )
        self.worker.start()

    def _set_busy(self, busy: bool) -> None:
        self.start_btn.configure(state=tk.DISABLED if busy else tk.NORMAL)
        self.stop_btn.configure(state=tk.NORMAL if busy else tk.DISABLED)

    def _request_stop(self) -> None:
        if self.cancel_event is None or not (self.worker and self.worker.is_alive()):
            return
        if not self.cancel_event.is_set():
            self.cancel_event.set()
            self.current_status = "Stopping..."
            self.progress_text_var.set("Stopping...")
            self._append_log("Stopping current export...")
            self.stop_btn.configure(state=tk.DISABLED)

    def _run_export(
        self,
        input_path: str,
        output_path: str,
        settings: SilenceSettings,
        detector: str,
        turbo: bool,
        render_mode: str,
        fast_merge_gap: float,
        accurate_merge_gap: float,
        parallel_jobs: int,
    ) -> None:
        try:
            result = process_media(
                input_path=input_path,
                output_path=output_path,
                settings=settings,
                detector=detector,
                turbo=turbo,
                render_mode=render_mode,
                fast_merge_gap=fast_merge_gap,
                accurate_merge_gap=accurate_merge_gap,
                parallel_jobs=parallel_jobs,
                log=lambda msg: self.log_queue.put(("log", msg)),
                cancel_event=self.cancel_event,
                progress=lambda pct: self.log_queue.put(("progress", pct)),
            )
            self.log_queue.put(("done", result))
        except ProcessingCancelled:
            self.log_queue.put(("cancelled", None))
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(("error", exc))

    def _schedule_poll(self) -> None:
        self._poll_queue()
        self.root.after(25, self._schedule_poll)

    def _poll_queue(self) -> None:
        while True:
            try:
                event, payload = self.log_queue.get_nowait()
            except queue.Empty:
                return

            if event == "log":
                message = str(payload)
                self.current_status = message
                self._append_log(message)
            elif event == "progress":
                pct = float(payload)
                self.progress["value"] = pct
                elapsed = max(0.0, time.monotonic() - self.progress_started_at)
                if pct <= 0.0:
                    self.progress_text_var.set(self.current_status)
                elif pct >= 100.0:
                    self.progress_text_var.set(f"100.0% | elapsed {elapsed:.0f}s")
                else:
                    self.progress_text_var.set(
                        f"{pct:5.1f}% | {self.current_status} | elapsed {elapsed:.0f}s"
                    )
            elif event == "done":
                self._set_busy(False)
                self.cancel_event = None
                assert isinstance(payload, ProcessResult)
                self.progress["value"] = 100.0
                elapsed = max(0.0, time.monotonic() - self.progress_started_at)
                self.progress_text_var.set(f"Done in {elapsed:.1f}s")
                self._append_log(
                    f"Done. Output duration: {payload.output_duration:.2f}s "
                    f"(removed {payload.removed_duration:.2f}s)"
                )
                messagebox.showinfo("Completed", f"Export completed:\n{payload.output_path}")
            elif event == "cancelled":
                self._set_busy(False)
                self.cancel_event = None
                self.progress["value"] = 0.0
                self.progress_text_var.set("Stopped")
                self.current_status = "Stopped"
                self._append_log("Export stopped.")
            elif event == "error":
                self._set_busy(False)
                self.cancel_event = None
                self.progress["value"] = 0.0
                self.progress_text_var.set("Failed")
                self._append_log(f"ERROR: {payload}")
                messagebox.showerror("Export Failed", str(payload))


def main() -> None:
    root = tk.Tk()
    app = SilenceRemoverApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
