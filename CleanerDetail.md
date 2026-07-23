# Cleaner Engineering Notes

These notes preserve engineering discoveries.

They are intentionally separate from the Cleaner specification.

The specification records what Cleaner guarantees.

These notes explain why certain implementation decisions exist.

------------------------------------------------------------------------

## DTS versus PTS

Early versions of Cleaner evaluated packet continuity using packet PTS
when available.

Testing against healthy H.264 sources produced thousands of false
backward timestamp events.

Investigation showed these were caused by normal B-frame presentation
reordering rather than damaged media.

Cleaner therefore evaluates packet continuity using DTS whenever
available.

PTS may legitimately move backward without indicating corruption.

------------------------------------------------------------------------

## Confidence Before Rules

Not every measurement deserves to influence archive confidence.

Measurements should first demonstrate that they correlate with visible
or structural archive defects.

Only after repeated verification should they become part of PASS / WARN /
FAIL policy.

Until then they remain diagnostic evidence.

------------------------------------------------------------------------

## Diagnostic Logging

Whenever practical, diagnostics should identify:

• where the condition occurred

• how severe it was

• enough information for the operator to inspect the media directly

A warning without actionable evidence has limited engineering value.

------------------------------------------------------------------------

## Source Damage

If fatal source damage can be demonstrated before encoding begins,
Cleaner should terminate processing before invoking FFmpeg.

Encoding cannot improve known corruption.

Early termination saves processing time while preserving the original
archive.

------------------------------------------------------------------------

## Engineering Principle

Cleaner should measure first.

Cleaner should judge second.

Engineering decisions should be promoted from observation to policy only
after repeated evidence demonstrates that they improve archive
confidence.

------------------------------------------------------------------------
