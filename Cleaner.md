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
