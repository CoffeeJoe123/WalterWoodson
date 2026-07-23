# WoodPile Codex

**Version:** 2.1  
**Status:** Current  
**Last Updated:** 2026-07-23

---

# Purpose

The WoodPile Codex is the engineering memory of the WoodPile project.

Its purpose is to preserve engineering decisions so future work begins from established knowledge rather than reconstructed conversation.

The Codex is authoritative.

When the project evolves, the Codex evolves with it.

---

# Mission

WoodPile exists to preserve media in an accessible, compatible, and intelligent manner so it remains useful long into the future.

The objective is not to create the smallest files or achieve the highest benchmark scores.

The objective is to preserve the ability for future people to experience the work with minimal technical barriers.

Technology will change.

The preservation objective remains.

---

# The WoodPile Standard

The WoodPile Standard represents the project's current engineering decisions.

Each standard is established through testing, observation, and practical experience.

Once adopted, the standard becomes the default implementation.

The standard changes only when new evidence demonstrates a better solution.

---

# The Flywheel

WoodPile is built around a flywheel rather than an expanding collection of user choices.

Repeated engineering decisions are made once, deliberately, then encoded into the software.

The decision is not removed.

The need to repeatedly make it is removed.

The flywheel is revisited only when new evidence justifies changing the standard.

Novelty alone is not sufficient.

Stable by default.

Evidence earns change.

---

# Engineering Philosophy

Compatibility is a cornerstone.

Accessibility is a cornerstone.

Optimize for the destination rather than the source.

Preserve the viewing and listening experience while removing unnecessary excess.

Do not engineer around incompatibility.

Prefer standards that naturally avoid it.

---

# Confidence

Confidence is a primary product requirement.

Most preserved media will not be watched again by the curator before long-term storage. A successful encode, remux, or direct-play test therefore does not by itself establish archive integrity.

WoodPile tools must make a reasonable, evidence-based effort to detect localized playback defects that tolerant players may conceal, including continuity gaps, frozen video spans, audio dropouts, and other defects that do not necessarily cause an encoder to abort.

Verification is not intended to prove perfection.

It exists to provide justified confidence that archived media is structurally usable and that known playback defects were not silently carried forward.

---

# Two Gates

Media preparation has two independent questions:

1. **Can the tool process this source?**
2. **Should the result be accepted into the archive?**

The first is a technical processing question.

The second is an integrity and preservation question.

A source may be technically encodable while still failing the WoodPile confidence standard.

WoodPile tools must not confuse successful processing with successful preservation.

---

# Positive Engineering

WoodPile tools assume success and attempt forward progress.

Whenever something can be corrected safely, correct it.

Whenever something can be standardized safely, standardize it.

Whenever something merely deserves reporting, report it.

Abort only when continuing would produce an untrustworthy archive or violate transaction safety.

When a demonstrable integrity failure is known before expensive processing begins, stop early, report the exact evidence, preserve the source, and continue with the batch.

---

# Documentation Philosophy

The Codex preserves current truth.

It is not intended to preserve obsolete decisions or project history.

When standards change:

- Carry forward everything that remains true.
- Replace anything that is no longer true.
- Preserve reasoning only when it helps future engineering.
- Do not manufacture explanations.

Version history belongs to source control.

The Codex describes the current specification.

---

# Specifications

Each tool owns one authoritative specification.

Examples include:

- `Cleaner/Cleaner.md`
- `Wrangler/Wrangler.md`
- `Bookie/Bookie.md`

Specifications describe what the tool currently does.

They are complete replacement documents rather than collections of incremental edits.

---

# Engineering Notes

Implementation discoveries that are likely to save future engineering effort belong in Engineering Notes.

Engineering Notes explain why.

Specifications define what.

Source code comments explain how.

Each kind of knowledge belongs in its natural home.

---

# Walter Woodson

Walter Woodson is the engineering partner and caretaker of the WoodPile project.

Walter does not preserve the project through memory.

Walter preserves the project by maintaining the Codex and implementing its standards.

Walter distinguishes between:

- documented fact,
- conversation,
- inference,
- recommendation.

Walter continues the project rather than rediscovering it.

---

# Project Objective

Every engineering decision should support the same long-term objective:

> Enable someone in the future to access and experience preserved media without becoming an expert in obsolete technology.

The preservation succeeds when the technology becomes invisible and the media remains accessible.

The software captures engineering judgment.

The Codex preserves that judgment.

The future inherits both.
