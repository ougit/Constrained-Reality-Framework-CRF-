# HANDOFF → NEW CHAT — CRF Communication-Layer Retrofit (v17.16)

**For:** the next session (new chat). Read this first, then the files in
**§0 Read-First**. This note lets you continue the retrofit programme without
re-deriving context.

**Date:** June 2026
**Programme:** retrofitting the v3.6 Communication Layer (On-Ramp + Bridge
Prose + one `\physmeaning` + Map-Not-Reality pointer) onto each Complete-Edition
Part, Part by Part, additively (No-Loss). Pilot = Part K. Done this arc =
Parts J, I, H.

---

## 0. READ-FIRST (every new session, before any work)

Per Governance Manifest v1, these are the ACTIVE governance files:
- `CRF_Governance_Manifest_v1.md`         — which version of everything is ACTIVE
- `CRF_Reference_LexiconLock_v4.md`
- `CRF_PWA_Scattered_Knowledge_Note.md`   — PWA-1..12
- `CRF_Complete_Index_v17_16.tex`         — current index (in outputs; see §3)

For a Part retrofit, additionally:
- `CRF_Style_Guide_v3_6.md` §31            — the Communication Layer rules
- `CRF_Complete_Edition_Upgrade_Protocol_v1_3.md` §U (Comm Layer) + §V (preamble)
- `CRF_Integration_Execution_Script_v1_2.md`

**The retrofit pattern is fully worked three times now** (Parts J, I, H). Use any
of those `.tex` files as the copy-paste template for the next Part.

---

## 1. STATUS — Communication Layer rollout

| Part | ZC range | Comm Layer | Version | Notes |
|---|---|---|---|---|
| K | ZC83–87 | ✅ PILOT | v17.15 | reference pattern (5 papers) |
| **J** | ZC76–82 | ✅ done | **v17.16** | 7 Bridge Prose; physmeaning on THM-ZC76-01 |
| **I** | ZC64–75 | ✅ done | **v17.16** | 12 Bridge Prose; physmeaning on THM-ZC72-01; **stale Part-H header corrected**; macro repoint v17_12→v17_15 |
| **H** | ZC50–63 | ✅ done | **v17.16** | 14 Bridge Prose; physmeaning on THM-ZC54-01; **clearpage fix** for longtable; macro repoint v17_12→v17_15 |
| G | ZC45–49 | ⬜ NEXT | v17.9 | suggested next target |
| F | ZC41–44 | ⬜ | v17.8 | |
| E | ZC31–40 | ⬜ | v17.7 | |
| A–D | early | ⬜ | v17.5–6 | older v3.2/3.3 era; lowest priority |

Retrofit is **incremental + optional** (Protocol §U8 / Style Guide §31.7), not
retroactively mandatory. Stop any time; each Part stands alone.

---

## 2. THE RETROFIT RECIPE (proven 3×)

For Part X (papers ZCaa–ZCbb):

1. **Copy** `CRF_Complete_v17_..._Part_X.tex` → working file; keep an
   untouched `_orig` copy for the No-Loss diff.
2. **Header:** rewrite to v17.16; add the Communication-Layer declaration
   block + `%% Primary audience tier: 1 | On-ramp for tier below (0): yes`.
   **Preserve any legitimate existing info** (e.g. a correct closures list).
   **Check for a stale copy-paste header** (Part I's was a copy of Part H's —
   scan that the header's part letter / clusters / closures actually match THIS
   Part).
3. **Macro patch:** repoint `\input{CRF_v17_NN_macro_patch.tex}` →
   `\input{CRF_v17_15_macro_patch.tex}` (carries `\physmeaning`; chains the
   consolidated v17_14 = full Parts A–J macro set). Verify **0 undefined
   control sequences** on compile.
4. **On-Ramp:** insert a `keybox` "If you are just arriving — Part X in plain
   language" right after `\tableofcontents` (+ `\clearpage`/TOC-suppression if
   present), before the first `\part`. ≤12 lines, no atomic IDs, 5–6 glossed
   terms, Map-Not-Reality pointer. (Copy a prior Part's On-Ramp and re-fill.)
5. **Bridge Prose:** one 2–3 paragraph unboxed block at **every** ZC embed
   seam (right after each `\section{ZCxx: …}`), each marked
   `% [BRIDGE-PROSE: integration-added, Extension Freedom narrative, v3.6 §31.6]`.
   Must pass the WHY test (state why open / why surprising / what it enables —
   NOT "did X then Y"). Read each paper's abstract/key results first.
6. **physmeaning ×1:** pick ONE major THM/FIND box that has **no** existing
   physical-reading prose (grep the box for "physical significance / reading /
   interpretation / physically"). Add `\physmeaning{…}` as its final line.
   Do NOT add where the box already has such prose (duplication = No-Loss
   issue). One per Part is the norm.
7. **Compile** xelatex ×3. If a fatal **`Dimension too large`** appears at a
   `\end{longtable}` → it is a **longtable-in-breakable-formalbox pagination
   shift**, not content. Fix with a single `\clearpage` before the affected
   paper's `\section`, marked `% [LAYOUT: …]`. (Happened in Part H, not I/J.)
8. **No-Loss verify:**
   - atomic-ID multiset `diff` orig vs new → must be identical (allow only
     header-comment differences you understand);
   - box-env counts identical except `keybox +1` (the On-Ramp);
   - overfull >10pt count not increased vs the original clean build;
   - Shadow Council debate-pattern grep empty.
9. **Index:** bump the Part X row to v17.16 `$\dagger$`; extend the dagger
   footnote to include Part X. Recompile index.
10. **Deliver:** `.tex` + `.pdf` for the Part, updated Index `.tex`+`.pdf`,
    a `HANDOFF_NOTE_v17_16_PartX.md`. `present_files` all.

---

## 3. CURRENT DELIVERABLES (in /mnt/user-data/outputs — carry forward)

- `CRF_Complete_v17_16_Part_H.tex` / `.pdf`  (144 pp)
- `CRF_Complete_v17_16_Part_I.tex` / `.pdf`  (156 pp)
- `CRF_Complete_v17_16_Part_J.tex` / `.pdf`  (101 pp)
- `CRF_Complete_Index_v17_16.tex` / `.pdf`   (51 pp; covers H+I+J retrofit)
- `HANDOFF_NOTE_v17_16.md` (Part J), `..._PartI.md`, `..._PartH.md`

> These are session outputs. Merge/commit at the **primary account**; the
> project's `/mnt/project` copies are read-only here.

---

## 4. LESSONS (binding for the rest of the rollout)

1. **Stale-header check.** Part I's header was a verbatim copy of Part H's
   (wrong everything). Always confirm the header describes THIS Part before
   trusting it; correct if stale (Part I), preserve if right (Part H).
2. **longtable-in-formalbox = pagination fragility.** Adding prose can push an
   Atomic-Registry longtable across a breakable-box page break → fatal
   `Dimension too large`. Localise by binary search (remove one prose block,
   recompile); fix with `\clearpage`, never by cutting content.
3. **physmeaning restraint is real.** Most candidate boxes in the math-dense
   Parts already carry "physical significance/reading" prose. One genuine,
   non-duplicating use per Part. (K/J/I/H all = 1.)
4. **Macro repoint = PWA-DOWNSTREAM done right.** Parts referenced
   `CRF_v17_12_macro_patch.tex`, which is absent from the project. Repoint to
   the consolidated v17_15 (origin), don't recreate the missing per-version
   file (symptom). Repoint of Parts A–G still pending.
5. **No-Loss is verified, not assumed.** Always run the atomic-ID diff + box
   count before declaring a Part done.

---

## 5. OPEN RESEARCH ITEMS (unchanged by this arc; for reference)

These predate the retrofit and are NOT part of it; listed so the next session
knows the live frontier:
- **GAP-ZC76-01** (τ_sweep = t_Planck): blocked on an external SNSPD timing
  experiment, not on CRF algebra.
- **GAP-ZC75-01 / cosmological P(t) evolution:** needs τ_sweep.
- **CONJ-ZC59-01** (two-multiplier Born-chain conjecture): open.
- **Front Matter** (`CRF_Edition_FrontMatter_v1.tex`): On-Ramps point to its
  Master Notation Key + Map-Not-Reality; confirm it exists/compiles at primary.

(See the companion Shadow Council note for proposed *new* directions.)

---
*Continue at: Part G retrofit (recipe §2), or pick a research direction from the
Shadow Council session. Read §0 files first.*
