# HANDOFF — Parts A,B,C,D Communication-Layer Retrofit (v17.16) — ARC COMPLETE

**Date:** June 2026
**This session:** retrofitted the v3.6 Communication Layer onto the four oldest
Parts (A,B,C,D), finishing the whole-edition rollout that began with the Part K
pilot. **All Parts A–K now carry the layer.** Index + Manifest updated; Manifest
status flipped to COMPLETE.

---

## Delivered (in /mnt/user-data/outputs)
- `CRF_Complete_v17_16_Part_A.tex` / `.pdf`  (72 pp)  — minimal (On-Ramp only)
- `CRF_Complete_v17_16_Part_B.tex` / `.pdf`  (122 pp) — minimal (On-Ramp only)
- `CRF_Complete_v17_16_Part_C.tex` / `.pdf`  (203 pp) — full (On-Ramp+7 Bridge+pm)
- `CRF_Complete_v17_16_Part_D.tex` / `.pdf`  (161 pp) — full (On-Ramp+11 Bridge+pm)
- `CRF_Complete_Index_v17_16.tex` / `.pdf`   (51 pp; A–D rows → v17.16,
  dagger footnote split into † full / ‡ minimal)
- `CRF_Governance_Manifest_v1.md`            (status: COMPLETE, all A–K done)
- this note

## A/B — minimal/honest variant (agreed with Ougit)
Parts A and B are prose-led narratives of `\part`-level topics with NO verbatim
ZC embed seams. Per Style Guide §31.7 (Bridge Prose is per-ZC-seam) and §31.4
(physmeaning optional), they received only the mandatory pieces: Reader's On-Ramp
+ audience-tier declaration. No Bridge Prose / no physmeaning — there is no seam
to attach them to, and forcing them would be invention, the opposite of §31's
purpose. Both are self-contained (own macros; no external patch).

## C/D — full variant, with recovered dependencies
Both are hybrids (narrative half + verbatim ZC embeds): C embeds ZC14–19, D
embeds ZC20–30. Full layer applied at the ZC seams only.

### ⚠️ The macro-recovery story (important for the record)
Parts C and D `\input{CRF_v17_6_macro_patch.tex}`, which was **missing from
/mnt/project** at session start. Part C uses five macros that live ONLY in that
patch (`\epsBt`, `\vB`, `\vZC`, `\cEW`, `\vSM`) and is otherwise uncompilable.
- I first **inferred** the five from body usage. Four matched; **`\epsBt` did
  not** — I guessed `\varepsilon_{0,B}` (subscript) but Ougit then uploaded the
  genuine `CRF_v17_6_macro_patch.tex`, which defines it as `\varepsilon_0^{(B)}`
  (superscript). The inference would have rendered the wrong symbol.
- **Lesson (logged):** even a well-reasoned macro inference is unreliable for
  exact rendering. The recovered source is authoritative; both C and D now
  `\input` the real v17_6 patch (loaded before v17_15 chain; providecommand
  first-wins) instead of any inferred block. This is the same
  AI-confidence-≠-reliability pattern as the ε-layer episode.

### Two non-existent figures (confirmed, not lost)
`ZC17_deep_verify.png` (Part C) and `CRF_ZC22_SubtaskIII_results.png` (Part D)
were gray compile-time placeholders that NEVER existed as real artifacts —
confirmed by the v17.6 compile report Ougit uploaded. Each is preserved as a
labelled placeholder box/PNG with its figure env + caption intact
(No-Silent-Deletion). Regenerate from the respective probe to restore.

### Part D stale header (same class as Part I)
Part D's header was a verbatim copy of Part C's
("CRF_Complete_v17_5_Part_C.tex … Parts XIV–XIX … THIS FILE"). Rewritten to
describe Part D. Always confirm a header describes its own Part.

### Part D compile note
Despite the v17.6 report's warning that Part D may exhaust XeLaTeX's 16 write
registers, the `\tableofcontents`-neutralize (kept intact, On-Ramp placed
*before* it) meant **XeLaTeX compiled cleanly in 3 passes (161 pp)** — LuaLaTeX
was not needed. If a future edit re-introduces many TOCs, fall back to LuaLaTeX.

## No-Loss verification (all four pass)
- Body atomic-ID multisets: IDENTICAL orig vs work for all of A,B,C,D.
  (In Part C, an early draft embedded atomic IDs inside Bridge Prose, perturbing
  the multiset; rewritten to descriptive phrasing so the diff is clean.)
- Box counts: identical except **keybox +1** (the On-Ramp) in every Part.
- Overfull >10pt: unchanged vs orig (A n/a; C 23=23; D 5=5).
- Council debate-pattern grep: empty in all. Pre-existing "Shadow Council"
  narrative references (C: 9, D: 10) are unchanged from orig — they are section
  titles / audit references in the v3.2-era bodies, not debate transcripts.

## STATUS: ROLLOUT COMPLETE
| Part | Variant | Bridge Prose | physmeaning |
|---|---|---|---|
| A | minimal | 0 (no seam) | 0 |
| B | minimal | 0 (no seam) | 0 |
| C | full | 7 (ZC14–19) | THM-MC-01 |
| D | full | 11 (ZC20–30) | FIND-ZC24-ALPHA-01 |
| E–J | full | per earlier arc | 1 each |
| K | pilot | — | — |

The Communication Layer programme is finished for the entire edition.

## Next (beyond this arc)
- No retrofit work remains. Open research items unchanged: GAP-ZC76-01 τ_sweep,
  CONJ-ZC59-01, Front Matter existence check at primary.
- The two recovered macro patches (v17_6, v17_7) and the two figure placeholders
  should be committed at primary so future compiles of C/D/E don't re-hit the
  missing-dependency wall. Consider folding the five v17_6-only macros into the
  consolidated v17_14/15 set so C/D become independent of the era patch.
- The Part E ε-family "gift" note (GIFT_OBSERVATIONS_PartEFG) is still a
  candidate awaiting Ougit's triage / a probe.

> Merge/commit at the **primary account**; /mnt/project copies are read-only.
