# HANDOFF — Part G Communication-Layer Retrofit (v17.16)

**Date:** June 2026
**This session:** retrofitted the v3.6 Communication Layer onto **Part G**
(ZC45–49), the fifth Part after the K pilot and the J/I/H arc. Additive,
No-Loss. Also updated the Governance Manifest to match true state.

---

## What was delivered
- `CRF_Complete_v17_16_Part_G.tex` / `.pdf`  (61 pp, xelatex ×3, clean)
- `CRF_Complete_Index_v17_16.tex` / `.pdf`   (51 pp; Part G row → v17.16†,
  dagger footnote extended to "Parts G, H, I and J")
- `CRF_Governance_Manifest_v1.md`            (updated — see below)
- this note

## Manifest correction (root-cause, PWA-DOWNSTREAM)
The Manifest had lagged one arc behind: it still stamped H/I/J as "ยังไม่
retrofit" and Index as v17.15, because it was last written at the END of the
Part-K session, BEFORE the J/I/H arc ran in a separate chat. Corrected at the
single source of truth rather than letting each HANDOFF override it:
- Index ACTIVE → **v17.16**
- compile-status table split A–G → **A–F** (pending) + individual
  **G,H,I,J = v17.16 ✅ retrofit**, K = v17.15 pilot
- retrofit-status note → "G,H,I,J,K done; A–F remaining (lowest priority)"

## Part G retrofit specifics
- **Header:** v17.9 → v17.16; Communication-Layer block added; header was
  CORRECT (not stale) — Part letter / clusters XXXV–XXXVII / ZC45–49 all match.
- **Macro repoint:** `CRF_v17_9_macro_patch` → `CRF_v17_15_macro_patch`
  (origin of the consolidated chain; v17_9 file is absent from project —
  Lesson 4). **0 undefined control sequences** on compile.
- **On-Ramp:** keybox after main TOC (line ~276), before `\part` XXXV.
  6 glossed terms (δ, ε₀, Spontaneous/Agentive Mode, Z₁₅, R=15/8, gap),
  Map-Not-Reality pointer, no atomic IDs, +`\clearpage`.
- **Bridge Prose ×5** — one at each ZC seam (ZC45/46/47/48/49), all WHY-test
  passed. The arc is a clean gap open→close chain: ZC46 promotes R=15/8 to a
  theorem leaving GAP-ZC46-01 open; ZC47 closes it (CRT decoupling); the prose
  foregrounds those stakes rather than narrating sequence.
- **physmeaning ×1** on **THM-ZC45-01** (Universal Floor). The box carried a
  *structural*-identity reading but no plain-language *physical* reading →
  non-duplicating. One per Part, as in K/J/I/H.

## No-Loss verification (all pass)
- **Body atomic-ID multiset:** IDENTICAL orig vs work (the only top-level diff,
  +1 THM-ZC45-01, is in the new HEADER COMMENT, not the body — verified by
  re-diffing with header lines excluded).
- **Box counts:** all identical except **keybox +1** (the On-Ramp). formalbox 27,
  derivedbox 24, openqbox 7, theorem 2, conmapbox 5, inheritbox 5,
  correctionbox 4 — all unchanged.
- **Overfull >10pt:** 0. (No `Dimension too large`; no clearpage fix needed,
  unlike Part H.)
- **Shadow Council debate-pattern grep:** empty.

## Next
- **Part F retrofit** (ZC41–44, v17.8) is the natural next target — recipe §2,
  use Part G/H/I/J as template. Then E, then A–D (oldest, lowest priority).
- Macro repoint of A–F still pending (do it as part of each Part's retrofit).
- Open research items unchanged (GAP-ZC76-01 τ_sweep, CONJ-ZC59-01, Front Matter
  existence check at primary).

> Merge/commit at the **primary account**; /mnt/project copies are read-only here.
