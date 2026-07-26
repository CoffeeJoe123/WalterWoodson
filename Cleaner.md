# Cleaner

**Status:** Current  
**Source version:** 2.2.0  
**Last updated:** 2026-07-26

Cleaner prepares curated video media for the WoodPile archive.

It standardizes video, audio, subtitles, naming, container structure, and verification evidence while preserving the source until a trustworthy result has been promoted.

Cleaner is a standardization and confidence pipeline. It is not intended to improve weak source material or prove that every frame and sample is perceptually perfect.

---

## Role

Cleaner owns:

- source inspection,
- preflight continuity analysis,
- H.264 video standardization,
- AAC stereo audio standardization,
- English subtitle selection,
- SRT sidecar intake,
- filename cleanup,
- MKV remuxing,
- output verification,
- transaction-safe promotion,
- source and consumed-sidecar preservation,
- batch reporting.

Cleaner assumes the operator has already decided the source belongs in the collection.

---

## Current WoodPile Standard

Cleaner currently defaults to:

- MKV output,
- H.264 using `libx264`,
- High Profile,
- 8-bit `yuv420p`,
- 1650 kb/s average video bitrate,
- one-pass encoding,
- `fast` preset,
- no tune,
- bicubic scaling,
- AAC LC stereo,
- 192 kb/s total audio bitrate,
- 48 kHz audio,
- English subtitles retained automatically,
- ordinary subtitle title absent,
- SDH subtitle title exactly `SDH`.

The operator may temporarily select:

- one-pass or two-pass,
- `fast`, `medium`, or `slow`,
- no tune, film, animation, or grain,
- bicubic, lanczos, spline, or bilinear scaling,
- 720p, 1080p, or Match Source.

The default remains 1650 kb/s, one-pass, `fast`.

The current decision record states that testing did not show enough quality, deviation, or file-size benefit from slow two-pass encoding to justify the additional runtime. One-pass `fast` reduced encode time by about 78 percent in the recorded comparison.

---

## Content Modes

Cleaner provides two content modes.

### Show

Show mode uses conservative sidecar ownership.

An SRT sidecar belongs to a video only when its normalized filename begins with the complete normalized video stem.

This avoids attaching an unrelated subtitle to the wrong episode in a multi-file folder.

### Movie

Movie mode uses the same filename-matching rule.

When the folder contains exactly one eligible video, every SRT file in that folder is treated as part of that movie package. This supports curated movie folders containing names such as `English.srt` or `SDH.srt`.

Show and Movie currently share encoding defaults. Their difference is file and sidecar policy.

---

## Video Policy

Cleaner encodes the first video stream.

### 720p

- maximum canvas: 1280 × 720,
- H.264 High Profile,
- Level 3.1,
- aspect ratio preserved,
- no upscaling,
- black padding used where necessary,
- dimensions kept divisible by two.

### 1080p

- maximum canvas: 1920 × 1080,
- H.264 High Profile,
- Level 4.1,
- aspect ratio preserved,
- no upscaling,
- black padding used where necessary,
- dimensions kept divisible by two.

### Match Source

- source geometry is retained,
- H.264 High Profile,
- Level 4.1,
- no fixed output canvas is imposed.

Cleaner applies `yadif=deint=interlaced`. Frames marked interlaced are deinterlaced; progressive frames pass through the filter without deliberate deinterlacing.

Cleaner never stretches media to fill the output canvas.

---

## Audio Policy

Cleaner selects the first audio stream and converts it to:

- AAC LC,
- stereo,
- 192 kb/s total,
- 48 kHz.

The source audio language is retained when it is a valid three-letter code. Otherwise Cleaner records it as English.

Alternate audio programs, commentary tracks, and additional audio streams are not retained in the current implementation.

---

## Subtitle Policy

Cleaner retains embedded subtitle streams marked English.

Cleaner also accepts matching external SRT sidecars according to the selected Show or Movie policy.

All retained subtitles are written as English.

Subtitle titles are normalized:

- ordinary subtitle: no title,
- hearing-impaired or SDH subtitle: `SDH`.

SDH detection uses embedded disposition and title evidence. For sidecars, `sdh`, `hoh`, and `cc` are treated as tokens, avoiding false matches inside ordinary words.

Only sidecars actually consumed by a successful job move to `orig`.

External subtitle formats other than SRT are not currently implemented.

---

## Filename Policy

Cleaner normalizes punctuation and spacing and attempts to preserve meaningful movie or episode names while removing recognized technical release tokens.

Episode names are normalized to:

`Show Name SxxExx Episode Title.mkv`

For non-episode material, Cleaner removes recognized technical tokens after the meaningful title and produces an MKV filename.

Filename cleanup is heuristic. It should be treated as a practical convention rather than a complete media-name parser.

---

## Processing Pipeline

For each eligible source Cleaner performs:

1. inspect source structure,
2. identify embedded English subtitles,
3. identify owned SRT sidecars,
4. scan source video and audio timestamp continuity,
5. stop before encoding when fatal source continuity evidence is found,
6. encode video and audio,
7. include selected subtitles,
8. remux with MKVToolNix,
9. verify structure and continuity,
10. move the source and consumed sidecars to `orig`,
11. promote the verified output,
12. record the result and timing evidence,
13. continue the batch.

One failed source does not terminate the remaining batch unless the wrapper itself cannot continue safely.

---

## Transaction Safety

Cleaner does not replace the source in place.

Temporary encode and mux files are created first.

Only after the candidate has passed required verification does Cleaner:

1. move the source video to `orig`,
2. move consumed subtitle sidecars to `orig`,
3. promote the verified candidate to the final path.

Every moved item is recorded.

If promotion fails, Cleaner attempts to restore the source and every consumed sidecar to their original locations.

Unrelated files are not moved.

Temporary files and two-pass logs are removed after success or failure when possible.

If a cleaned final filename already exists as a separate file, Cleaner skips that source rather than overwrite it.

---

## Preflight Integrity Analysis

Cleaner performs timestamp continuity analysis before expensive encoding.

The continuity clock is DTS when available. PTS is used only as a fallback.

This is deliberate. Normal H.264 B-frame reordering can make PTS appear to move backward even when the stream is healthy. Using PTS as the primary clock previously created false corruption findings.

Cleaner records:

- packet count,
- largest timestamp gap,
- gap start and end,
- backward DTS count,
- exact backward-DTS events,
- human-readable inspection locations.

Current thresholds are:

- gap under 2 seconds: diagnostic only,
- gap from 2 seconds through under 10 seconds: WARN,
- gap of 10 seconds or more: FAIL,
- 0 through 10 backward DTS events: diagnostic only,
- 11 through 100 backward DTS events: WARN,
- more than 100 backward DTS events: FAIL.

The current video and audio gap thresholds are the same.

Fatal preflight findings stop that file before encoding. The source remains untouched and the batch continues.

---

## Verification

PASS does not mean only that FFmpeg exited successfully.

Cleaner verifies that the candidate:

- exists,
- is not implausibly small,
- remains within 2 seconds of source duration,
- contains exactly one video stream,
- contains exactly one audio stream,
- uses H.264 video,
- uses `yuv420p`,
- uses AAC stereo,
- has expected title-field normalization,
- has the expected subtitle count or reports a warning,
- has English subtitle language metadata or reports a warning,
- passes output continuity analysis,
- does not introduce a new significant timestamp gap,
- does not enlarge a source gap beyond tolerance.

Cleaner also records:

- output size,
- duration,
- measured video packet bitrate,
- measured audio packet bitrate,
- stream counts.

A source gap preserved in the output is reported honestly. Cleaner does not claim the encoder created damage that was already present.

---

## Result States

### PASS

All required structural checks completed without evidence that currently undermines archive confidence.

### WARN

A usable output was produced and retained, but evidence deserves operator review.

Examples include:

- subtitle count mismatch,
- subtitle language or title mismatch,
- unexpected title metadata,
- a nonfatal timestamp discontinuity,
- a source discontinuity preserved in the output.

### FAIL

Cleaner could not produce and promote a trustworthy output.

Examples include:

- no readable source packets,
- fatal source continuity damage,
- FFmpeg or MKVToolNix failure,
- missing or implausibly small candidate,
- unacceptable duration difference,
- wrong video or audio structure,
- new or enlarged output continuity damage,
- failed promotion.

The source and consumed sidecars remain or are restored whenever Cleaner can do so safely.

### SKIP

Cleaner intentionally did not process the source, normally because the intended final filename already exists.

---

## Interface and Evidence

The upper pane is the persistent batch ledger.

It answers:

- which files passed,
- which files warned,
- which files failed,
- which files were skipped.

The lower pane contains detailed tool output and verification evidence.

Cleaner displays:

- current file,
- current processing stage,
- encode progress derived from FFmpeg timestamps,
- final batch totals.

Cleaner logs phase timing for:

- inspection,
- source continuity,
- encode pass 1 when used,
- encode or encode pass 2,
- mux,
- verification,
- promotion,
- wrapper overhead,
- total elapsed time.

The progress bar represents the active FFmpeg encode pass. Non-encode stages are identified by stage text but are not percentage-estimated.

The persistent run log is `Cleaner.log` in the selected source folder.

---

## Known Limits and Unrealized Features

The following are not implemented and must not be implied by interface text, comments, PASS status, or documentation:

### Perceptual validation

Continuity scanning is structural evidence.

Cleaner does not decode and analyze every frame and audio sample for:

- black or frozen video,
- silence,
- clipping,
- corruption visible only after decode,
- lip-sync drift,
- brief perceptual defects,
- subjective image or sound quality.

A PASS result therefore means the implemented checks passed. It does not prove perceptual perfection.

### HDR handling

Cleaner does not currently implement a deliberate HDR-to-SDR tone-mapping policy.

HDR input still enters the normal 8-bit H.264 output path. That may alter appearance and must not be described as validated HDR conversion.

HDR-to-SDR handling remains an open engineering feature.

### Multiple program selection

Cleaner uses the first video stream and first audio stream.

It does not currently make an intelligent choice among:

- alternate cuts,
- multiple video angles,
- commentary audio,
- descriptive audio,
- alternate-language audio,
- multiple primary audio programs.

### Subtitle formats

External sidecar support is limited to SRT.

ASS, SSA, VTT, PGS, VobSub, and other external subtitle packages are not currently consumed as sidecars.

### Filename intelligence

Filename cleanup is based on recognized patterns and release tokens.

It is not a database-backed title matcher and can require operator correction for unusual names.

### Verification thresholds

The current continuity and duration thresholds are project policy embodied in code, but they still require field testing against a broader range of real sources.

Thresholds should change only when evidence justifies a new standard.

---

## Required Tools

Cleaner requires:

- Python with Tkinter,
- FFmpeg,
- FFprobe,
- MKVToolNix `mkvmerge`.

Cleaner searches the system PATH and selected conventional Windows install locations.

---

## Canonical Naming

The repository source file is:

`Source/Cleaner.py`

The application identifies itself as:

`Cleaner`

The persistent log is:

`Cleaner.log`

Older `TheCleaner.py`, `The Cleaner` application-title, and `TheCleaner.log` references are obsolete naming and should not be carried forward.

---

## Source Version 2.2.0

Version 2.2.0 reconciles the two diverged branches:

From 2.1:

- Show and Movie modes,
- SRT sidecar ownership,
- subtitle input ownership,
- consumed-sidecar transaction handling,
- multi-item rollback.

From 2.0.3:

- current stage display,
- FFmpeg encode progress,
- per-phase timing,
- performance summary.

Version 2.2.0 also corrects canonical source, application, and log naming and makes known limits explicit in both source and specification.
