"""
Subtitle Wrangler

Folder tool for extracting editable English subtitles from MKV files and
replacing the embedded subtitle tracks after editing.

Requirements:
- MKVToolNix installed (mkvmerge.exe and mkvextract.exe).
- Select a folder; processing is recursive.

Extract Subtitles:
- Extracts at most one ordinary English subtitle and one English SDH subtitle.
- Ordinary:  <video stem>.srt
- SDH:       <video stem> SDH.srt
- Existing sidecars are not overwritten.

Replace Subtitles:
- Copies every non-subtitle part of the MKV unchanged.
- Removes all embedded subtitle tracks.
- Adds the edited sidecars found beside the MKV.
- Ordinary English subtitle: language=eng, title absent.
- English SDH subtitle: language=eng, title exactly SDH.
- Verifies the temporary MKV before replacing the original.
- On success, deletes the used SRT sidecars and leaves only the finished MKV.
- On failure, leaves the original MKV and sidecars untouched.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext

APP_TITLE = "Subtitle Wrangler"
MKV_EXT = ".mkv"
SDH_MARKERS = ("sdh", "hearing impaired", "hearing-impaired", "hoh", "closed captions", "cc")
ENGLISH_CODES = {"eng", "en", "english"}
TEMP_MARKER = ".__SUB_WRANGLER__"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("900x590")
        self.minsize(760, 480)

        self.folder: Path | None = None
        self.running = False
        self.stop_requested = False
        self.msg_q: queue.Queue[tuple[str, str]] = queue.Queue()

        self.mkvmerge = self.find_tool("mkvmerge")
        self.mkvextract = self.find_tool("mkvextract")

        self.build_ui()
        self.after(100, self.poll_messages)

    def build_ui(self) -> None:
        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 5))

        tk.Button(top, text="Choose Folder", width=15, command=self.choose_folder).pack(side="left")

        self.folder_label = tk.Label(top, text="(no folder selected)", anchor="w")
        self.folder_label.pack(side="left", padx=10, fill="x", expand=True)

        controls = tk.Frame(self)
        controls.pack(fill="x", padx=10, pady=5)

        self.extract_button = tk.Button(
            controls,
            text="Extract Subtitles",
            width=18,
            command=lambda: self.start_job("extract"),
        )
        self.extract_button.pack(side="left")

        self.replace_button = tk.Button(
            controls,
            text="Replace Subtitles",
            width=18,
            command=lambda: self.start_job("replace"),
        )
        self.replace_button.pack(side="left", padx=(8, 0))

        self.stop_button = tk.Button(
            controls,
            text="Stop",
            width=10,
            state="disabled",
            command=self.request_stop,
        )
        self.stop_button.pack(side="left", padx=(8, 0))

        self.status = tk.Label(controls, text="Idle", anchor="w")
        self.status.pack(side="left", padx=12)

        self.log = scrolledtext.ScrolledText(self, font=("Consolas", 10), wrap="word")
        self.log.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        if not self.mkvmerge or not self.mkvextract:
            self.log_message(
                "MKVToolNix was not found automatically.\n"
                "Install MKVToolNix or place mkvmerge.exe and mkvextract.exe on PATH."
            )

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory()
        if selected:
            self.folder = Path(selected)
            self.folder_label.config(text=str(self.folder))

    def start_job(self, mode: str) -> None:
        if self.running:
            return

        if not self.folder:
            messagebox.showinfo(APP_TITLE, "Choose a folder first.")
            return

        if not self.mkvmerge or not self.mkvextract:
            messagebox.showerror(
                APP_TITLE,
                "MKVToolNix was not found. Install it or add it to PATH.",
            )
            return

        self.running = True
        self.stop_requested = False
        self.extract_button.config(state="disabled")
        self.replace_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.log.delete("1.0", "end")

        threading.Thread(target=self.worker, args=(mode,), daemon=True).start()

    def request_stop(self) -> None:
        self.stop_requested = True
        self.set_status("Stopping after current file...")

    def worker(self, mode: str) -> None:
        assert self.folder is not None

        files = sorted(
            path for path in self.folder.rglob("*")
            if path.is_file()
            and path.suffix.lower() == MKV_EXT
            and TEMP_MARKER not in path.name
        )

        action = "extract" if mode == "extract" else "replace"
        self.log_message(f"Found {len(files)} MKV file(s) to inspect.\n")

        success = 0
        skipped = 0
        failed = 0

        for index, mkv in enumerate(files, start=1):
            if self.stop_requested:
                break

            self.set_status(f"{action.title()} {index} of {len(files)}")
            self.log_message("=" * 78)
            self.log_message(str(mkv))

            try:
                result = self.extract_from_file(mkv) if mode == "extract" else self.replace_in_file(mkv)
                if result == "success":
                    success += 1
                else:
                    skipped += 1
            except Exception as exc:
                failed += 1
                self.log_message(f"FAILED: {exc}")

        stopped = self.stop_requested
        self.log_message("\n" + "=" * 78)
        self.log_message(
            f"Finished — success {success}, skipped {skipped}, failed {failed}"
            + (" — stopped" if stopped else "")
        )
        self.msg_q.put(("done", "Stopped" if stopped else "Idle"))

    def extract_from_file(self, mkv: Path) -> str:
        info = self.probe(mkv)
        tracks = info.get("tracks", [])

        ordinary = None
        sdh = None

        for track in tracks:
            if track.get("type") != "subtitles":
                continue

            props = track.get("properties", {})
            language = str(props.get("language", "")).lower()
            language_ietf = str(props.get("language_ietf", "")).lower()
            title = str(props.get("track_name", "")).strip()
            text = f"{title} {language} {language_ietf}".lower()

            is_english = (
                language in ENGLISH_CODES
                or language_ietf.startswith("en")
                or "english" in text
            )
            if not is_english:
                continue

            is_sdh = any(marker in text for marker in SDH_MARKERS)

            if is_sdh and sdh is None:
                sdh = track
            elif not is_sdh and ordinary is None:
                ordinary = track

        selected: list[tuple[dict, Path, str]] = []

        if ordinary is not None:
            selected.append((ordinary, mkv.with_suffix(".srt"), "English"))

        if sdh is not None:
            selected.append((sdh, mkv.with_name(f"{mkv.stem} SDH.srt"), "English SDH"))

        if not selected:
            self.log_message("SKIPPED: no English text subtitle found.")
            return "skipped"

        extracted = 0

        for track, output, label in selected:
            codec = str(track.get("codec", "")).lower()
            if "subrip" not in codec and "srt" not in codec:
                self.log_message(f"SKIPPED {label}: unsupported subtitle codec {codec or '<unknown>'}.")
                continue

            if output.exists():
                self.log_message(f"SKIPPED {label}: sidecar already exists: {output.name}")
                continue

            cmd = [self.mkvextract, "tracks", str(mkv), f"{track['id']}:{output}"]
            result = self.run_command(cmd)

            if result.returncode != 0 or not output.exists() or output.stat().st_size == 0:
                output.unlink(missing_ok=True)
                raise RuntimeError(f"subtitle extraction failed for {label}")

            extracted += 1
            self.log_message(f"EXTRACTED: {output.name}")

        return "success" if extracted else "skipped"

    def replace_in_file(self, mkv: Path) -> str:
        ordinary = mkv.with_suffix(".srt")
        sdh = mkv.with_name(f"{mkv.stem} SDH.srt")

        sidecars: list[tuple[Path, bool]] = []
        if ordinary.exists():
            sidecars.append((ordinary, False))
        if sdh.exists():
            sidecars.append((sdh, True))

        if not sidecars:
            self.log_message("SKIPPED: no matching edited SRT sidecar found.")
            return "skipped"

        for path, _ in sidecars:
            if path.stat().st_size == 0:
                raise RuntimeError(f"sidecar is empty: {path.name}")

        original_info = self.probe(mkv)
        original_non_sub = self.non_subtitle_signature(original_info)

        temp = mkv.with_name(f"{TEMP_MARKER}{mkv.name}")
        temp.unlink(missing_ok=True)

        cmd = [
            self.mkvmerge,
            "--output", str(temp),
            "--title", "",
            "--no-subtitles",
            str(mkv),
        ]

        for sidecar, is_sdh in sidecars:
            cmd.extend([
                "--language", "0:eng",
                "--track-name", f"0:{'SDH' if is_sdh else ''}",
                "--default-track-flag", "0:no",
                "--forced-display-flag", "0:no",
                str(sidecar),
            ])

        result = self.run_command(cmd)

        if result.returncode not in (0, 1):
            temp.unlink(missing_ok=True)
            raise RuntimeError(f"mkvmerge failed with return code {result.returncode}")

        if not temp.exists() or temp.stat().st_size < 1024:
            temp.unlink(missing_ok=True)
            raise RuntimeError("temporary MKV was not created correctly")

        new_info = self.probe(temp)
        new_non_sub = self.non_subtitle_signature(new_info)

        if original_non_sub != new_non_sub:
            temp.unlink(missing_ok=True)
            raise RuntimeError("verification failed: non-subtitle track structure changed")

        subtitle_tracks = [
            track for track in new_info.get("tracks", [])
            if track.get("type") == "subtitles"
        ]

        if len(subtitle_tracks) != len(sidecars):
            temp.unlink(missing_ok=True)
            raise RuntimeError(
                f"verification failed: expected {len(sidecars)} subtitle track(s), "
                f"found {len(subtitle_tracks)}"
            )

        expected_titles = ["SDH" if is_sdh else "" for _, is_sdh in sidecars]

        for track, expected_title in zip(subtitle_tracks, expected_titles):
            props = track.get("properties", {})
            language = str(props.get("language", "")).lower()
            title = str(props.get("track_name", "")).strip()

            if language not in ("eng", "en"):
                temp.unlink(missing_ok=True)
                raise RuntimeError("verification failed: subtitle language is not English")

            if title != expected_title:
                temp.unlink(missing_ok=True)
                shown = title or "<absent>"
                wanted = expected_title or "<absent>"
                raise RuntimeError(
                    f"verification failed: subtitle title {shown}, expected {wanted}"
                )

        os.replace(temp, mkv)

        for sidecar, _ in sidecars:
            sidecar.unlink()

        self.log_message(
            "REPLACED: embedded subtitles updated; edited sidecars deleted; "
            "finished MKV retained."
        )
        return "success"

    @staticmethod
    def non_subtitle_signature(info: dict) -> list[tuple]:
        signature = []
        for track in info.get("tracks", []):
            if track.get("type") == "subtitles":
                continue

            props = track.get("properties", {})
            signature.append((
                track.get("type"),
                track.get("codec"),
                props.get("pixel_dimensions"),
                props.get("audio_channels"),
                props.get("audio_sampling_frequency"),
            ))
        return signature

    def probe(self, path: Path) -> dict:
        result = subprocess.run(
            [self.mkvmerge, "-J", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=self.no_window_flag(),
        )

        if result.returncode != 0:
            raise RuntimeError(f"could not inspect {path.name}: {result.stderr.strip()}")

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid mkvmerge inspection output for {path.name}") from exc

    def run_command(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.log_message("COMMAND: " + subprocess.list2cmdline(cmd))
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=self.no_window_flag(),
        )

        output = result.stdout.strip()
        if output:
            self.log_message(output)

        return result

    @staticmethod
    def find_tool(name: str) -> str | None:
        executable = f"{name}.exe" if os.name == "nt" else name

        found = shutil.which(executable)
        if found:
            return found

        candidates = [
            Path(r"C:\Program Files\MKVToolNix") / executable,
            Path(r"C:\Program Files (x86)\MKVToolNix") / executable,
            Path(r"C:\Apps\MKVToolNix") / executable,
        ]

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        return None

    @staticmethod
    def no_window_flag() -> int:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    def log_message(self, message: str) -> None:
        self.msg_q.put(("log", message))

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
                elif kind == "done":
                    self.running = False
                    self.stop_requested = False
                    self.status.config(text=message)
                    self.extract_button.config(state="normal")
                    self.replace_button.config(state="normal")
                    self.stop_button.config(state="disabled")

        except queue.Empty:
            pass

        self.after(100, self.poll_messages)


if __name__ == "__main__":
    App().mainloop()
