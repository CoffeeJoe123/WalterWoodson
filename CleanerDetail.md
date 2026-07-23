# Cleaner Engineering Notes

**Status:** Current  
**Last Updated:** 2026-07-23

These notes preserve engineering discoveries.

They are intentionally separate from the Cleaner specification.

The specification records what Cleaner guarantees.

These notes explain why certain implementation decisions exist.

---

## DTS versus PTS

Early versions of Cleaner evaluated packet continuity using packet PTS when available.

Testing against healthy H.264 sources produced thousands of false backward timestamp events.

Investigation showed these were caused by normal B-frame presentation reordering rather than damaged media.

Cleaner therefore evaluates packet continuity using DTS whenever available.

PTS may legitimately move backward without indicating corruption.

Small DTS backsteps observed near stream startup must also be treated cautiously. A backward step by itself is not sufficient evidence of a playback defect.

---

## Confidence Before Rules

Not every measurement deserves to influence archive confidence.

Measurements should first demonstrate that they correlate with visible or structural archive defects.

Only after repeated verification should they become part of PASS / WARN / FAIL policy.

Until then they remain diagnostic evidence.

The inverse also matters: when a known playback defect repeatedly demonstrates that a measurement is meaningful, future versions must not downgrade or remove that protection without new evidence.

---

## Diagnostic Logging

Whenever practical, diagnostics should identify:

- where the condition occurred,
- how severe it was,
- the affected stream,
- enough information for the operator to inspect the media directly,
- the policy result,
- whether processing was skipped or attempted.

A warning or failure without actionable evidence has limited engineering value.

A generic message such as `encode complete` is not sufficient evidence of archive integrity.

---

## Source Damage

If fatal source damage or a demonstrated integrity defect can be established before encoding begins, Cleaner should terminate that source before invoking FFmpeg.

Encoding cannot restore missing source content merely by completing successfully.

Early termination saves processing time, preserves the original, and allows the batch to continue.

The operator-facing message should explain that the defect occurs later in the source when that is the case. Immediate preflight rejection does not imply the opening portion is unreadable.

---

## Known Continuity Regression Specimen

The project retains a known source containing a real playback hole.

The defect was originally found by watching the file.

Observed player behavior differs:

- VLC skips across the missing span and continues without an obvious error.
- MPC-HC continues audio in real time, freezes the last rendered video frame through the gap, then resumes video afterward.

This file remains useful because technically tolerant playback can conceal a meaningful integrity defect.

The specimen exists to verify that Cleaner does not equate successful decoding, encoding, remuxing, or player recovery with a trustworthy archive.

The expected result is an integrity failure with exact timestamps.

It must not be reported as a good and complete encode.

---

## Origin of Continuity Checking

Continuity checking first existed as a Wrangler feature.

Cleaner versions before 2.0 did not detect the known playback hole as part of archive acceptance and could report successful completion despite the defect.

The continuity capability was brought into Cleaner because encode success alone did not provide enough confidence for unattended preservation.

Wrangler and Cleaner may use continuity information for different purposes, but the underlying engineering lesson is shared: stream timelines can expose defects that tolerant decoders and successful processing conceal.

---

## Cleaner 2.x Continuity Evolution

### Cleaner 2.0

- Detected the known continuity hole.
- Continued processing after the finding.
- Later reached the MKVToolNix/remux stage and errored.
- Demonstrated that detection existed but was not yet acting as an efficient preflight gate.

### Cleaner 2.01

- Moved continuity findings into preflight rejection.
- Avoided wasting encode time on a source already known to violate the integrity standard.
- Incorrectly rejected additional healthy files because backward timestamp movement was treated too aggressively.

### Cleaner 2.02

- Corrected the normal backstep problem by refining continuity analysis and using DTS.
- Retained early rejection of the demonstrated playback hole.
- Established the desired operational behavior: identify a known integrity defect before encoding, report its later location, preserve the source, and continue the batch.

This progression explains why current continuity code must preserve both behaviors:

1. normal frame-order timestamp behavior must not fail healthy media;
2. a demonstrated playback hole must still fail preflight.

---

## Can Process versus Should Archive

Cleaner has two independent responsibilities.

FFmpeg and related tools help answer:

> Can this source be processed?

Cleaner must also answer:

> Should this result be accepted into the WoodPile?

A source may be fully encodable while containing a localized defect that makes it unsuitable for trusted preservation.

The second question is the reason continuity and verification exist.

---

## Preflight Timing

A source can be healthy from the beginning until a later damaged span.

A whole-file preflight scan may discover that later defect immediately.

This is intentional.

Cleaner is not claiming the source is broken at the first frame.

Cleaner is avoiding the wasted time of encoding material that is already known to fail the archive-integrity gate.

Preferred wording should explicitly say that the defect was detected later in the source.

---

## Engineering Principle

Cleaner should measure first.

Cleaner should judge second.

Engineering decisions should be promoted from observation to policy only after repeated evidence demonstrates that they improve archive confidence.

Once a known regression specimen establishes that a condition represents a real playback defect, preserving that detection becomes part of the WoodPile flywheel.
