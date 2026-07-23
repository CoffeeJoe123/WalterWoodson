# The Cleaner

**Status:** Current  
**Last Updated:** 2026-07-23

The Cleaner prepares media according to the WoodPile's preservation, compatibility, accessibility, size, and confidence standards.

It is the successor to the former Media Standardizer name.

The new name is deliberate: the tool cleans and prepares material for the archive; it does not claim to improve the source.

---

## Role

The Cleaner owns media transformation and acceptance decisions such as:

- video codec and encoding behavior,
- scaling,
- bitrate strategy,
- audio conversion,
- subtitle retention during conversion,
- preflight source-integrity checks,
- verification of the produced media,
- batch continuation and failure reporting.

Naming, metadata cleanup, folder construction, and library organization belong primarily to [The Wrangler](../Wrangler/Wrangler.md).

---

## Preservation Objective

The Cleaner is not merely an FFmpeg wrapper.

Its job is not complete when encoding and remuxing succeed.

The Cleaner must make a reasonable, evidence-based effort to determine whether the source and resulting media are trustworthy enough for long-term storage.

A technically playable file may still contain a meaningful playback defect.

A tolerant player may skip over a damaged span, freeze the last video frame while audio continues, or recover after missing packets without displaying an obvious error.

Such behavior does not make the source healthy.

---

## Two Acceptance Gates

Cleaner evaluates two separate questions.

### Processing Gate

Can the source be decoded, encoded, remuxed, and verified technically?

Examples of processing failures include:

- unreadable input,
- fatal decoder errors,
- unsupported streams,
- aborted encoding,
- remux failure,
- output verification failure.

### Integrity Gate

Does available evidence support accepting the media into the WoodPile?

Examples of integrity failures include:

- a demonstrated playback continuity hole,
- a serious timestamp discontinuity correlated with missing or frozen playback,
- a localized audio or video defect that processing alone would conceal,
- any condition that permits technical completion but undermines archive confidence.

Successful processing does not override an integrity failure.

---

## Preflight Integrity Analysis

Cleaner performs source-integrity analysis before expensive encoding whenever practical.

If a demonstrated failure is found later in the source, Cleaner may reject the job immediately rather than processing up to that point.

The report must make clear that:

- the defect occurs later in the source,
- the exact observed time range,
- encoding was intentionally not started,
- the original was preserved,
- the batch will continue.

Preferred operator-facing wording:

> **PREFLIGHT INTEGRITY FAILURE**  
> A playback continuity defect was detected later in the source.  
> Location: `HH:MM:SS → HH:MM:SS`  
> Encoding was not started because the source cannot produce a trustworthy archive under the current WoodPile Standard.

Preflight exists to save processing time without hiding the reason for rejection.

---

## Continuity Policy

Packet continuity is evaluated using DTS whenever available.

Normal H.264 frame reordering can produce small backward timestamp movement without indicating damaged media.

A backward timestamp step alone must not be classified as an integrity failure.

A demonstrated continuity hole is different from normal timestamp reordering.

The distinction must remain explicit in code, logging, tests, and documentation.

Continuity findings should identify:

- affected stream,
- previous timestamp,
- next timestamp,
- size of the gap,
- location in human-readable time,
- policy result,
- whether encoding was skipped.

---

## Current Direction

The project favors:

- broad playback compatibility,
- dependable quality rather than maximal quality,
- controlled and predictable output size,
- minimal routine choices once testing has established the standard,
- source-first processing,
- unattended batch operation that can be trusted,
- actionable verification rather than generic success messages.

The current working direction includes H.264 output for compatibility, fixed-bitrate testing, AAC stereo, deliberate scaling tests, and preflight continuity analysis.

Exact canonical encoding settings should be expanded here only after they are confirmed from existing project evidence.

---

## Batch Behavior

Cleaner assumes success and attempts every queued file.

For each source:

- inspect,
- perform preflight integrity checks,
- encode only when the source remains eligible,
- remux,
- verify,
- preserve the original,
- record the outcome,
- continue to the next file.

One failed source must not terminate the remaining batch unless transaction safety itself is compromised.

---

## Reporting

Cleaner must distinguish among:

### PASS

Processing completed and no evidence currently undermines archive confidence.

### WARN

An unusual condition was measured, but available evidence does not justify rejection.

### INTEGRITY FAIL

A real playback or preservation defect has been demonstrated, even if the source remains technically playable or encodable.

### PROCESSING FAIL

The tool could not complete the required technical operation.

Diagnostics should be specific enough for direct inspection and future engineering.

---

## Related Documents

- [Walter Start Here](../WALTER_START_HERE.md)
- [About the WoodPile](../WoodPile/AboutTheWoodPile.md)
- [WoodPile Codex](../WoodPile/Codex.md)
- [Cleaner Engineering Notes](../WoodPile/CleanerDetail.md)
- [The Wrangler](../Wrangler/Wrangler.md)
- [Duty Log](../WoodPile/DutyLog.md)
