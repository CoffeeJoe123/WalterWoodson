"""
Media Standardizer v1.3

Production-shaped Joe Standard pipeline:
  inspect -> encode temporary MKV -> MKVToolNix cleanup -> verify
  -> move untouched source to orig -> promote clean final name -> continue

Locked policy:
- H.264/x264, High profile, 8-bit yuv420p; progressive; never upscale.
- AAC LC stereo, 192 kb/s total, 48 kHz.
- Keep English subtitles automatically; discard non-English subtitles.
- Ordinary subtitle title absent; SDH subtitle title exactly "SDH".
- Video language Unknown; video/audio/container titles absent.
- Final MKVToolNix remux removes inherited tags/statistics and track titles.
- Clean AutoIt-style archive naming.
- Original moves to orig only after final verification; never deleted.

v1.3 keeps the proven transaction pipeline and adds selectable one-pass or
two-pass x264 average-bitrate encoding. Two-pass is the default for final
library encodes; one-pass remains available for direct comparison. Resolution
selects the matching H.264 level automatically, and the scaler is user
selectable with Bicubic as the default.
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
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any

APP_VERSION = "1.3"
VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".mpg", ".mpeg", ".ts", ".m2ts"}
AUDIO_BITRATE_KBPS = 192
DEFAULT_VIDEO_BITRATE_KBPS = 1750
PRESETS = ("fast", "medium", "slow")
PASS_MODES = ("Two-pass", "One-pass")
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
LOG_NAME = "Media_Standardizer.log"

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


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Media Standardizer v{APP_VERSION}")
        self.geometry("960x650")
        self.minsize(820, 520)

        self.folder: str | None = None
        self.msg_q: queue.Queue[tuple[str, str]] = queue.Queue()
        self.running = False
        self.stop_requested = False

        self.video_bitrate = tk.StringVar(value=str(DEFAULT_VIDEO_BITRATE_KBPS))
        self.pass_mode = tk.StringVar(value="Two-pass")
        self.preset = tk.StringVar(value="slow")
        self.tune_label = tk.StringVar(value="Normal / no tune")
        self.scaler_label = tk.StringVar(value="Bicubic")
        self.resolution = tk.StringVar(value="720")

        self.build_ui()
        self.after(100, self.poll_messages)

    def build_ui(self) -> None:
        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 5))

        tk.Button(top, text="Choose Folder", command=self.choose_folder).pack(side="left")
        self.folder_label = tk.Label(top, text="(no folder selected)", anchor="w")
        self.folder_label.pack(side="left", padx=10, fill="x", expand=True)

        settings = tk.LabelFrame(self, text="Job")
        settings.pack(fill="x", padx=10, pady=5)

        row1 = tk.Frame(settings)
        row1.pack(fill="x", padx=8, pady=(6, 3))

        tk.Label(row1, text="Average video bitrate").pack(side="left", padx=(0, 4))
        tk.Entry(row1, width=8, textvariable=self.video_bitrate).pack(side="left", padx=(0, 4))
        tk.Label(row1, text="kb/s").pack(side="left", padx=(0, 14))

        tk.Label(row1, text="Passes").pack(side="left", padx=(0, 4))
        ttk.Combobox(
            row1,
            width=10,
            state="readonly",
            values=PASS_MODES,
            textvariable=self.pass_mode,
        ).pack(side="left", padx=(0, 14))

        tk.Label(row1, text="Preset").pack(side="left", padx=(0, 4))
        ttk.Combobox(
            row1,
            width=8,
            state="readonly",
            values=PRESETS,
            textvariable=self.preset,
        ).pack(side="left", padx=(0, 14))

        tk.Label(row1, text="Tune").pack(side="left", padx=(0, 4))
        ttk.Combobox(
            row1,
            width=20,
            state="readonly",
            values=tuple(TUNES.keys()),
            textvariable=self.tune_label,
        ).pack(side="left")

        row2 = tk.Frame(settings)
        row2.pack(fill="x", padx=8, pady=(3, 6))

        tk.Label(row2, text="Scaling").pack(side="left", padx=(0, 4))
        ttk.Combobox(
            row2,
            width=12,
            state="readonly",
            values=tuple(SCALERS.keys()),
            textvariable=self.scaler_label,
        ).pack(side="left", padx=(0, 18))

        tk.Label(row2, text="Resolution").pack(side="left", padx=(0, 4))
        tk.Radiobutton(row2, text="720p", value="720", variable=self.resolution).pack(side="left")
        tk.Radiobutton(row2, text="1080p", value="1080", variable=self.resolution).pack(side="left")
        tk.Radiobutton(row2, text="Match source", value="keep", variable=self.resolution).pack(side="left")

        controls = tk.Frame(self)
        controls.pack(fill="x", padx=10, pady=5)

        self.start_button = tk.Button(controls, text="Standardize", width=14, command=self.start)
        self.start_button.pack(side="left")

        self.stop_button = tk.Button(
            controls,
            text="Stop After Current",
            width=16,
            command=self.request_stop,
            state="disabled",
        )
        self.stop_button.pack(side="left", padx=(8, 0))

        tk.Button(controls, text="Clear Log", width=12, command=self.clear_log).pack(side="left", padx=(8, 0))

        self.status = tk.Label(controls, text="Idle", anchor="w")
        self.status.pack(side="left", padx=12)

        self.log = scrolledtext.ScrolledText(self, font=("Consolas", 10))
        self.log.pack(fill="both", expand=True, padx=10, pady=(5, 10))

    def choose_folder(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.folder = folder
            self.folder_label.config(text=folder)

    def clear_log(self) -> None:
        self.log.delete("1.0", "end")

    def request_stop(self) -> None:
        self.stop_requested = True
        self.log_message("Stop requested. Current file will finish safely; no new file will start.")

    def start(self) -> None:
        if self.running:
            return
        if not self.folder:
            messagebox.showwarning("Folder required", "Choose a source folder first.")
            return

        missing = [tool for tool in ("ffmpeg", "ffprobe", "mkvmerge") if not self.resolve_tool(tool)]
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
        if pass_mode not in PASS_MODES:
            messagebox.showerror("Invalid pass mode", "Choose one-pass or two-pass.")
            return

        preset = self.preset.get().strip()
        if preset not in PRESETS:
            messagebox.showerror("Invalid preset", "Choose fast, medium, or slow.")
            return

        scaler = SCALERS.get(self.scaler_label.get())
        if scaler is None:
            messagebox.showerror("Invalid scaler", "Choose one of the listed scaling methods.")
            return

        tune = TUNES.get(self.tune_label.get())
        if tune is None:
            messagebox.showerror("Invalid tune", "Choose one of the listed tune modes.")
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
        try:
            files = self.find_source_files(folder)
            self.write_header(logfile, video_kbps, pass_mode, preset, tune, scaler, len(files))
            self.log_message(f"Found {len(files)} eligible source file(s).", logfile)

            for number, infile in enumerate(files, start=1):
                if self.stop_requested:
                    self.log_message("Stopped before starting the next file.", logfile)
                    break

                self.set_status(f"{number}/{len(files)}  {infile.name}")
                self.process_file(infile, video_kbps, pass_mode, preset, tune, scaler, logfile)

        except Exception as exc:
            self.log_message(f"FATAL WRAPPER ERROR: {type(exc).__name__}: {exc}", logfile)
        finally:
            self.set_status("Idle")
            self.msg_q.put(("running", "false"))
            self.log_message("Run finished.", logfile)

    def process_file(
        self,
        infile: Path,
        video_kbps: int,
        pass_mode: str,
        preset: str,
        tune: str,
        scaler: str,
        logfile: Path,
    ) -> None:
        started = time.time()
        final_name = self.clean_filename_autoit_style(infile)
        final_path = infile.with_name(final_name)
        temp_encode = infile.with_name(f".__MS_ENCODE__{infile.stem}.mkv")
        temp_mux = infile.with_name(f".__MS_MUX__{infile.stem}.mkv")

        self.log_message("\n" + "=" * 78, logfile)
        self.log_message(f"SOURCE: {infile}", logfile)
        self.log_message(f"PLANNED FINAL: {final_path}", logfile)

        if final_path.exists() and final_path.resolve() != infile.resolve():
            self.log_message("SKIP — clean final filename already exists; source untouched.", logfile)
            return

        self.remove_if_exists(temp_encode)
        self.remove_if_exists(temp_mux)

        try:
            probe = self.probe_file(infile)
            source = self.source_info(probe)
            self.log_source_summary(probe, source, logfile)

            self.log_message(
                f"RATE CONTROL: average video bitrate={video_kbps} kb/s "
                f"mode={pass_mode} resolution={self.resolution.get()} "
                f"scaler={self.scaler_label.get()}",
                logfile,
            )

            passlog = infile.with_name(f".__MS_PASSLOG__{infile.stem}")
            self.remove_passlog_files(passlog)

            if pass_mode == "Two-pass":
                first_pass_cmd = self.build_ffmpeg_first_pass_command(
                    infile, source, video_kbps, preset, tune, scaler, passlog
                )
                self.log_message("\nFFMPEG FIRST PASS COMMAND:", logfile)
                self.log_message(self.command_text(first_pass_cmd), logfile)
                first_pass_result = self.run_live_command(
                    first_pass_cmd, logfile, "FFMPEG PASS 1"
                )
                if first_pass_result != 0:
                    raise RuntimeError(
                        f"FFmpeg first pass returned code {first_pass_result}."
                    )

            encode_cmd = self.build_ffmpeg_command(
                infile,
                temp_encode,
                source,
                video_kbps,
                preset,
                tune,
                scaler,
                pass_mode,
                passlog,
            )
            self.log_message(
                "\nFFMPEG SECOND PASS COMMAND:"
                if pass_mode == "Two-pass"
                else "\nFFMPEG ONE-PASS COMMAND:",
                logfile,
            )
            self.log_message(self.command_text(encode_cmd), logfile)

            encode_result = self.run_live_command(
                encode_cmd,
                logfile,
                "FFMPEG PASS 2" if pass_mode == "Two-pass" else "FFMPEG",
            )
            if encode_result != 0:
                raise RuntimeError(f"FFmpeg returned code {encode_result}.")

            self.remove_passlog_files(passlog)

            if not temp_encode.exists() or temp_encode.stat().st_size == 0:
                raise RuntimeError("FFmpeg did not create a usable temporary output.")

            mux_cmd = self.build_mkvmerge_command(temp_encode, temp_mux, source)
            self.log_message("\nMKVTOOLNIX CLEANUP COMMAND:", logfile)
            self.log_message(self.command_text(mux_cmd), logfile)

            mux_result = self.run_live_command(mux_cmd, logfile, "MKVMERGE")
            if mux_result not in (0, 1):
                raise RuntimeError(f"mkvmerge returned code {mux_result}.")

            report = self.verify_final(source, temp_mux)
            self.log_verification(report, logfile)

            orig_dir = infile.parent / "orig"
            orig_dir.mkdir(exist_ok=True)
            orig_path = self.unique_orig_path(orig_dir / infile.name)

            shutil.move(str(infile), str(orig_path))
            self.log_message(f"ORIGINAL MOVED: {orig_path}", logfile)

            try:
                temp_mux.replace(final_path)
            except Exception:
                if not infile.exists() and orig_path.exists():
                    shutil.move(str(orig_path), str(infile))
                raise

            self.remove_if_exists(temp_encode)
            self.remove_passlog_files(infile.with_name(f".__MS_PASSLOG__{infile.stem}"))
            elapsed = time.time() - started
            self.log_message(f"FINAL PROMOTED: {final_path}", logfile)
            self.log_message(f"SUCCESS — elapsed {self.format_duration(elapsed)}", logfile)

        except Exception as exc:
            self.log_message(f"FAILED — {type(exc).__name__}: {exc}", logfile)
            self.remove_if_exists(temp_encode)
            self.remove_if_exists(temp_mux)
            self.remove_passlog_files(infile.with_name(f".__MS_PASSLOG__{infile.stem}"))
            self.log_message("Source left untouched; no orig move performed.", logfile)

    def build_ffmpeg_first_pass_command(
        self,
        infile: Path,
        source: SourceInfo,
        video_bitrate_kbps: int,
        preset: str,
        tune: str,
        scaler: str,
        passlog: Path,
    ) -> list[str]:
        cmd = [
            self.resolve_tool("ffmpeg") or "ffmpeg",
            "-y", "-hide_banner", "-loglevel", "info", "-stats",
            "-i", str(infile),
            "-map", "0:v:0",
        ]
        cmd += self.build_video_options(
            video_bitrate_kbps, preset, tune, scaler, pass_number=1, passlog=passlog
        )
        cmd += [
            "-an", "-sn", "-dn",
            "-f", "null",
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

        cmd += ["-map", "0:t?"]
        cmd += ["-map_metadata", "-1", "-map_chapters", "0"]

        cmd += self.build_video_options(
            video_bitrate_kbps,
            preset,
            tune,
            scaler,
            pass_number=2 if pass_mode == "Two-pass" else None,
            passlog=passlog if pass_mode == "Two-pass" else None,
        )
        cmd += [
            "-metadata:s:v:0", "language=und",
            "-metadata:s:v:0", "title=",
        ]
        cmd += self.build_audio_options(source)

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
        """Return the complete Joe Standard video option block."""
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
            options += [
                "-pass", str(pass_number),
                "-passlogfile", str(passlog),
            ]

        return options

    @staticmethod
    def build_audio_options(source: SourceInfo) -> list[str]:
        """Return the complete Joe Standard audio option block."""
        return [
            "-c:a", "aac",
            "-ac", "2",
            "-b:a", f"{AUDIO_BITRATE_KBPS}k",
            "-ar", "48000",
            "-metadata:s:a:0", f"language={source.audio_language}",
            "-metadata:s:a:0", "title=",
        ]

    def build_mkvmerge_command(
        self,
        infile: Path,
        outfile: Path,
        source: SourceInfo,
    ) -> list[str]:
        identify = self.identify_mkv(infile)
        tracks = identify.get("tracks", [])

        cmd = [
            self.resolve_tool("mkvmerge") or "mkvmerge",
            "-o", str(outfile),
            "--no-global-tags",
            "--no-track-tags",
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
                    if subtitle_number < len(source.subtitles)
                    else False
                )
                cmd += [
                    "--language", f"{tid}:eng",
                    "--track-name", f"{tid}:{'SDH' if is_sdh else ''}",
                ]
                subtitle_number += 1

        cmd.append(str(infile))
        return cmd

    def verify_final(self, source: SourceInfo, outfile: Path) -> dict[str, Any]:
        if not outfile.exists() or outfile.stat().st_size < MIN_OUTPUT_MIB * 1024 * 1024:
            raise RuntimeError("Final candidate is missing or implausibly small.")

        probe = self.probe_file(outfile)
        duration = self.get_duration(probe)
        if abs(duration - source.duration) > DURATION_TOLERANCE_SECONDS:
            raise RuntimeError(
                f"Duration differs from source by {abs(duration - source.duration):.2f} seconds."
            )

        streams = probe.get("streams", [])
        video = [s for s in streams if s.get("codec_type") == "video"]
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        subs = [s for s in streams if s.get("codec_type") == "subtitle"]

        if len(video) != 1:
            raise RuntimeError(f"Expected one video stream; found {len(video)}.")
        if len(audio) != 1:
            raise RuntimeError(f"Expected one audio stream; found {len(audio)}.")
        if len(subs) != len(source.subtitles):
            raise RuntimeError(
                f"Expected {len(source.subtitles)} subtitle(s); found {len(subs)}."
            )

        v = video[0]
        a = audio[0]

        if v.get("codec_name") != "h264":
            raise RuntimeError(f"Video codec is {v.get('codec_name')}, not H.264.")
        if v.get("pix_fmt") != "yuv420p":
            raise RuntimeError(f"Video pixel format is {v.get('pix_fmt')}, not yuv420p.")
        if str(v.get("tags", {}).get("language", "und")).lower() not in {"und", ""}:
            raise RuntimeError("Video language is not Unknown/und.")
        if self.track_title(v):
            raise RuntimeError("Video title field is not absent.")

        if a.get("codec_name") != "aac" or int(a.get("channels", 0)) != 2:
            raise RuntimeError("Audio is not AAC stereo.")
        if self.track_title(a):
            raise RuntimeError("Audio title field is not absent.")

        for index, stream in enumerate(subs):
            lang = str(stream.get("tags", {}).get("language", "")).lower()
            if lang not in ENGLISH_CODES:
                raise RuntimeError(f"Subtitle {index + 1} language is not English.")

            expected_title = "SDH" if source.subtitles[index].is_sdh else ""
            actual_title = self.track_title(stream)
            if actual_title != expected_title:
                raise RuntimeError(
                    f"Subtitle {index + 1} title is {actual_title!r}; expected {expected_title!r}."
                )

        format_tags = probe.get("format", {}).get("tags", {}) or {}
        if str(format_tags.get("title", "")).strip():
            raise RuntimeError("Container title field is not absent.")

        size_bytes = outfile.stat().st_size
        overall_kbps = size_bytes * 8 / duration / 1000
        measured_audio_kbps = self.measure_packet_bitrate(outfile, "a:0", duration)
        measured_video_kbps = self.measure_packet_bitrate(outfile, "v:0", duration)

        return {
            "duration": duration,
            "size_mib": size_bytes / 1024 / 1024,
            "overall_kbps": overall_kbps,
            "video_kbps": measured_video_kbps,
            "audio_kbps": measured_audio_kbps,
            "video_count": len(video),
            "audio_count": len(audio),
            "subtitle_count": len(subs),
            "chapters": len(probe.get("chapters", [])),
        }

    def measure_packet_bitrate(self, infile: Path, selector: str, duration: float) -> float:
        cmd = [
            self.resolve_tool("ffprobe") or "ffprobe",
            "-v", "error",
            "-select_streams", selector,
            "-show_entries", "packet=size",
            "-of", "csv=p=0",
            str(infile),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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

    def source_info(self, probe: dict[str, Any]) -> SourceInfo:
        duration = self.get_duration(probe)
        streams = probe.get("streams", [])
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        if not audio_streams:
            raise RuntimeError("Source contains no audio stream.")

        audio_language = self.normalize_language(
            audio_streams[0].get("tags", {}).get("language"),
            fallback="eng",
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

            subtitles.append(
                SubtitleSelection(
                    source_index=int(stream["index"]),
                    language="eng",
                    is_sdh=is_sdh,
                    codec_name=str(stream.get("codec_name", "unknown")),
                )
            )

        return SourceInfo(
            duration=duration,
            audio_language=audio_language,
            subtitles=subtitles,
            has_chapters=bool(probe.get("chapters")),
        )

    def probe_file(self, infile: Path) -> dict[str, Any]:
        cmd = [
            self.resolve_tool("ffprobe") or "ffprobe",
            "-v", "error",
            "-show_streams",
            "-show_format",
            "-show_chapters",
            "-of", "json",
            str(infile),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffprobe failed.")

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Could not parse ffprobe output: {exc}") from exc

    def identify_mkv(self, infile: Path) -> dict[str, Any]:
        cmd = [self.resolve_tool("mkvmerge") or "mkvmerge", "-J", str(infile)]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "mkvmerge identification failed.")

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Could not parse mkvmerge JSON: {exc}") from exc

    def log_source_summary(
        self,
        probe: dict[str, Any],
        source: SourceInfo,
        logfile: Path,
    ) -> None:
        streams = probe.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})

        self.log_message(
            "SOURCE INSPECTION:\n"
            f"  Duration: {self.format_duration(source.duration)}\n"
            f"  Video: {video.get('codec_name', '?')} "
            f"{video.get('width', '?')}x{video.get('height', '?')} "
            f"{video.get('pix_fmt', '?')}\n"
            f"  Audio: {audio.get('codec_name', '?')} "
            f"{audio.get('channels', '?')}ch language={source.audio_language}\n"
            f"  English subtitles selected automatically: {len(source.subtitles)}\n"
            f"  Chapters present: {'yes' if source.has_chapters else 'no'}",
            logfile,
        )

        for number, subtitle in enumerate(source.subtitles, start=1):
            self.log_message(
                f"    Subtitle {number}: source stream {subtitle.source_index}, "
                f"codec={subtitle.codec_name}, "
                f"title={'SDH' if subtitle.is_sdh else '<absent>'}",
                logfile,
            )

    def log_verification(self, report: dict[str, Any], logfile: Path) -> None:
        self.log_message(
            "\nFINAL VERIFICATION PASSED:\n"
            f"  Size: {report['size_mib']:.1f} MiB\n"
            f"  Duration: {self.format_duration(report['duration'])}\n"
            f"  Overall calculated bitrate: {report['overall_kbps']:.0f} kb/s\n"
            f"  Measured video packet bitrate: {report['video_kbps']:.0f} kb/s\n"
            f"  Measured audio packet bitrate: {report['audio_kbps']:.0f} kb/s "
            f"({AUDIO_BITRATE_KBPS} kb/s target)\n"
            f"  Streams: video={report['video_count']} audio={report['audio_count']} "
            f"subtitles={report['subtitle_count']} chapters={report['chapters']}\n"
            "  Titles/languages/subtitle policy: verified",
            logfile,
        )

    def run_live_command(self, cmd: list[str], logfile: Path, phase: str) -> int:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )

        assert process.stdout is not None
        for line in process.stdout:
            clean = line.rstrip()
            if clean:
                self.log_message(f"[{phase}] {clean}", logfile)

        return process.wait()

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
        words = []
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
                if path.name.startswith(".__MS_"):
                    continue
                files.append(path)

        return sorted(files, key=lambda p: str(p).lower())

    def build_video_filter(self, scaler: str) -> str:
        """
        Return the complete Joe Standard video filter chain.

        yadif only acts on frames marked interlaced. Standard progressive material
        passes through unchanged. Fixed-resolution modes preserve aspect ratio,
        never upscale, and pad to a conventional 16:9 canvas without distortion.
        """
        filters = ["yadif=deint=interlaced"]

        selected = self.resolution.get()
        if selected == "1080":
            filters += [
                (
                    "scale='min(iw,1920)':'min(ih,1080)':"
                    "force_original_aspect_ratio=decrease:"
                    f"force_divisible_by=2:flags={scaler}"
                ),
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black",
            ]
        elif selected == "720":
            filters += [
                (
                    "scale='min(iw,1280)':'min(ih,720)':"
                    "force_original_aspect_ratio=decrease:"
                    f"force_divisible_by=2:flags={scaler}"
                ),
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black",
            ]

        return ",".join(filters)

    @staticmethod
    def normalize_language(value: Any, fallback: str = "eng") -> str:
        raw = str(value or "").lower().strip()
        if raw in ENGLISH_CODES:
            return "eng"
        if re.fullmatch(r"[a-z]{3}", raw):
            return raw
        return fallback

    @staticmethod
    def track_title(stream: dict[str, Any]) -> str:
        return str(stream.get("tags", {}).get("title", "")).strip()

    @staticmethod
    def get_duration(probe: dict[str, Any]) -> float:
        try:
            duration = float(probe["format"]["duration"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Duration unavailable.") from exc

        if duration <= 0:
            raise RuntimeError("Invalid duration.")
        return duration

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
    def remove_if_exists(path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    @staticmethod
    def remove_passlog_files(passlog: Path) -> None:
        """Remove x264 two-pass statistics without touching unrelated files."""
        parent = passlog.parent
        prefix = passlog.name
        try:
            for candidate in parent.glob(prefix + "*"):
                if candidate.is_file():
                    candidate.unlink()
        except OSError:
            pass

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

    def write_header(
        self,
        logfile: Path,
        video_kbps: int,
        pass_mode: str,
        preset: str,
        tune: str,
        scaler: str,
        count: int,
    ) -> None:
        self.log_message("\n" + "#" * 78, logfile)
        self.log_message(
            f"Media Standardizer v{APP_VERSION} run\n"
            f"Average video bitrate={video_kbps} kb/s "
            f"mode={pass_mode} preset={preset} tune={tune or 'none'} "
            f"scaler={self.scaler_label.get()} resolution={self.resolution.get()}\n"
            f"Audio=AAC LC stereo {AUDIO_BITRATE_KBPS} kb/s total\n"
            "Locked subtitles=English only; SDH exact; non-English removed\n"
            f"Eligible files={count}",
            logfile,
        )

    def log_message(self, message: str, logfile: Path | None = None) -> None:
        self.msg_q.put(("log", message))

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

                if kind == "log":
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

    @staticmethod
    def command_text(cmd: list[str]) -> str:
        return subprocess.list2cmdline(cmd)

    @staticmethod
    def format_duration(seconds: float) -> str:
        total = int(round(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"


if __name__ == "__main__":
    App().mainloop()
