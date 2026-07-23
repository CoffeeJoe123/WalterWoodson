# The Cleaner

The Cleaner prepares media according to the WoodPile's preservation, compatibility, accessibility, and size standards.

It is the successor to the former Media Standardizer name. The new name is deliberate: the tool cleans and prepares material for the archive; it does not claim to improve the source.

## Role

The Cleaner owns media transformation decisions such as:

- video codec and encoding behavior
- scaling
- bitrate strategy
- audio conversion
- subtitle retention during conversion
- verification of the produced media

Naming, metadata cleanup, folder construction, and library organization belong primarily to [The Wrangler](../Wrangler/Wrangler.md).

## Current Direction

The project favors:

- broad playback compatibility
- dependable quality rather than maximal quality
- controlled and predictable output size
- minimal routine choices once testing has established the standard
- source-first processing
- unattended batch operation that can be trusted

The current working direction includes H.264 output for compatibility, fixed-bitrate testing, AAC stereo, and deliberate scaling tests. Exact canonical settings should be expanded here only after they are confirmed from the existing project evidence.

<img width="800" height="800" alt="Cleaner v2 0" src="https://raw.githubusercontent.com/CoffeeJoe123/WalterWoodson/WoodPile/Attachments/CleanerVision.png" />

# Cleaner

## Purpose

Cleaner standardizes archived television episodes into a consistent,
verified format suitable for long-term storage.

The objective is not simply to encode media.

The objective is to increase confidence that every completed archive
remains trustworthy while eliminating repetitive manual decisions.

------------------------------------------------------------------------

## Engineering Philosophy

Cleaner exists to replace repeated human judgement with documented,
repeatable policy.

If the same decision is made often enough that an operator can predict
it in advance, Cleaner should eventually learn that behavior.

The archive should become more consistent over time while requiring less
human intervention.

Automation is successful only when confidence increases alongside the
reduction in manual effort.

------------------------------------------------------------------------

## Verification Philosophy

Verification exists to establish archive confidence rather than technical
perfection.

Every verification rule should answer a practical question:

    "Would a reasonable curator archive this media?"

Verification therefore prefers measurements that correlate with actual
archive quality instead of theoretical container correctness.

Cleaner follows these principles:

• Detect fatal source damage before encoding whenever possible.

• Never spend significant time encoding media already known to be
  unsuitable for replacement.

• Preserve the original whenever verification cannot establish
  confidence.

• Record diagnostic observations separately from confidence decisions.

• Allow engineering evidence to mature before promoting measurements
  into PASS / WARN / FAIL policy.

Warnings should represent conditions that a human operator can
reasonably investigate.

Diagnostics should provide enough information to inspect the affected
media directly.

------------------------------------------------------------------------

## Archive Standard

Video

- H.264
- 1650 kb/s target bitrate
- One-pass encoding
- Fast preset
- Bicubic scaling

Audio

- AAC
- Stereo
- 192 kb/s

Subtitles

- Preserve all subtitle streams.

------------------------------------------------------------------------

## Design Principle

Cleaner should eliminate recurring manual work without reducing archive
confidence.

Confidence always takes priority over speed.

When speed and confidence are equal, prefer the simpler implementation.

------------------------------------------------------------------------


## Manual Structure to Build

This manual will eventually contain:

- current interface image
- accepted controls and their purpose
- canonical video, audio, subtitle, and container behavior
- one-pass and two-pass behavior
- scaling standards and test results
- verification rules
- batch and failure behavior
- source links
- known limitations
- active work links back to the [Duty Log](../WoodPile/DutyLog.md)

## Related Documents

- [Walter Start Here](../WALTER_START_HERE.md)
- [About the WoodPile](../WoodPile/AboutTheWoodPile.md)
- [WoodPile Codex](../WoodPile/Codex.md)
- [Duty Log](../WoodPile/DutyLog.md)
