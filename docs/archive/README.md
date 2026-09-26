# Archived planning documents

These are historical. They are kept for provenance — so you can see what was
decided and when — but **not as guidance**. Several of them were already stale
or wrong when archived, and they contradict each other.

Read `docs/STATUS.md` instead. It is the single authoritative status document,
and everything in it was verified against the code on 2026-09-26.

## What is here and why it was retired

| File | Retired because |
|---|---|
| `PLAN.md` | Superseded by `ROADMAP.md` (2026-08-22), which was itself superseded. Its 8-feature roadmap was implemented. |
| `ROADMAP.md` | Superseded by `.kilo/plans/1787583794283-tnhcomfy-hardening-plan.md`. Still listed the audit's "open" batches long after they were done. |
| `REMEDIATION_PLAN.md` | Batches 0–3 and 5 marked ✅ were in fact done, but Batch 4 and the "pending" Batch 5 items had also been implemented without this file being updated. Nothing referenced it. |
| `REMEDIATION_PLAN_v2.md` | Superseded by `ROADMAP.md`. |
| `DEMO_GAPS_PLAN.md` | Superseded by the 2026-08-24 plan. Its "demo feel" diagnosis was accurate; its phasing is done. One decision from it survives and is cited in `docs/STATUS.md`: auth is intentionally out of scope for a local single-user studio. |
| `Implementation-plan.md` | Never superseded by anything, but implemented (OnboardingWizard, command palette, export modal, idle simulation all exist) and referenced by nothing. |

## The two genuine cross-references that leave this directory

- The plan `ROADMAP.md` and `DEMO_GAPS_PLAN.md` point at
  (`.kilo/plans/1787583794283-tnhcomfy-hardening-plan.md`) still exists and is
  the 2026-08-24 audit those documents defer to.
- `.kilo/plans/` also holds several other session plans, including two named
  `comprehensive-hardening-plan`. Those are per-session working notes, not
  tracked status.

If you are deciding what to work on, none of the above should influence you.
`docs/STATUS.md` lists what is actually still open, verified against the code.
