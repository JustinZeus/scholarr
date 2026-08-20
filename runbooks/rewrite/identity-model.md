# Scholarr rewrite - identity model  **[live 2026-07-23]**

This is an agreed direction from the 2026-07-21 discussion with Justin. It is now formalized in the
review-ready, unfrozen draft at `/opt/stacks/scholarr-rewrite/docs/specs/data-model.md`. Part of the
[scholarr-rewrite](README.md) runbook; read the doctrine there first.

This document records how the rewrite decides *who an author is* and how it keeps the same person
from turning into two records. It is a decision record, not the final spec: it feeds the identity /
identifier-first-dedup spec when that spec is frozen.

## Root principle

Identity is anchored to **source identifiers**; names are **labels only**. Nothing is ever keyed
on a name. Two records are the same author because they share a resolved identifier, never because
they share a string.

## Same name, different people

Supported **by construction**: distinct external IDs are distinct `FollowedAuthor` records, so two
genuinely different people who happen to share a name simply resolve to two records and never
collide.

UX around this:

- **Disambiguation evidence at add time.** When a user is picking a candidate, show the deciding
  evidence side by side: affiliation, fields, active years, sample works, and the identifiers
  themselves. The user confirms a specific person, not a name.
- **One soft, non-blocking notice** when confirming a candidate whose name matches an
  already-followed author with a **different** ID: "same person or different?" It does not block
  the confirm; it just makes the collision visible.
- **The answer persists as a "confirmed different" tombstone**, so that exact pair is never
  re-flagged again.

## Duplicate prevention: three mechanisms for three causes

Duplicates have three distinct causes, and each gets its own mechanism.

1. **Exact re-follows** (the same identifier followed again). Killed by a **uniqueness constraint on
   `(source, external_id)`** plus the shared-identity model: there is one canonical author record
   and per-user follow rows, so a second user following the same person **attaches to the existing
   resolution** rather than creating a new author.

2. **The same human reached via different identifiers.** `AuthorSourceIdentity` is a **list on one
   author**: a Scholar-imported shell, an OpenAlex ID, and an ORCID can all attach to a single
   `FollowedAuthor` record. When a shell is later identified as an already-followed ID, the
   resolution becomes a **MERGE**, **never a new
   author**. The survivor is not assumed to be the already-followed record: the spec's
   deterministic target rule governs every author merge (resolved beats shell, more strong
   identities, older `created_at`, lowest `public_id`), regardless of which record was the review
   subject. Merges are **audited and undoable**, because a wrong merge (collapsing two real people
   into one) is the worst mistake the system can make.

3. **OpenAlex split profiles** (one real person holding more than one OpenAlex ID). One author may
   hold multiple OpenAlex IDs via an **"also this profile"** action. The **works-overlap scoring**
   used for identity calibration doubles as the duplicate detector here: it raises a **"possible
   duplicate" review card** that resolves to either **merge** or **keep-separate** (keep-separate
   writes the **confirmed-different** tombstone described above).

## Review-queue hygiene

The review queue is keyed by the **author entity**, never by the raising event. This keeps the
queue honest instead of flooding it.

- A shell that fails to resolve across ten syncs is **one card**, not ten.
- **Pairwise duplicate cards spawn once per pair**, unless genuinely new evidence appears (for
  example, a newly shared identifier changes the picture).
- **Four card types:**
  - **identify shell** - a Scholar-imported shell that has no resolved ID yet.
  - **confirm ambiguous match** - the soft "same person or different?" from add time.
  - **possible duplicate** - the works-overlap detector flagged two records as maybe the same
    person.
  - **not-this-person fallout** - cleanup when a prior resolution turns out to be wrong.

## Honest limit

Shells with **no name and no works** cannot be proven distinct. They stay **human-decided**, and
the UI **says so plainly** rather than guessing. The system does not pretend to resolve identity it
has no evidence for.

## Related

- The works-overlap scoring reused here as a duplicate detector: [identity-calibration.md](identity-calibration.md).
- Root entity and `AuthorSourceIdentity` decision: [README.md](README.md) (Locked decisions).
