"""
Media Wrangler v1.5

Opinionated media maintenance utility.

Existing operations retained:
- Extract editable English subtitles from MKV files.
- Replace embedded subtitles from edited sidecars.
- Quickly screen media for obvious structural problems.

Clean:
- Select a parent folder and process media found beneath it.
- Derive a canonical Movie Title [Year] name from the media filename.
- Create/rename the first-level movie folder and media filename.
- Rename a matching English SRT sidecar to <canonical>.en.srt.
- Remove MKV container and stream titles while preserving SDH as the only
  meaningful subtitle title.
- Move release clutter and uncertain extras to _Trash Review for inspection.
- Never permanently delete review material.
"""

from __future__ import annotations

import csv
import io
import json
import os
import queue
import re
import shutil
import statistics
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext

APP_TITLE = "Media Wrangler v1.5"
MKV_EXT = ".mkv"
MEDIA_EXTS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".ts", ".m2ts", ".mpg", ".mpeg"}
SIDECAR_EXTS = {".srt", ".sub", ".ass", ".ssa", ".vtt"}
SDH_MARKERS = ("sdh", "hearing impaired", "hearing-impaired", "hoh", "closed captions", "cc")
ENGLISH_CODES = {"eng", "en", "english"}
TEMP_MARKER = ".__MEDIA_WRANGLER__"
TRASH_FOLDER = "_Trash Review"

# Files that add no archive value and may be quarantined for review.
TRASH_NAMES = {
    "thumbs.db", "desktop.ini", ".ds_store",
}
TRASH_EXTS = {
    ".nfo", ".txt", ".url", ".lnk", ".sfv", ".md5", ".sha1", ".sha256",
    ".torrent", ".exe", ".bat", ".cmd", ".ps1",
}
TRASH_DIR_NAMES = {
    "sample", "samples", "proof", "screens", "screenshots", "subs", "subtitle", "subtitles",
}

# Release tokens used only after a year or technical anchor is found.
TECH_TOKENS = {
    "480p", "576p", "720p", "1080p", "1080i", "2160p", "4k", "uhd",
    "bluray", "blu-ray", "bdrip", "brrip", "webrip", "web-dl", "webdl",
    "hdtv", "dvdrip", "remux", "proper", "repack", "internal",
    "x264", "h264", "avc", "x265", "h265", "hevc", "10bit", "8bit",
    "hdr", "hdr10", "dv", "dolbyvision", "aac", "ac3", "eac3", "dd",
    "ddp", "dts", "truehd", "atmos", "5.1", "7.1", "2.0", "stereo",
    "web", "webcap", "web-dl", "webdl", "amzn", "nf", "dsnp", "hmax",
}

WARN_GAP_SECONDS = 2.0
FAIL_GAP_SECONDS = 10.0
TIMESTAMP_EPSILON = 0.001
DURATION_WARN_SECONDS = 5.0
DURATION_FAIL_SECONDS = 30.0
MAX_REASONABLE_DIMENSION = 16384
MAX_REASONABLE_OVERALL_BITRATE = 1_000_000_000
MAX_REASONABLE_VIDEO_BITRATE = 500_000_000


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1060x700")
        self.minsize(900, 560)

        self.folder: Path | None = None
        self.running = False
        self.stop_requested = False
        self.msg_q: queue.Queue[tuple[str, str]] = queue.Queue()

        self.mkvmerge = self.find_tool("mkvmerge")
        self.mkvextract = self.find_tool("mkvextract")
        self.mkvpropedit = self.find_tool("mkvpropedit")
        self.ffprobe = self.find_tool("ffprobe")

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
            controls, text="Extract Subtitles", width=18,
            command=lambda: self.start_job("extract"),
        )
        self.extract_button.pack(side="left")

        self.replace_button = tk.Button(
            controls, text="Replace Subtitles", width=18,
            command=lambda: self.start_job("replace"),
        )
        self.replace_button.pack(side="left", padx=(8, 0))

        self.verify_button = tk.Button(
            controls, text="Verify Media", width=18,
            command=lambda: self.start_job("verify"),
        )
        self.verify_button.pack(side="left", padx=(8, 0))

        self.clean_button = tk.Button(
            controls, text="Clean", width=14,
            command=lambda: self.start_job("clean"),
        )
        self.clean_button.pack(side="left", padx=(8, 0))

        self.stop_button = tk.Button(
            controls, text="Stop", width=10, state="disabled",
            command=self.request_stop,
        )
        self.stop_button.pack(side="left", padx=(8, 0))

        self.status = tk.Label(controls, text="Idle", anchor="w")
        self.status.pack(side="left", padx=12)

        tk.Label(self, text="Status / Results", anchor="w").pack(fill="x", padx=10, pady=(6, 0))
        self.results = scrolledtext.ScrolledText(self, height=9, font=("Consolas", 10), wrap="word")
        self.results.pack(fill="x", padx=10, pady=(2, 6))

        tk.Label(self, text="Tool Output", anchor="w").pack(fill="x", padx=10)
        self.log = scrolledtext.ScrolledText(self, font=("Consolas", 10), wrap="word")
        self.log.pack(fill="both", expand=True, padx=10, pady=(2, 10))

        if not self.mkvmerge or not self.mkvextract:
            self.log_message(
                "MKVToolNix was not found automatically.\n"
                "Install MKVToolNix or place mkvmerge.exe and mkvextract.exe on PATH."
            )
        if not self.ffprobe:
            self.log_message(
                "ffprobe was not found automatically.\n"
                "Verify Media requires FFmpeg/ffprobe on PATH or in a common FFmpeg folder."
            )
        if not self.mkvpropedit:
            self.log_message(
                "mkvpropedit was not found automatically.\n"
                "Clean can still rename and folder MP4 media, but MKV title cleanup requires mkvpropedit."
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
        if mode in {"extract", "replace"} and (not self.mkvmerge or not self.mkvextract):
            messagebox.showerror(APP_TITLE, "MKVToolNix was not found. Install it or add it to PATH.")
            return
        if mode == "clean" and not self.mkvpropedit:
            messagebox.showerror(APP_TITLE, "Clean requires mkvpropedit from MKVToolNix.")
            return
        if mode == "verify" and not self.ffprobe:
            messagebox.showerror(APP_TITLE, "ffprobe was not found. Install FFmpeg or add ffprobe to PATH.")
            return

        self.running = True
        self.stop_requested = False
        for button in (self.extract_button, self.replace_button, self.verify_button, self.clean_button):
            button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.results.delete("1.0", "end")
        self.log.delete("1.0", "end")
        threading.Thread(target=self.worker, args=(mode,), daemon=True).start()

    def request_stop(self) -> None:
        self.stop_requested = True
        self.set_status("Stopping after current file...")

    def worker(self, mode: str) -> None:
        assert self.folder is not None
        if mode == "clean":
            self.clean_worker()
            return

        files = sorted(
            path for path in self.folder.rglob("*")
            if path.is_file() and path.suffix.lower() == MKV_EXT and TEMP_MARKER not in path.name
        )
        action = {"extract": "Extract", "replace": "Replace", "verify": "Verify"}[mode]
        started = time.monotonic()
        self.result_message(f"Started {action} — {len(files)} MKV file(s)")
        self.log_message(f"Found {len(files)} MKV file(s) to inspect.\n")

        passed = warned = skipped = failed = 0
        for index, mkv in enumerate(files, start=1):
            if self.stop_requested:
                break
            self.set_status(f"{action} {index} of {len(files)}")
            self.log_message("=" * 78)
            self.log_message(str(mkv))
            try:
                if mode == "extract":
                    result = self.extract_from_file(mkv)
                elif mode == "replace":
                    result = self.replace_in_file(mkv)
                else:
                    result = self.verify_media_file(mkv)
                if result == "success": passed += 1
                elif result == "warning": warned += 1
                elif result == "failed": failed += 1
                else: skipped += 1
            except Exception as exc:
                failed += 1
                self.log_message(f"FAILED: {exc}")
                self.result_message(f"FAIL  {mkv.name} — {exc}")

        stopped = self.stop_requested
        elapsed = self.format_elapsed(time.monotonic() - started)
        summary = (
            f"Finished — pass {passed}, warn {warned}, skipped {skipped}, fail {failed}, elapsed {elapsed}"
            + (" — stopped" if stopped else "")
        )
        self.log_message("\n" + "=" * 78)
        self.log_message(summary)
        self.result_message("-" * 78)
        self.result_message(summary)
        if mode == "verify" and not stopped:
            self.result_message("Quick screening only — PASS means no obvious structural problem was found.")
        self.finish_job(stopped, failed, warned)

    # ------------------------------------------------------------------
    # Clean
    # ------------------------------------------------------------------

    def clean_worker(self) -> None:
        assert self.folder is not None
        root = self.folder
        trash_root = root / TRASH_FOLDER
        started = time.monotonic()

        media_files = sorted(
            p for p in root.rglob("*")
            if p.is_file()
            and p.suffix.lower() in MEDIA_EXTS
            and TRASH_FOLDER not in p.parts
            and TEMP_MARKER not in p.name
        )

        self.result_message(f"Started Clean — {len(media_files)} media file(s)")
        self.log_message(f"Selected parent: {root}")
        self.log_message(f"Found {len(media_files)} media file(s).\n")

        passed = warned = skipped = failed = 0
        processed_sources: set[Path] = set()

        for index, source in enumerate(media_files, start=1):
            if self.stop_requested:
                break
            if not source.exists() or source in processed_sources:
                continue

            self.set_status(f"Clean {index} of {len(media_files)}")
            self.log_message("=" * 78)
            self.log_message(str(source))

            try:
                canonical, missing_year = self.canonical_movie_name(source.stem)
                if not canonical:
                    warned += 1
                    self.result_message(f"WARN  {source.name} — title could not be determined; unchanged")
                    self.log_message("UNCHANGED: a believable title could not be determined.")
                    continue

                target_dir = root / canonical
                target_media = target_dir / f"{canonical}{source.suffix.lower()}"

                if target_media.exists() and target_media.resolve() != source.resolve():
                    warned += 1
                    self.result_message(f"WARN  {source.name} — destination already exists; unchanged")
                    self.log_message(f"DESTINATION EXISTS: {target_media}")
                    continue

                target_dir.mkdir(parents=True, exist_ok=True)

                # Move and rename the media first. A same-folder rename is atomic.
                if source.resolve() != target_media.resolve():
                    shutil.move(str(source), str(target_media))
                    self.log_message(f"MEDIA: {source.name} -> {target_media}")
                processed_sources.add(target_media)

                sidecar_result = self.move_matching_sidecar(source, target_media)
                if sidecar_result:
                    self.log_message(sidecar_result)

                if target_media.suffix.lower() == MKV_EXT:
                    self.clean_mkv_titles(target_media)

                # Quarantine leftovers only from the media's original immediate folder.
                original_dir = source.parent
                if original_dir.exists() and original_dir != root and original_dir != target_dir:
                    moved = self.quarantine_leftovers(original_dir, trash_root, canonical)
                    if moved:
                        self.log_message(f"QUARANTINED: {moved} item(s) from {original_dir}")
                    self.remove_empty_upward(original_dir, root)

                if missing_year:
                    warned += 1
                    self.result_message(f"WARN  {canonical} — no year found; standardized without year")
                    self.log_message("WARNING: no year found; naming and cleanup completed without [Year].")
                else:
                    self.result_message(f"PASS  {canonical} — named, foldered, titles cleaned")
                    passed += 1

            except Exception as exc:
                failed += 1
                self.log_message(f"FAILED: {exc}")
                self.result_message(f"FAIL  {source.name} — {exc}")

        stopped = self.stop_requested
        elapsed = self.format_elapsed(time.monotonic() - started)
        summary = (
            f"Finished — pass {passed}, warn {warned}, skipped {skipped}, fail {failed}, elapsed {elapsed}"
            + (" — stopped" if stopped else "")
        )
        self.log_message("\n" + "=" * 78)
        self.log_message(summary)
        self.result_message("-" * 78)
        self.result_message(summary)
        if trash_root.exists():
            self.result_message(f"Review quarantined material in: {trash_root}")
        self.finish_job(stopped, failed, warned)

    def canonical_movie_name(self, stem: str) -> tuple[str | None, bool]:
        """Return (canonical name, missing_year).

        A missing year is no longer fatal. The title is still standardized and
        Clean reports a warning after completing the work.
        """
        text = stem.strip()
        year: str | None = None
        title_part = text

        # Existing bracketed year is authoritative.
        bracket = re.search(r"\[(19\d{2}|20\d{2})\]", text)
        if bracket:
            year = bracket.group(1)
            title_part = text[:bracket.start()]
        else:
            # Prefer a year preceding an obvious release anchor.
            matches = list(re.finditer(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", text))
            chosen = None
            for match in matches:
                tail = text[match.end():].lower().replace("_", ".").replace("-", ".")
                tokens = {t for t in re.split(r"[^a-z0-9.]+|\.+", tail) if t}
                if tokens & TECH_TOKENS or re.search(r"\b(?:480p|576p|720p|1080[pi]|2160p|bluray|web[- .]?dl|webrip)\b", tail):
                    chosen = match
                    break
            if chosen is None and matches:
                last = matches[-1]
                if not text[last.end():].strip(" ._-()[]"):
                    chosen = last
            if chosen is not None:
                year = chosen.group(1)
                title_part = text[:chosen.start()]
            else:
                # No year: cut at the first strong technical/release anchor,
                # otherwise use the complete stem and continue with a warning.
                anchor = re.search(
                    r"(?i)(?:^|[ ._\-])(?:480p|576p|720p|1080p|1080i|2160p|4k|uhd|"
                    r"blu[ ._-]?ray|bdrip|brrip|web[ ._-]?dl|webrip|hdtv|dvdrip|remux|"
                    r"x264|h[ ._-]?264|x265|h[ ._-]?265|hevc|avc)(?=$|[ ._\-])",
                    text,
                )
                if anchor:
                    title_part = text[:anchor.start()]

        title = re.sub(r"[._]+", " ", title_part)

        # Canonical subtitle punctuation: exactly space-dash-space. Colons and
        # spaced dash variants are treated as title/subtitle separators. A
        # closed hyphen inside a word (Spider-Man) is preserved.
        title = re.sub(r"\s*[:–—]\s*", " - ", title)
        title = re.sub(r"\s+-\s+|\s+-|-(?=\s+)", " - ", title)
        title = re.sub(r"\s+", " ", title).strip(" ._-")
        if not title:
            return None, year is None

        # Conservative title casing: preserve mixed capitalization; normalize
        # filenames that are entirely lower- or upper-case.
        if title == title.lower() or title == title.upper():
            small = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with"}
            words = title.lower().split()
            title = " ".join(
                word if i and word in small else word[:1].upper() + word[1:]
                for i, word in enumerate(words)
            )

        title = re.sub(r'[<>:"/\\|?*]', "", title).strip()
        if not title:
            return None, year is None
        canonical = f"{title} [{year}]" if year else title
        return canonical, year is None

    def move_matching_sidecar(self, old_media: Path, new_media: Path) -> str | None:
        candidates: list[Path] = []
        if old_media.parent.exists():
            for path in old_media.parent.iterdir():
                if not path.is_file() or path.suffix.lower() not in SIDECAR_EXTS:
                    continue
                normalized = path.stem.lower()
                media_stem = old_media.stem.lower()
                if normalized == media_stem or normalized.startswith(media_stem + ".") or normalized.startswith(media_stem + " "):
                    candidates.append(path)

        srt_candidates = [p for p in candidates if p.suffix.lower() == ".srt"]
        if not srt_candidates:
            return None

        ordinary = [p for p in srt_candidates if not any(m in p.stem.lower() for m in SDH_MARKERS)]
        chosen = ordinary[0] if ordinary else srt_candidates[0]
        destination = new_media.with_name(f"{new_media.stem}.en.srt")
        if destination.exists() and destination.resolve() != chosen.resolve():
            return f"SIDECAR SKIPPED: destination exists: {destination.name}"
        if chosen.resolve() != destination.resolve():
            shutil.move(str(chosen), str(destination))
        return f"SIDECAR: {chosen.name} -> {destination.name}"

    def clean_mkv_titles(self, mkv: Path) -> None:
        """Normalize MKV titles in place without remuxing the media payload."""
        if not self.mkvpropedit:
            raise RuntimeError("mkvpropedit was not found")

        info = self.probe(mkv)
        cmd = [self.mkvpropedit, str(mkv), "--edit", "info", "--delete", "title"]

        expected_by_uid: dict[int, str] = {}
        for track in info.get("tracks", []):
            props = track.get("properties", {})
            uid = props.get("uid")
            if uid is None:
                raise RuntimeError(f"MKV title cleanup could not identify track UID {track.get('id')}")

            existing_title = str(props.get("track_name", "")).strip()
            keep_sdh = (
                track.get("type") == "subtitles"
                and any(marker in existing_title.lower() for marker in SDH_MARKERS)
            )
            expected = "SDH" if keep_sdh else ""
            expected_by_uid[int(uid)] = expected

            cmd.extend(["--edit", f"track:={uid}"])
            if keep_sdh:
                cmd.extend(["--set", "name=SDH"])
            else:
                cmd.extend(["--delete", "name"])

        self.log_message("MKV TITLE METHOD: mkvpropedit in-place (no remux)")
        result = self.run_command(cmd)
        if result.returncode not in (0, 1):
            raise RuntimeError("MKV title cleanup failed")

        new_info = self.probe(mkv)
        if self.full_track_signature(info) != self.full_track_signature(new_info):
            raise RuntimeError("MKV title cleanup verification failed: track structure changed")

        container_title = str(new_info.get("container", {}).get("properties", {}).get("title", "")).strip()
        if container_title:
            raise RuntimeError("MKV title cleanup verification failed: container title remains")

        for track in new_info.get("tracks", []):
            props = track.get("properties", {})
            uid = props.get("uid")
            title = str(props.get("track_name", "")).strip()
            expected = expected_by_uid.get(int(uid), "") if uid is not None else ""
            if title != expected:
                raise RuntimeError(f"MKV title cleanup verification failed on track {track.get('id')}")

        self.log_message("MKV TITLES: container and stream titles normalized in place")

    def quarantine_leftovers(self, folder: Path, trash_root: Path, canonical: str) -> int:
        if not folder.exists():
            return 0
        destination_root = trash_root / canonical
        moved = 0
        for item in list(folder.iterdir()):
            if item.name.startswith(TEMP_MARKER):
                continue
            should_move = False
            if item.is_dir() and item.name.lower() in TRASH_DIR_NAMES:
                should_move = True
            elif item.is_file():
                if item.name.lower() in TRASH_NAMES or item.suffix.lower() in TRASH_EXTS:
                    should_move = True
                elif item.suffix.lower() in SIDECAR_EXTS:
                    should_move = True
                elif item.suffix.lower() not in MEDIA_EXTS:
                    # Unknown extras are quarantined, not deleted.
                    should_move = True
            if not should_move:
                continue

            destination_root.mkdir(parents=True, exist_ok=True)
            destination = self.unique_destination(destination_root / item.name)
            shutil.move(str(item), str(destination))
            moved += 1
        return moved

    @staticmethod
    def unique_destination(path: Path) -> Path:
        if not path.exists():
            return path
        counter = 2
        while True:
            candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def remove_empty_upward(folder: Path, stop: Path) -> None:
        current = folder
        while current != stop and stop in current.parents:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    @staticmethod
    def full_track_signature(info: dict) -> list[tuple]:
        signature = []
        for track in info.get("tracks", []):
            props = track.get("properties", {})
            signature.append((
                track.get("id"), track.get("type"), track.get("codec"),
                props.get("pixel_dimensions"), props.get("audio_channels"),
                props.get("audio_sampling_frequency"), props.get("language"),
            ))
        return signature

    # ------------------------------------------------------------------
    # Existing subtitle functions retained
    # ------------------------------------------------------------------

    def extract_from_file(self, mkv: Path) -> str:
        info = self.probe(mkv)
        ordinary = None
        sdh = None
        for track in info.get("tracks", []):
            if track.get("type") != "subtitles":
                continue
            props = track.get("properties", {})
            language = str(props.get("language", "")).lower()
            language_ietf = str(props.get("language_ietf", "")).lower()
            title = str(props.get("track_name", "")).strip()
            text = f"{title} {language} {language_ietf}".lower()
            is_english = language in ENGLISH_CODES or language_ietf.startswith("en") or "english" in text
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
            self.result_message(f"SKIP  {mkv.name} — no English text subtitle")
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
        if extracted:
            self.result_message(f"PASS  {mkv.name} — extracted {extracted} subtitle track(s)")
            return "success"
        self.result_message(f"SKIP  {mkv.name} — nothing extracted")
        return "skipped"

    def replace_in_file(self, mkv: Path) -> str:
        ordinary = mkv.with_suffix(".srt")
        sdh = mkv.with_name(f"{mkv.stem} SDH.srt")
        sidecars: list[tuple[Path, bool]] = []
        if ordinary.exists(): sidecars.append((ordinary, False))
        if sdh.exists(): sidecars.append((sdh, True))
        if not sidecars:
            self.log_message("SKIPPED: no matching edited SRT sidecar found.")
            self.result_message(f"SKIP  {mkv.name} — no edited SRT sidecar")
            return "skipped"
        for path, _ in sidecars:
            if path.stat().st_size == 0:
                raise RuntimeError(f"sidecar is empty: {path.name}")

        original_info = self.probe(mkv)
        original_non_sub = self.non_subtitle_signature(original_info)
        temp = mkv.with_name(f"{TEMP_MARKER}{mkv.name}")
        temp.unlink(missing_ok=True)
        cmd = [self.mkvmerge, "--output", str(temp), "--title", "", "--no-subtitles", str(mkv)]
        for sidecar, is_sdh in sidecars:
            cmd.extend([
                "--language", "0:eng", "--track-name", f"0:{'SDH' if is_sdh else ''}",
                "--default-track-flag", "0:no", "--forced-display-flag", "0:no", str(sidecar),
            ])
        result = self.run_command(cmd)
        if result.returncode not in (0, 1):
            temp.unlink(missing_ok=True)
            raise RuntimeError(f"mkvmerge failed with return code {result.returncode}")
        if not temp.exists() or temp.stat().st_size < 1024:
            temp.unlink(missing_ok=True)
            raise RuntimeError("temporary MKV was not created correctly")
        new_info = self.probe(temp)
        if original_non_sub != self.non_subtitle_signature(new_info):
            temp.unlink(missing_ok=True)
            raise RuntimeError("verification failed: non-subtitle track structure changed")
        subtitle_tracks = [t for t in new_info.get("tracks", []) if t.get("type") == "subtitles"]
        if len(subtitle_tracks) != len(sidecars):
            temp.unlink(missing_ok=True)
            raise RuntimeError(f"verification failed: expected {len(sidecars)} subtitle track(s), found {len(subtitle_tracks)}")
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
                raise RuntimeError(f"verification failed: subtitle title {title or '<absent>'}, expected {expected_title or '<absent>'}")
        os.replace(temp, mkv)
        for sidecar, _ in sidecars:
            sidecar.unlink()
        self.log_message("REPLACED: embedded subtitles updated; edited sidecars deleted; finished MKV retained.")
        self.result_message(f"PASS  {mkv.name} — embedded subtitles replaced")
        return "success"

    # ------------------------------------------------------------------
    # Quick media triage retained
    # ------------------------------------------------------------------

    def verify_media_file(self, mkv: Path) -> str:
        assert self.ffprobe is not None
        started = time.monotonic()
        warn_reasons: list[str] = []
        fail_reasons: list[str] = []
        metadata_cmd = [
            self.ffprobe, "-v", "warning", "-show_entries",
            "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,duration,start_time,bit_rate,avg_frame_rate,r_frame_rate",
            "-of", "json", str(mkv),
        ]
        metadata = self.run_ffprobe_json(metadata_cmd, "metadata")
        streams = metadata.get("streams", [])
        format_info = metadata.get("format", {})
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        if not video_streams: fail_reasons.append("no video stream")
        if not audio_streams: warn_reasons.append("no audio stream")
        format_duration = self.safe_float(format_info.get("duration"))
        format_size = self.safe_int(format_info.get("size"))
        overall_bitrate = self.safe_int(format_info.get("bit_rate"))
        if format_duration is None or format_duration <= 0: fail_reasons.append("missing or invalid container duration")
        if format_size is None or format_size <= 0: fail_reasons.append("missing or invalid file size")
        if overall_bitrate is None and format_duration and format_size:
            overall_bitrate = int((format_size * 8) / format_duration)
        if overall_bitrate is not None:
            if overall_bitrate <= 0: warn_reasons.append("reported overall bitrate is invalid")
            elif overall_bitrate > MAX_REASONABLE_OVERALL_BITRATE:
                warn_reasons.append(f"implausible overall bitrate {self.format_bitrate(overall_bitrate)}")
        if video_streams:
            video = video_streams[0]
            width = self.safe_int(video.get("width")); height = self.safe_int(video.get("height"))
            video_bitrate = self.safe_int(video.get("bit_rate")); video_duration = self.safe_float(video.get("duration"))
            if width is None or height is None or width <= 0 or height <= 0:
                fail_reasons.append("missing or invalid video geometry")
            elif width > MAX_REASONABLE_DIMENSION or height > MAX_REASONABLE_DIMENSION:
                warn_reasons.append(f"implausible geometry {width}x{height}")
            if video_bitrate is not None:
                if video_bitrate <= 0: warn_reasons.append("reported video bitrate is invalid")
                elif video_bitrate > MAX_REASONABLE_VIDEO_BITRATE:
                    warn_reasons.append(f"implausible video bitrate {self.format_bitrate(video_bitrate)}")
            if format_duration and video_duration:
                difference = abs(format_duration - video_duration)
                if difference > DURATION_FAIL_SECONDS: fail_reasons.append(f"video/container duration mismatch {difference:.1f}s")
                elif difference > DURATION_WARN_SECONDS: warn_reasons.append(f"video/container duration mismatch {difference:.1f}s")
        if audio_streams and format_duration:
            audio_duration = self.safe_float(audio_streams[0].get("duration"))
            if audio_duration:
                difference = abs(format_duration - audio_duration)
                if difference > DURATION_FAIL_SECONDS: fail_reasons.append(f"audio/container duration mismatch {difference:.1f}s")
                elif difference > DURATION_WARN_SECONDS: warn_reasons.append(f"audio/container duration mismatch {difference:.1f}s")

        packet_cmd = [
            self.ffprobe, "-v", "warning", "-select_streams", "v:0",
            "-show_entries", "packet=pts_time,dts_time,duration_time", "-of", "csv=p=0", str(mkv),
        ]
        packet_result = self.run_ffprobe_text(packet_cmd, "primary video packets")
        packet_count = 0; pts_values: list[float] = []; positive_durations: list[float] = []
        previous_dts: float | None = None; backward_dts = 0
        for row in csv.reader(io.StringIO(packet_result)):
            if self.stop_requested: break
            packet_count += 1
            pts = self.safe_float(row[0] if len(row) > 0 else None)
            dts = self.safe_float(row[1] if len(row) > 1 else None)
            duration = self.safe_float(row[2] if len(row) > 2 else None)
            if pts is not None: pts_values.append(pts)
            if duration is not None and duration > 0: positive_durations.append(duration)
            if dts is not None:
                if previous_dts is not None and dts + TIMESTAMP_EPSILON < previous_dts: backward_dts += 1
                previous_dts = dts
        if packet_count == 0 or len(pts_values) < 2:
            fail_reasons.append("primary video packet timestamps could not be read")
        else:
            typical_frame = statistics.median(positive_durations) if positive_durations else 1 / 24
            sorted_pts = sorted(set(pts_values)); largest_gap = largest_start = largest_end = 0.0
            previous_pts = sorted_pts[0]
            for current_pts in sorted_pts[1:]:
                gap = current_pts - previous_pts
                if gap > largest_gap:
                    largest_gap, largest_start, largest_end = gap, previous_pts, current_pts
                previous_pts = current_pts
            effective_warn_gap = max(WARN_GAP_SECONDS, typical_frame * 12)
            if largest_gap >= FAIL_GAP_SECONDS:
                fail_reasons.append(f"video timestamp gap {self.format_timestamp(largest_start)} -> {self.format_timestamp(largest_end)} ({largest_gap:.3f}s)")
            elif largest_gap >= effective_warn_gap:
                warn_reasons.append(f"video timestamp gap {self.format_timestamp(largest_start)} -> {self.format_timestamp(largest_end)} ({largest_gap:.3f}s)")
        if backward_dts:
            if backward_dts > 5: fail_reasons.append(f"{backward_dts} backward DTS steps")
            else: warn_reasons.append(f"{backward_dts} backward DTS step(s)")

        elapsed = self.format_elapsed(time.monotonic() - started)
        details = self.media_details(format_info, video_streams, audio_streams, packet_count)
        if fail_reasons:
            reason = fail_reasons[0]; extra = f" (+{len(fail_reasons)-1} more)" if len(fail_reasons) > 1 else ""
            self.result_message(f"FAIL  {mkv.name} — {reason}{extra} — {elapsed}")
            self.log_message("RESULT: FAIL")
            for item in fail_reasons: self.log_message(f"  FAIL: {item}")
            for item in warn_reasons: self.log_message(f"  WARN: {item}")
            self.log_message(details); return "failed"
        if warn_reasons:
            reason = warn_reasons[0]; extra = f" (+{len(warn_reasons)-1} more)" if len(warn_reasons) > 1 else ""
            self.result_message(f"WARN  {mkv.name} — {reason}{extra} — {elapsed}")
            self.log_message("RESULT: WARN")
            for item in warn_reasons: self.log_message(f"  WARN: {item}")
            self.log_message(details); return "warning"
        self.result_message(f"PASS  {mkv.name} — no obvious structural problem — {elapsed}")
        self.log_message("RESULT: PASS"); self.log_message(details); return "success"

    def run_ffprobe_json(self, cmd: list[str], label: str) -> dict:
        output = self.run_ffprobe_process(cmd, label)
        try: return json.loads(output)
        except json.JSONDecodeError as exc: raise RuntimeError(f"ffprobe returned invalid {label} JSON") from exc

    def run_ffprobe_text(self, cmd: list[str], label: str) -> str:
        return self.run_ffprobe_process(cmd, label)

    def run_ffprobe_process(self, cmd: list[str], label: str) -> str:
        self.log_message("COMMAND: " + subprocess.list2cmdline(cmd))
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", creationflags=self.no_window_flag(),
        )
        if result.stderr.strip(): self.log_message(result.stderr.strip())
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe could not read {label} (return code {result.returncode})")
        return result.stdout

    def media_details(self, format_info: dict, video_streams: list[dict], audio_streams: list[dict], packet_count: int) -> str:
        duration = self.safe_float(format_info.get("duration")); bitrate = self.safe_int(format_info.get("bit_rate"))
        parts = []
        if video_streams:
            video = video_streams[0]
            parts.append(f"video {video.get('codec_name','?')} {video.get('width','?')}x{video.get('height','?')}")
        parts.append(f"audio streams {len(audio_streams)}")
        if duration is not None: parts.append(f"duration {self.format_timestamp(duration)}")
        if bitrate is not None: parts.append(f"overall {self.format_bitrate(bitrate)}")
        parts.append(f"video packets {packet_count:,}")
        return "DETAILS: " + "; ".join(parts)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def finish_job(self, stopped: bool, failed: int, warned: int) -> None:
        if stopped: final_status = "Stopped"
        elif failed: final_status = "Failures found"
        elif warned: final_status = "Warnings found"
        else: final_status = "Idle"
        self.msg_q.put(("done", final_status))

    @staticmethod
    def safe_float(value: object) -> float | None:
        if value is None: return None
        text = str(value).strip()
        if not text or text.upper() == "N/A": return None
        try: return float(text)
        except ValueError: return None

    @staticmethod
    def safe_int(value: object) -> int | None:
        if value is None: return None
        text = str(value).strip()
        if not text or text.upper() == "N/A": return None
        try: return int(float(text))
        except ValueError: return None

    @staticmethod
    def format_bitrate(bits_per_second: int) -> str:
        return f"{bits_per_second / 1_000_000:.2f} Mb/s" if bits_per_second >= 1_000_000 else f"{bits_per_second / 1_000:.0f} kb/s"

    @staticmethod
    def format_timestamp(seconds: float) -> str:
        seconds = max(0.0, seconds); hours = int(seconds // 3600); minutes = int((seconds % 3600) // 60); remaining = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{remaining:06.3f}"

    @staticmethod
    def format_elapsed(seconds: float) -> str:
        total = max(0, int(round(seconds))); hours, remainder = divmod(total, 3600); minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def non_subtitle_signature(info: dict) -> list[tuple]:
        signature = []
        for track in info.get("tracks", []):
            if track.get("type") == "subtitles": continue
            props = track.get("properties", {})
            signature.append((track.get("type"), track.get("codec"), props.get("pixel_dimensions"), props.get("audio_channels"), props.get("audio_sampling_frequency")))
        return signature

    def probe(self, path: Path) -> dict:
        result = subprocess.run(
            [self.mkvmerge, "-J", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", creationflags=self.no_window_flag(),
        )
        if result.returncode != 0:
            raise RuntimeError(f"could not inspect {path.name}: {result.stderr.strip()}")
        try: return json.loads(result.stdout)
        except json.JSONDecodeError as exc: raise RuntimeError(f"invalid mkvmerge inspection output for {path.name}") from exc

    def run_command(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.log_message("COMMAND: " + subprocess.list2cmdline(cmd))
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", creationflags=self.no_window_flag(),
        )
        if result.stdout.strip(): self.log_message(result.stdout.strip())
        return result

    @staticmethod
    def find_tool(name: str) -> str | None:
        executable = f"{name}.exe" if os.name == "nt" else name
        found = shutil.which(executable)
        if found: return found
        candidates = [
            Path(r"C:\Program Files\MKVToolNix") / executable,
            Path(r"C:\Program Files (x86)\MKVToolNix") / executable,
            Path(r"C:\Apps\MKVToolNix") / executable,
            Path(r"C:\Program Files\ffmpeg\bin") / executable,
            Path(r"C:\Program Files (x86)\ffmpeg\bin") / executable,
            Path(r"C:\Apps\ffmpeg\bin") / executable,
            Path(r"C:\ffmpeg\bin") / executable,
        ]
        for candidate in candidates:
            if candidate.exists(): return str(candidate)
        return None

    @staticmethod
    def no_window_flag() -> int:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    def log_message(self, message: str) -> None: self.msg_q.put(("log", message))
    def result_message(self, message: str) -> None: self.msg_q.put(("result", message))
    def set_status(self, message: str) -> None: self.msg_q.put(("status", message))

    @staticmethod
    def append_with_follow(widget: scrolledtext.ScrolledText, message: str) -> None:
        _, bottom_fraction = widget.yview(); follow_output = bottom_fraction >= 0.999
        widget.insert("end", message + "\n")
        if follow_output: widget.see("end")

    def poll_messages(self) -> None:
        try:
            while True:
                kind, message = self.msg_q.get_nowait()
                if kind == "log": self.append_with_follow(self.log, message)
                elif kind == "result": self.append_with_follow(self.results, message)
                elif kind == "status": self.status.config(text=message)
                elif kind == "done":
                    self.running = False; self.stop_requested = False; self.status.config(text=message)
                    for button in (self.extract_button, self.replace_button, self.verify_button, self.clean_button):
                        button.config(state="normal")
                    self.stop_button.config(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self.poll_messages)


if __name__ == "__main__":
    App().mainloop()
