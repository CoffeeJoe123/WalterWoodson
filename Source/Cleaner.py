"""
TheCleaner.py
WoodPile Cleaner
Version: 2.0.2
Date: 2026-07-22

Purpose
-------
Convert curated source media into the current WoodPile Standard and produce
evidence strong enough for the operator to decide whether the result belongs
in the archive.

Current WoodPile defaults
-------------------------
- H.264/x264 High Profile, 8-bit yuv420p
- 1650 kb/s average video bitrate
- one-pass
- preset=fast
- no tune
- bicubic scaling
- AAC LC stereo, 192 kb/s total, 48 kHz
- English subtitles retained automatically
- ordinary subtitle title absent; SDH title exactly "SDH"
- source moved to orig only after trustworthy output has been promoted

Decision record
---------------
The 1650 kb/s, one-pass, fast standard was selected after testing showed that
slow two-pass encoding did not improve quality, deviation, or file size enough
to justify the additional runtime. One-pass fast reduced encode time by about
78%. The bitrate also provides deliberate headroom: ordinary one-pass variation
may be slightly less compression-efficient, but is not expected to push the
result below the intended archive-quality floor.

Verification philosophy
-----------------------
PASS does not mean "FFmpeg exited successfully." PASS means every required
structural check completed without uncertainty.

WARN means a usable output was produced and retained, but the evidence deserves
operator review.

FAIL means Cleaner could not produce and promote a trustworthy output. The
source remains untouched.

The top pane is a persistent batch ledger. The bottom pane is detailed evidence.
The operator should eventually be able to trust PASS and investigate only WARN
or FAIL.

Woodchipper rule
----------------
Ordinary oddness should be handled, not debated. Cleaner assumes success,
continues whenever safe, reports uncertainty honestly, and stops only when
continuing would violate transaction safety or create an untrustworthy archive.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Iterable

APP_VERSION = "2.0.2"
APP_DATE = "2026-07-22"

VIDEO_EXTS = {
    ".mkv", ".mp4", ".avi", ".mov", ".m4v",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".webm",
}
AUDIO_BITRATE_KBPS = 192
DEFAULT_VIDEO_BITRATE_KBPS = 1650
PRESETS = ("fast", "medium", "slow")
PASS_MODES = ("One-pass", "Two-pass")
SCALERS = {
    "Bicubic": "bicubic",
    "Lanczos": "lanczos",
    "Spline": "spline",
    "Bilinear": "bilinear",
}
TUNES = {
    "Normal / no tune": "",
    "Film": "film",
    "Animation": "animation",
    "Grainy source": "grain",
}

DURATION_TOLERANCE_SECONDS = 2.0
MIN_OUTPUT_MIB = 25.0
WARN_GAP_SECONDS = 2.0
FAIL_GAP_SECONDS = 10.0
AUDIO_WARN_GAP_SECONDS = 2.0
AUDIO_FAIL_GAP_SECONDS = 10.0
LOG_NAME = "TheCleaner.log"

TECH_TOKENS = {
    "480p", "576p", "720p", "1080p", "1080i", "2160p", "4k", "uhd",
    "bluray", "blu-ray", "bdrip", "brrip", "webrip", "web-dl", "webdl",
    "hdtv", "dvdrip", "remux", "proper", "repack", "internal",
    "x264", "h264", "avc", "x265", "h265", "hevc", "10bit", "8bit",
    "hdr", "hdr10", "dv", "dolbyvision", "aac", "ac3", "eac3", "dd",
    "ddp", "dts", "truehd", "atmos", "5.1", "7.1", "2.0", "stereo",
}
SDH_MARKERS = ("sdh", "hearing impaired", "hearing-impaired", "hoh", "cc")
ENGLISH_CODES = {"eng", "en", "english"}


@dataclass
class SubtitleSelection:
    source_index: int
    language: str
    is_sdh: bool
    codec_name: str


@dataclass
class SourceInfo:
    duration: float
    audio_language: str
    subtitles: list[SubtitleSelection]
    has_chapters: bool
    width: int
    height: int
    video_codec: str
    audio_codec: str


@dataclass
class ContinuityReport:
    selector: str
    packet_count: int = 0
    largest_gap: float = 0.0
    gap_start: float | None = None
    gap_end: float | None = None
    backward_steps: int = 0
    backward_events: list[tuple[int, float, float, float]] = field(default_factory=list)
    first_pts: float | None = None
    last_pts: float | None = None


@dataclass
class VerificationReport:
    status: str = "PASS"
    reasons: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    duration: float = 0.0
    size_mib: float = 0.0
    video_kbps: float = 0.0
    audio_kbps: float = 0.0

    def warn(self, reason: str) -> None:
        if self.status == "PASS":
            self.status = "WARN"
        self.reasons.append(reason)

    def fail(self, reason: str) -> None:
        self.status = "FAIL"
        self.reasons.append(reason)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"The Cleaner v{APP_VERSION}")
        self.geometry("1080x780")
        self.minsize(900, 650)

        self.folder: str | None = None
        self.msg_q: queue.Queue[tuple[str, str]] = queue.Queue()
        self.running = False
        self.stop_requested = False
        self.current_process: subprocess.Popen[str] | None = None

        self.video_bitrate = tk.StringVar(value=str(DEFAULT_VIDEO_BITRATE_KBPS))
        self.pass_mode = tk.StringVar(value="One-pass")
        self.preset = tk.StringVar(value="fast")
        self.tune_label = tk.StringVar(value="Normal / no tune")
        self.scaler_label = tk.StringVar(value="Bicubic")
        self.resolution = tk.StringVar(value="720")

        self.build_ui()
        self.after(100, self.poll_messages)

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    def build_ui(self) -> None:
        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 5))

        tk.Button(top, text="Choose Folder", command=self.choose_folder).pack(side="left")
        self.folder_label = tk.Label(top, text="(no folder selected)", anchor="w")
        self.folder_label.pack(side="left", padx=10, fill="x", expand=True)

        settings = tk.LabelFrame(self, text="WoodPile Job")
        settings.pack(fill="x", padx=10, pady=5)

        row1 = tk.Frame(settings)
        row1.pack(fill="x", padx=8, pady=(6, 3))

        tk.Label(row1, text="Average video bitrate").pack(side="left", padx=(0, 4))
        tk.Entry(row1, width=8, textvariable=self.video_bitrate).pack(side="left", padx=(0, 4))
        tk.Label(row1, text="kb/s").pack(side="left", padx=(0, 14))

        tk.Label(row1, text="Passes").pack(side="left", padx=(0, 4))
        ttk.Combobox(
            row1, width=10, state="readonly",
            values=PASS_MODES, textvariable=self.pass_mode,
        ).pack(side="left", padx=(0, 14))

        tk.Label(row1, text="Preset").pack(side="left", padx=(0, 4))
        ttk.Combobox(
            row1, width=8, state="readonly",
            values=PRESETS, textvariable=self.preset,
        ).pack(side="left", padx=(0, 14))

        tk.Label(row1, text="Tune").pack(side="left", padx=(0, 4))
        ttk.Combobox(
            row1, width=20, state="readonly",
            values=tuple(TUNES), textvariable=self.tune_label,
        ).pack(side="left")

        row2 = tk.Frame(settings)
        row2.pack(fill="x", padx=8, pady=(3, 6))

        tk.Label(row2, text="Scaling").pack(side="left", padx=(0, 4))
        ttk.Combobox(
            row2, width=12, state="readonly",
            values=tuple(SCALERS), textvariable=self.scaler_label,
        ).pack(side="left", padx=(0, 18))

        tk.Label(row2, text="Resolution").pack(side="left", padx=(0, 4))
        tk.Radiobutton(row2, text="720p", value="720", variable=self.resolution).pack(side="left")
        tk.Radiobutton(row2, text="1080p", value="1080", variable=self.resolution).pack(side="left")
        tk.Radiobutton(row2, text="Match source", value="keep", variable=self.resolution).pack(side="left")

        controls = tk.Frame(self)
        controls.pack(fill="x", padx=10, pady=5)

        self.start_button = tk.Button(
            controls, text="Standardize", width=14, command=self.start
        )
        self.start_button.pack(side="left")

        self.stop_button = tk.Button(
            controls, text="Stop After Current", width=16,
            command=self.request_stop, state="disabled",
        )
        self.stop_button.pack(side="left", padx=(8, 0))

        tk.Button(
            controls, text="Clear Panes", width=12, command=self.clear_panes
        ).pack(side="left", padx=(8, 0))

        self.status = tk.Label(controls, text="Idle", anchor="w")
        self.status.pack(side="left", padx=12)

        # The split is intentional. The ledger answers "what needs attention?"
        # The tool pane answers "what exactly happened?"
        results_frame = tk.LabelFrame(self, text="Batch Results — PASS / WARN / FAIL")
        results_frame.pack(fill="both", expand=False, padx=10, pady=(5, 5))

        self.results = scrolledtext.ScrolledText(
            results_frame, height=10, font=("Consolas", 10), wrap="word"
        )
        self.results.pack(fill="both", expand=True, padx=5, pady=5)
        self.results.tag_configure("PASS", foreground="#167a16")
        self.results.tag_configure("WARN", foreground="#9a6500")
        self.results.tag_configure("FAIL", foreground="#b00020")
        self.results.tag_configure("INFO", foreground="#333333")

        log_frame = tk.LabelFrame(self, text="Tool Output / Verification Evidence")
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.log = scrolledtext.ScrolledText(
            log_frame, font=("Consolas", 9), wrap="none"
        )
        self.log.pack(fill="both", expand=True, padx=5, pady=5)

    def choose_folder(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.folder = folder
            self.folder_label.config(text=folder)

    def clear_panes(self) -> None:
        self.results.delete("1.0", "end")
        self.log.delete("1.0", "end")

    def request_stop(self) -> None:
        self.stop_requested = True
        self.detail("Stop requested. Current file will finish safely; no new file will start.")

    # ------------------------------------------------------------------
    # Batch control
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self.running:
            return
        if not self.folder:
            messagebox.showwarning("Folder required", "Choose a source folder first.")
            return

        missing = [
            tool for tool in ("ffmpeg", "ffprobe", "mkvmerge")
            if not self.resolve_tool(tool)
        ]
        if missing:
            messagebox.showerror(
                "Required tool missing",
                "Could not locate: " + ", ".join(missing)
                + "\n\nInstall FFmpeg and MKVToolNix or add them to PATH.",
            )
            return

        try:
            video_kbps = int(self.video_bitrate.get().strip())
            if video_kbps <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Invalid video bitrate",
                "Video bitrate must be a positive whole number in kb/s.",
            )
            return

        pass_mode = self.pass_mode.get().strip()
        preset = self.preset.get().strip()
        scaler = SCALERS.get(self.scaler_label.get())
        tune = TUNES.get(self.tune_label.get())

        if pass_mode not in PASS_MODES or preset not in PRESETS or scaler is None or tune is None:
            messagebox.showerror("Invalid settings", "One or more job settings are invalid.")
            return

        self.running = True
        self.stop_requested = False
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")

        threading.Thread(
            target=self.worker,
            args=(video_kbps, pass_mode, preset, tune, scaler),
            daemon=True,
        ).start()

    def worker(
        self,
        video_kbps: int,
        pass_mode: str,
        preset: str,
        tune: str,
        scaler: str,
    ) -> None:
        folder = Path(self.folder or "")
        logfile = folder / LOG_NAME
        passed = warned = failed = skipped = 0

        try:
            files = self.find_source_files(folder)
            self.write_run_header(
                logfile, video_kbps, pass_mode, preset, tune, scaler, len(files)
            )
            self.result(
                "INFO",
                f"START  {len(files)} eligible file(s) — "
                f"{video_kbps} kb/s, {pass_mode}, {preset}, "
                f"{self.scaler_label.get()}",
            )

            for number, infile in enumerate(files, start=1):
                if self.stop_requested:
                    self.result("INFO", "STOP  No new file started.")
                    break

                self.set_status(f"{number}/{len(files)}  {infile.name}")
                status = self.process_file(
                    infile, video_kbps, pass_mode, preset, tune, scaler, logfile
                )
                if status == "PASS":
                    passed += 1
                elif status == "WARN":
                    warned += 1
                elif status == "FAIL":
                    failed += 1
                else:
                    skipped += 1

        except Exception as exc:
            failed += 1
            self.result("FAIL", f"WRAPPER — {type(exc).__name__}: {exc}")
            self.detail(f"FATAL WRAPPER ERROR: {type(exc).__name__}: {exc}", logfile)
        finally:
            self.result(
                "INFO",
                f"FINISH  PASS={passed} WARN={warned} FAIL={failed} SKIP={skipped}",
            )
            self.set_status("Idle")
            self.msg_q.put(("running", "false"))
            self.detail("Run finished.", logfile)

    # ------------------------------------------------------------------
    # Transaction
    # ------------------------------------------------------------------

    def process_file(
        self,
        infile: Path,
        video_kbps: int,
        pass_mode: str,
        preset: str,
        tune: str,
        scaler: str,
        logfile: Path,
    ) -> str:
        started = time.monotonic()
        final_name = self.clean_filename_autoit_style(infile)
        final_path = infile.with_name(final_name)
        temp_encode = infile.with_name(f".__CLEANER_ENCODE__{infile.stem}.mkv")
        temp_mux = infile.with_name(f".__CLEANER_MUX__{infile.stem}.mkv")
        passlog = infile.with_name(f".__CLEANER_PASSLOG__{infile.stem}")

        self.detail("\n" + "=" * 90, logfile)
        self.detail(f"SOURCE: {infile}", logfile)
        self.detail(f"PLANNED FINAL: {final_path}", logfile)

        if final_path.exists() and final_path.resolve() != infile.resolve():
            self.result("WARN", f"SKIP  {infile.name} — clean final name already exists")
            self.detail("Source untouched.", logfile)
            return "SKIP"

        self.remove_if_exists(temp_encode)
        self.remove_if_exists(temp_mux)
        self.remove_passlog_files(passlog)

        source_moved = False
        orig_path: Path | None = None

        try:
            source_probe = self.probe_file(infile)
            source = self.source_info(source_probe)
            self.log_source_summary(source_probe, source, logfile)

            source_video = self.scan_continuity(infile, "v:0", logfile)
            source_audio = self.scan_continuity(infile, "a:0", logfile)
            source_flags = self.classify_continuity(source_video, "source video")
            source_flags += self.classify_continuity(source_audio, "source audio")
            for severity, reason in source_flags:
                self.detail(f"SOURCE {severity}: {reason}", logfile)

            # Fatal source damage is knowable before encoding. Do not spend an
            # entire encode proving that a clearly damaged source remains
            # damaged. Record the evidence, leave the source untouched, and
            # continue the batch.
            fatal_source_findings = [
                reason for severity, reason in source_flags if severity == "FAIL"
            ]
            if fatal_source_findings:
                elapsed = self.format_duration(time.monotonic() - started)
                reason = fatal_source_findings[0]
                extra = (
                    f" (+{len(fatal_source_findings) - 1} more)"
                    if len(fatal_source_findings) > 1 else ""
                )
                self.result(
                    "FAIL",
                    f"FAIL  {infile.name} — source damaged: {reason}{extra} — {elapsed}",
                )
                self.detail(
                    "PREFLIGHT STOP: fatal source continuity damage detected. "
                    "No encode was started; source left untouched.",
                    logfile,
                )
                return "FAIL"

            self.detail(
                f"RATE CONTROL: {video_kbps} kb/s; {pass_mode}; "
                f"preset={preset}; tune={tune or 'none'}; "
                f"resolution={self.resolution.get()}; scaler={self.scaler_label.get()}",
                logfile,
            )

            if pass_mode == "Two-pass":
                first_pass_cmd = self.build_ffmpeg_first_pass_command(
                    infile, video_kbps, preset, tune, scaler, passlog
                )
                self.run_checked(first_pass_cmd, logfile, "FFMPEG PASS 1")

            encode_cmd = self.build_ffmpeg_command(
                infile, temp_encode, source, video_kbps,
                preset, tune, scaler, pass_mode, passlog,
            )
            self.run_checked(
                encode_cmd, logfile,
                "FFMPEG PASS 2" if pass_mode == "Two-pass" else "FFMPEG",
            )
            self.remove_passlog_files(passlog)

            if not temp_encode.exists() or temp_encode.stat().st_size == 0:
                raise RuntimeError("FFmpeg did not create a usable temporary output.")

            mux_cmd = self.build_mkvmerge_command(temp_encode, temp_mux, source)
            mux_code = self.run_live_command(mux_cmd, logfile, "MKVMERGE")
            if mux_code not in (0, 1):
                raise RuntimeError(f"mkvmerge returned code {mux_code}.")

            report = self.verify_final(
                source=source,
                source_video=source_video,
                source_audio=source_audio,
                outfile=temp_mux,
                logfile=logfile,
            )
            if report.status == "FAIL":
                raise RuntimeError("; ".join(report.reasons))

            # Transaction safety:
            #
            # The source may already have the intended final filename. Promoting
            # over that path first would destroy the original. Therefore the
            # verified source is moved to orig, then the final is promoted. If
            # promotion fails, the source is restored immediately.
            orig_dir = infile.parent / "orig"
            orig_dir.mkdir(exist_ok=True)
            orig_path = self.unique_orig_path(orig_dir / infile.name)
            shutil.move(str(infile), str(orig_path))
            source_moved = True
            self.detail(f"ORIGINAL MOVED: {orig_path}", logfile)

            try:
                temp_mux.replace(final_path)
                self.detail(f"FINAL PROMOTED: {final_path}", logfile)
            except Exception:
                if orig_path.exists() and not infile.exists():
                    shutil.move(str(orig_path), str(infile))
                    source_moved = False
                    self.detail("ROLLBACK: original restored after promotion failure.", logfile)
                raise

            self.remove_if_exists(temp_encode)
            elapsed = self.format_duration(time.monotonic() - started)

            reason = report.reasons[0] if report.reasons else "all required checks passed"
            extra = f" (+{len(report.reasons)-1} more)" if len(report.reasons) > 1 else ""
            self.result(
                report.status,
                f"{report.status}  {final_path.name} — {reason}{extra} — {elapsed}",
            )
            self.log_verification(report, logfile)
            return report.status

        except Exception as exc:
            # Roll back only what Cleaner itself changed.
            if source_moved and orig_path and orig_path.exists() and not infile.exists():
                try:
                    shutil.move(str(orig_path), str(infile))
                    self.detail("ROLLBACK: original restored to working folder.", logfile)
                except OSError as rollback_exc:
                    self.detail(f"ROLLBACK FAILED: {rollback_exc}", logfile)

            self.remove_if_exists(temp_encode)
            self.remove_if_exists(temp_mux)
            self.remove_passlog_files(passlog)

            elapsed = self.format_duration(time.monotonic() - started)
            self.result("FAIL", f"FAIL  {infile.name} — {type(exc).__name__}: {exc} — {elapsed}")
            self.detail(f"FAILED: {type(exc).__name__}: {exc}", logfile)
            self.detail("Source preserved; incomplete temporary files removed.", logfile)
            return "FAIL"

    # ------------------------------------------------------------------
    # Command construction
    # ------------------------------------------------------------------

    def build_ffmpeg_first_pass_command(
        self,
        infile: Path,
        video_bitrate_kbps: int,
        preset: str,
        tune: str,
        scaler: str,
        passlog: Path,
    ) -> list[str]:
        cmd = [
            self.resolve_tool("ffmpeg") or "ffmpeg",
            "-y", "-hide_banner", "-loglevel", "info", "-stats",
            "-i", str(infile), "-map", "0:v:0",
        ]
        cmd += self.build_video_options(
            video_bitrate_kbps, preset, tune, scaler,
            pass_number=1, passlog=passlog,
        )
        cmd += [
            "-an", "-sn", "-dn", "-f", "null",
            "NUL" if os.name == "nt" else "/dev/null",
        ]
        return cmd

    def build_ffmpeg_command(
        self,
        infile: Path,
        outfile: Path,
        source: SourceInfo,
        video_bitrate_kbps: int,
        preset: str,
        tune: str,
        scaler: str,
        pass_mode: str,
        passlog: Path,
    ) -> list[str]:
        cmd = [
            self.resolve_tool("ffmpeg") or "ffmpeg",
            "-y", "-hide_banner", "-loglevel", "info", "-stats",
            "-i", str(infile),
            "-map", "0:v:0",
            "-map", "0:a:0",
        ]

        for subtitle in source.subtitles:
            cmd += ["-map", f"0:{subtitle.source_index}"]

        cmd += ["-map", "0:t?", "-map_metadata", "-1", "-map_chapters", "0"]
        cmd += self.build_video_options(
            video_bitrate_kbps, preset, tune, scaler,
            pass_number=2 if pass_mode == "Two-pass" else None,
            passlog=passlog if pass_mode == "Two-pass" else None,
        )
        cmd += [
            "-metadata:s:v:0", "language=und",
            "-metadata:s:v:0", "title=",
        ]
        cmd += [
            "-c:a", "aac", "-ac", "2", "-b:a", f"{AUDIO_BITRATE_KBPS}k",
            "-ar", "48000",
            "-metadata:s:a:0", f"language={source.audio_language}",
            "-metadata:s:a:0", "title=",
        ]

        if source.subtitles:
            cmd += ["-c:s", "copy"]
            for out_index, subtitle in enumerate(source.subtitles):
                cmd += [f"-metadata:s:s:{out_index}", "language=eng"]
                cmd += [
                    f"-metadata:s:s:{out_index}",
                    f"title={'SDH' if subtitle.is_sdh else ''}",
                ]

        cmd += ["-c:t", "copy", "-metadata", "title=", str(outfile)]
        return cmd

    def build_video_options(
        self,
        video_bitrate_kbps: int,
        preset: str,
        tune: str,
        scaler: str,
        pass_number: int | None,
        passlog: Path | None,
    ) -> list[str]:
        # Non-standard geometry is not a reason to reject or stretch media.
        # Match Source preserves geometry and uses Level 4.1 as the documented
        # 1080-class compatibility policy.
        level = "3.1" if self.resolution.get() == "720" else "4.1"
        options = [
            "-c:v", "libx264",
            "-preset", preset,
            "-b:v", f"{video_bitrate_kbps}k",
            "-profile:v", "high",
            "-level:v", level,
            "-pix_fmt", "yuv420p",
        ]
        if tune:
            options += ["-tune", tune]

        video_filter = self.build_video_filter(scaler)
        if video_filter:
            options += ["-vf", video_filter]

        if pass_number is not None and passlog is not None:
            options += ["-pass", str(pass_number), "-passlogfile", str(passlog)]
        return options

    def build_video_filter(self, scaler: str) -> str:
        # yadif acts only on frames marked interlaced. Fixed-resolution modes
        # preserve aspect ratio, never upscale, and pad without distortion.
        parts = ["yadif=deint=interlaced"]
        resolution = self.resolution.get()
        if resolution == "720":
            parts += [
                f"scale=w=1280:h=720:force_original_aspect_ratio=decrease:"
                f"force_divisible_by=2:flags={scaler}",
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
            ]
        elif resolution == "1080":
            parts += [
                f"scale=w=1920:h=1080:force_original_aspect_ratio=decrease:"
                f"force_divisible_by=2:flags={scaler}",
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
            ]
        return ",".join(parts)

    def build_mkvmerge_command(
        self, infile: Path, outfile: Path, source: SourceInfo
    ) -> list[str]:
        identify = self.identify_mkv(infile)
        tracks = identify.get("tracks", [])
        cmd = [
            self.resolve_tool("mkvmerge") or "mkvmerge",
            "-o", str(outfile),
            "--no-global-tags", "--no-track-tags",
            "--title", "",
        ]

        subtitle_number = 0
        for track in tracks:
            tid = str(track.get("id"))
            ttype = track.get("type")
            if ttype == "video":
                cmd += ["--language", f"{tid}:und", "--track-name", f"{tid}:"]
            elif ttype == "audio":
                cmd += [
                    "--language", f"{tid}:{source.audio_language}",
                    "--track-name", f"{tid}:",
                ]
            elif ttype == "subtitles":
                is_sdh = (
                    source.subtitles[subtitle_number].is_sdh
                    if subtitle_number < len(source.subtitles) else False
                )
                cmd += [
                    "--language", f"{tid}:eng",
                    "--track-name", f"{tid}:{'SDH' if is_sdh else ''}",
                ]
                subtitle_number += 1

        cmd.append(str(infile))
        return cmd

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_final(
        self,
        source: SourceInfo,
        source_video: ContinuityReport,
        source_audio: ContinuityReport,
        outfile: Path,
        logfile: Path,
    ) -> VerificationReport:
        report = VerificationReport()

        if not outfile.exists():
            report.fail("final candidate is missing")
            return report

        report.size_mib = outfile.stat().st_size / 1024 / 1024
        if report.size_mib < MIN_OUTPUT_MIB:
            report.fail(f"final candidate is implausibly small ({report.size_mib:.1f} MiB)")
            return report

        probe = self.probe_file(outfile)
        report.duration = self.get_duration(probe)
        duration_delta = abs(report.duration - source.duration)
        if duration_delta > DURATION_TOLERANCE_SECONDS:
            report.fail(f"duration differs from source by {duration_delta:.2f}s")

        streams = probe.get("streams", [])
        video = [s for s in streams if s.get("codec_type") == "video"]
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        subs = [s for s in streams if s.get("codec_type") == "subtitle"]

        if len(video) != 1:
            report.fail(f"expected one video stream; found {len(video)}")
        if len(audio) != 1:
            report.fail(f"expected one audio stream; found {len(audio)}")
        if len(subs) != len(source.subtitles):
            report.warn(
                f"expected {len(source.subtitles)} English subtitle(s); found {len(subs)}"
            )

        if video:
            v = video[0]
            if v.get("codec_name") != "h264":
                report.fail(f"video codec is {v.get('codec_name')}, not H.264")
            if v.get("pix_fmt") != "yuv420p":
                report.fail(f"video pixel format is {v.get('pix_fmt')}, not yuv420p")
            if self.track_title(v):
                report.warn("video title field is not absent")

        if audio:
            a = audio[0]
            if a.get("codec_name") != "aac" or int(a.get("channels", 0)) != 2:
                report.fail("audio is not AAC stereo")
            if self.track_title(a):
                report.warn("audio title field is not absent")

        for index, stream in enumerate(subs):
            lang = str(stream.get("tags", {}).get("language", "")).lower()
            if lang not in ENGLISH_CODES:
                report.warn(f"subtitle {index + 1} language is not English")
            if index < len(source.subtitles):
                expected = "SDH" if source.subtitles[index].is_sdh else ""
                actual = self.track_title(stream)
                if actual != expected:
                    report.warn(
                        f"subtitle {index + 1} title is {actual!r}; expected {expected!r}"
                    )

        format_tags = probe.get("format", {}).get("tags", {}) or {}
        if str(format_tags.get("title", "")).strip():
            report.warn("container title field is not absent")

        output_video = self.scan_continuity(outfile, "v:0", logfile)
        output_audio = self.scan_continuity(outfile, "a:0", logfile)

        for severity, reason in self.classify_continuity(output_video, "output video"):
            if severity == "FAIL":
                report.fail(reason)
            else:
                report.warn(reason)

        for severity, reason in self.classify_continuity(output_audio, "output audio"):
            if severity == "FAIL":
                report.fail(reason)
            else:
                report.warn(reason)

        # A damaged source may legitimately produce an output with the same gap.
        # Cleaner should not hide that evidence, but neither should it pretend the
        # encoder caused it. The output is retained and clearly flagged.
        self.compare_continuity(source_video, output_video, "video", report)
        self.compare_continuity(source_audio, output_audio, "audio", report)

        report.video_kbps = self.measure_packet_bitrate(outfile, "v:0", report.duration)
        report.audio_kbps = self.measure_packet_bitrate(outfile, "a:0", report.duration)

        report.details.extend([
            f"size {report.size_mib:.1f} MiB",
            f"duration {self.format_duration(report.duration)}",
            f"video packet bitrate {report.video_kbps:.0f} kb/s",
            f"audio packet bitrate {report.audio_kbps:.0f} kb/s",
            f"streams video={len(video)} audio={len(audio)} subtitles={len(subs)}",
        ])
        return report

    def scan_continuity(
        self, infile: Path, selector: str, logfile: Path
    ) -> ContinuityReport:
        # This is intentionally a timestamp scan, not a second decode. It gives
        # useful evidence about missing packet ranges at a small runtime cost.
        #
        # Use DTS as the continuity clock. Earlier code used PTS first and falsely
        # reported normal H.264 B-frame reordering as thousands of backward
        # timestamp steps, causing every healthy encode to fail verification.
        cmd = [
            self.resolve_tool("ffprobe") or "ffprobe",
            "-v", "error",
            "-select_streams", selector,
            "-show_entries", "packet=dts_time,pts_time,duration_time",
            "-of", "compact=p=0:nk=0",
            str(infile),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            creationflags=self.no_window_flag(),
        )
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or f"ffprobe could not scan {selector} packets"
            )

        report = ContinuityReport(selector=selector)
        previous: float | None = None

        for raw in result.stdout.splitlines():
            values: dict[str, str] = {}
            for field in raw.strip().split("|"):
                if "=" not in field:
                    continue
                key, value = field.split("=", 1)
                values[key.strip()] = value.strip()

            # Packet traversal is in decode order. DTS is therefore the correct
            # continuity clock. PTS may legitimately move backward when H.264
            # B-frames are reordered and must not be treated as corruption.
            timestamp = self.safe_float(values.get("dts_time"))
            if timestamp is None:
                timestamp = self.safe_float(values.get("pts_time"))
            if timestamp is None:
                continue

            report.packet_count += 1
            if report.first_pts is None:
                report.first_pts = timestamp
            report.last_pts = timestamp

            if previous is not None:
                gap = timestamp - previous
                if gap < -0.001:
                    report.backward_steps += 1
                    # Preserve enough evidence to inspect the exact area later:
                    # packet number, prior DTS, current DTS, and reversal size.
                    report.backward_events.append((
                        report.packet_count,
                        previous,
                        timestamp,
                        abs(gap),
                    ))
                elif gap > report.largest_gap:
                    report.largest_gap = gap
                    report.gap_start = previous
                    report.gap_end = timestamp
            previous = timestamp

        self.detail(
            f"CONTINUITY {selector}: packets={report.packet_count:,}; "
            f"largest_gap={report.largest_gap:.3f}s; "
            f"backward_steps={report.backward_steps}",
            logfile,
        )

        # Backward DTS events are retained as diagnostics even when too small or
        # too rare to affect archive confidence. Each event identifies a place
        # the operator can inspect in a player rather than leaving only a count.
        for event_number, (packet_number, prior_dts, current_dts, reversal) in enumerate(
            report.backward_events, start=1
        ):
            self.detail(
                f"BACKWARD DTS {selector} #{event_number}: "
                f"inspect near {self.format_timestamp(current_dts)}; "
                f"packet={packet_number:,}; "
                f"previous={prior_dts:.6f}s; current={current_dts:.6f}s; "
                f"reversal={reversal:.6f}s",
                logfile,
            )

        return report

    @staticmethod
    def classify_continuity(
        continuity: ContinuityReport, label: str
    ) -> list[tuple[str, str]]:
        findings: list[tuple[str, str]] = []
        is_audio = continuity.selector.startswith("a")
        warn_gap = AUDIO_WARN_GAP_SECONDS if is_audio else WARN_GAP_SECONDS
        fail_gap = AUDIO_FAIL_GAP_SECONDS if is_audio else FAIL_GAP_SECONDS

        if continuity.packet_count == 0:
            findings.append(("FAIL", f"{label} contains no readable packets"))
            return findings

        if continuity.largest_gap >= fail_gap:
            findings.append((
                "FAIL",
                f"{label} timestamp gap "
                f"{App.format_timestamp(continuity.gap_start)} -> "
                f"{App.format_timestamp(continuity.gap_end)} "
                f"({continuity.largest_gap:.3f}s)",
            ))
        elif continuity.largest_gap >= warn_gap:
            findings.append((
                "WARN",
                f"{label} timestamp gap "
                f"{App.format_timestamp(continuity.gap_start)} -> "
                f"{App.format_timestamp(continuity.gap_end)} "
                f"({continuity.largest_gap:.3f}s)",
            ))

        # Isolated DTS reversals are commonly too small to indicate a visible
        # defect, so 0-10 remain diagnostic-only and do not lower confidence.
        # The full event list is still written to the log for direct inspection.
        if continuity.backward_steps > 100:
            findings.append((
                "FAIL",
                f"{label} has {continuity.backward_steps} backward timestamp steps",
            ))
        elif continuity.backward_steps > 10:
            findings.append((
                "WARN",
                f"{label} has {continuity.backward_steps} backward timestamp steps",
            ))
        return findings

    @staticmethod
    def compare_continuity(
        source: ContinuityReport,
        output: ContinuityReport,
        label: str,
        report: VerificationReport,
    ) -> None:
        tolerance = 0.5
        if source.largest_gap >= WARN_GAP_SECONDS:
            if abs(output.largest_gap - source.largest_gap) <= tolerance:
                report.warn(
                    f"{label} gap present in source and preserved in output "
                    f"({output.largest_gap:.3f}s)"
                )
            elif output.largest_gap > source.largest_gap + tolerance:
                report.fail(
                    f"output {label} gap is larger than source "
                    f"({source.largest_gap:.3f}s -> {output.largest_gap:.3f}s)"
                )
        elif output.largest_gap >= WARN_GAP_SECONDS:
            report.fail(
                f"new {label} gap appeared in output ({output.largest_gap:.3f}s)"
            )

    # ------------------------------------------------------------------
    # Inspection and helpers
    # ------------------------------------------------------------------

    def source_info(self, probe: dict[str, Any]) -> SourceInfo:
        duration = self.get_duration(probe)
        streams = probe.get("streams", [])

        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        if not video_streams:
            raise RuntimeError("Source contains no video stream.")
        if not audio_streams:
            raise RuntimeError("Source contains no audio stream.")

        video = video_streams[0]
        audio = audio_streams[0]
        audio_language = self.normalize_language(
            audio.get("tags", {}).get("language"), fallback="eng"
        )

        subtitles: list[SubtitleSelection] = []
        for stream in streams:
            if stream.get("codec_type") != "subtitle":
                continue
            lang = str(stream.get("tags", {}).get("language", "")).lower().strip()
            if lang not in ENGLISH_CODES:
                continue

            title = str(stream.get("tags", {}).get("title", ""))
            disposition = stream.get("disposition", {}) or {}
            is_sdh = bool(disposition.get("hearing_impaired")) or any(
                marker in title.lower() for marker in SDH_MARKERS
            )
            subtitles.append(SubtitleSelection(
                source_index=int(stream["index"]),
                language="eng",
                is_sdh=is_sdh,
                codec_name=str(stream.get("codec_name", "unknown")),
            ))

        return SourceInfo(
            duration=duration,
            audio_language=audio_language,
            subtitles=subtitles,
            has_chapters=bool(probe.get("chapters")),
            width=int(video.get("width", 0)),
            height=int(video.get("height", 0)),
            video_codec=str(video.get("codec_name", "unknown")),
            audio_codec=str(audio.get("codec_name", "unknown")),
        )

    def probe_file(self, infile: Path) -> dict[str, Any]:
        cmd = [
            self.resolve_tool("ffprobe") or "ffprobe",
            "-v", "error",
            "-show_streams", "-show_format", "-show_chapters",
            "-of", "json", str(infile),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            creationflags=self.no_window_flag(),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffprobe failed")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Could not parse ffprobe output: {exc}") from exc

    def identify_mkv(self, infile: Path) -> dict[str, Any]:
        cmd = [self.resolve_tool("mkvmerge") or "mkvmerge", "-J", str(infile)]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            creationflags=self.no_window_flag(),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "mkvmerge identification failed")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Could not parse mkvmerge JSON: {exc}") from exc

    def run_checked(self, cmd: list[str], logfile: Path, phase: str) -> None:
        code = self.run_live_command(cmd, logfile, phase)
        if code != 0:
            raise RuntimeError(f"{phase} returned code {code}")

    def run_live_command(self, cmd: list[str], logfile: Path, phase: str) -> int:
        self.detail(f"\n{phase} COMMAND:\n{self.command_text(cmd)}", logfile)
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=self.no_window_flag(),
        )
        self.current_process = process
        assert process.stdout is not None
        for line in process.stdout:
            clean = line.rstrip()
            if clean:
                self.detail(f"[{phase}] {clean}", logfile)
        code = process.wait()
        self.current_process = None
        return code

    def measure_packet_bitrate(
        self, infile: Path, selector: str, duration: float
    ) -> float:
        cmd = [
            self.resolve_tool("ffprobe") or "ffprobe",
            "-v", "error",
            "-select_streams", selector,
            "-show_entries", "packet=size",
            "-of", "csv=p=0",
            str(infile),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            creationflags=self.no_window_flag(),
        )
        if result.returncode != 0:
            return 0.0

        total = 0
        for line in result.stdout.splitlines():
            try:
                total += int(line.strip().split(",")[0])
            except (ValueError, IndexError):
                continue
        return total * 8 / duration / 1000 if duration > 0 else 0.0

    def log_source_summary(
        self, probe: dict[str, Any], source: SourceInfo, logfile: Path
    ) -> None:
        self.detail(
            "SOURCE INSPECTION:\n"
            f"  Duration: {self.format_duration(source.duration)}\n"
            f"  Video: {source.video_codec} {source.width}x{source.height}\n"
            f"  Audio: {source.audio_codec} language={source.audio_language}\n"
            f"  English subtitles selected: {len(source.subtitles)}\n"
            f"  Chapters present: {'yes' if source.has_chapters else 'no'}",
            logfile,
        )

    def log_verification(
        self, report: VerificationReport, logfile: Path
    ) -> None:
        self.detail(f"\nARCHIVE CONFIDENCE: {report.status}", logfile)
        for reason in report.reasons:
            self.detail(f"  {report.status}: {reason}", logfile)
        for item in report.details:
            self.detail(f"  DETAIL: {item}", logfile)

    def write_run_header(
        self,
        logfile: Path,
        video_kbps: int,
        pass_mode: str,
        preset: str,
        tune: str,
        scaler: str,
        count: int,
    ) -> None:
        self.detail("\n" + "#" * 90, logfile)
        self.detail(
            f"The Cleaner v{APP_VERSION} ({APP_DATE})\n"
            f"Video={video_kbps} kb/s; mode={pass_mode}; preset={preset}; "
            f"tune={tune or 'none'}; scaler={self.scaler_label.get()}; "
            f"resolution={self.resolution.get()}\n"
            f"Audio=AAC LC stereo {AUDIO_BITRATE_KBPS} kb/s total\n"
            f"Eligible files={count}",
            logfile,
        )

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    def result(self, level: str, message: str) -> None:
        self.msg_q.put(("result", f"{level}\t{message}"))

    def detail(self, message: str, logfile: Path | None = None) -> None:
        self.msg_q.put(("detail", message))
        if logfile:
            try:
                with logfile.open("a", encoding="utf-8") as handle:
                    handle.write(message + "\n")
            except OSError:
                pass

    def set_status(self, message: str) -> None:
        self.msg_q.put(("status", message))

    def poll_messages(self) -> None:
        try:
            while True:
                kind, message = self.msg_q.get_nowait()
                if kind == "result":
                    level, text = message.split("\t", 1)
                    self.results.insert("end", text + "\n", level)
                    self.results.see("end")
                elif kind == "detail":
                    self.log.insert("end", message + "\n")
                    self.log.see("end")
                elif kind == "status":
                    self.status.config(text=message)
                elif kind == "running":
                    self.running = False
                    self.start_button.config(state="normal")
                    self.stop_button.config(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self.poll_messages)

    # ------------------------------------------------------------------
    # Static utilities
    # ------------------------------------------------------------------

    @staticmethod
    def clean_filename_autoit_style(infile: Path) -> str:
        stem = infile.stem
        stem = re.sub(r"[\[\](){}]", " ", stem)
        stem = re.sub(r"[._]+", " ", stem)
        stem = re.sub(r"\s+", " ", stem).strip()

        match = re.search(r"(?i)\bS(\d{1,2})E(\d{1,3})\b", stem)
        if not match:
            tokens = stem.split()
            kept: list[str] = []
            for token in tokens:
                if token.lower() in TECH_TOKENS or re.fullmatch(r"(?i)(x|h)26[45]", token):
                    break
                kept.append(token)
            clean = " ".join(kept) or stem
            return App.smart_title(clean) + ".mkv"

        show_part = stem[:match.start()].strip(" -")
        season = int(match.group(1))
        episode = int(match.group(2))
        remainder = stem[match.end():].strip(" -")

        episode_tokens: list[str] = []
        for token in remainder.split():
            low = token.lower().strip("-")
            if low in TECH_TOKENS or re.fullmatch(r"(?i)(x|h)26[45]", token):
                break
            if re.fullmatch(r"(?i)(ddp?|dts|aac|ac3|eac3)\d*(\.\d+)?", token):
                break
            episode_tokens.append(token)

        clean = f"{App.smart_title(show_part)} S{season:02d}E{episode:02d}"
        if episode_tokens:
            clean += " " + App.smart_title(" ".join(episode_tokens))
        return clean.strip() + ".mkv"

    @staticmethod
    def smart_title(text: str) -> str:
        words: list[str] = []
        for word in re.sub(r"\s+", " ", text).strip().split(" "):
            if not word:
                continue
            if word.isupper() and len(word) <= 5:
                words.append(word)
            elif re.fullmatch(r"\d+", word):
                words.append(word)
            else:
                words.append(word[:1].upper() + word[1:])
        return " ".join(words)

    @staticmethod
    def find_source_files(folder: Path) -> list[Path]:
        files: list[Path] = []
        for root, dirs, names in os.walk(folder):
            dirs[:] = [d for d in dirs if d.lower() != "orig"]
            for name in names:
                path = Path(root) / name
                if path.suffix.lower() not in VIDEO_EXTS:
                    continue
                if path.name.startswith(".__CLEANER_"):
                    continue
                files.append(path)
        return sorted(files, key=lambda p: str(p).lower())

    @staticmethod
    def resolve_tool(name: str) -> str | None:
        found = shutil.which(name)
        if found:
            return found

        if os.name == "nt":
            program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            program_files_x86 = Path(
                os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
            )
            candidates = {
                "mkvmerge": [
                    program_files / "MKVToolNix" / "mkvmerge.exe",
                    program_files_x86 / "MKVToolNix" / "mkvmerge.exe",
                ],
                "ffmpeg": [
                    Path(r"C:\Apps\ffmpeg\bin\ffmpeg.exe"),
                    Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
                ],
                "ffprobe": [
                    Path(r"C:\Apps\ffmpeg\bin\ffprobe.exe"),
                    Path(r"C:\ffmpeg\bin\ffprobe.exe"),
                ],
            }
            for candidate in candidates.get(name, []):
                if candidate.exists():
                    return str(candidate)
        return None

    @staticmethod
    def remove_if_exists(path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    @staticmethod
    def remove_passlog_files(passlog: Path) -> None:
        try:
            for candidate in passlog.parent.glob(passlog.name + "*"):
                if candidate.is_file():
                    candidate.unlink()
        except OSError:
            pass

    @staticmethod
    def unique_orig_path(path: Path) -> Path:
        if not path.exists():
            return path
        counter = 2
        while True:
            candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def get_duration(probe: dict[str, Any]) -> float:
        value = probe.get("format", {}).get("duration")
        duration = App.safe_float(value)
        if duration is None or duration <= 0:
            raise RuntimeError("Could not determine a valid media duration.")
        return duration

    @staticmethod
    def normalize_language(value: Any, fallback: str) -> str:
        text = str(value or "").strip().lower()
        return text if re.fullmatch(r"[a-z]{3}", text) else fallback

    @staticmethod
    def track_title(stream: dict[str, Any]) -> str:
        return str((stream.get("tags", {}) or {}).get("title", "")).strip()

    @staticmethod
    def safe_float(value: Any) -> float | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.upper() == "N/A":
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def command_text(cmd: Iterable[str]) -> str:
        return subprocess.list2cmdline(list(cmd))

    @staticmethod
    def format_duration(seconds: float) -> str:
        total = int(round(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def format_timestamp(seconds: float | None) -> str:
        if seconds is None:
            return "?"
        return App.format_duration(seconds)

    @staticmethod
    def no_window_flag() -> int:
        return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


if __name__ == "__main__":
    App().mainloop()
