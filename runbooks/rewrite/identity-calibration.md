# Scholarr rewrite - identity calibration  **[live 2026-07-22]**

Part of the [scholarr-rewrite](README.md) runbook. Read the doctrine there first.

## Purpose

**This is calibration, not a gate.** An earlier framing treated a coverage experiment as the
decision point for whether to go API-first at all. That question is settled: **API-first is
doctrine** (no Google Scholar network contact, ever - see the runbook README). This document
does not re-litigate it.

What calibration *does* measure:

- **Identity-mapping quality** - how reliably a Scholar-imported author (name, plus whatever
  identifiers the old dataset holds) maps to the correct **OpenAlex** author, so the
  `FollowedAuthor` → `AuthorSourceIdentity` mapping in the rewrite is grounded in real numbers
  rather than optimism.
- **Honest coverage expectations** - per-author publication coverage relative to the old
  dataset, so onboarding and the "did we find everything?" UX can set expectations truthfully
  instead of implying completeness the APIs cannot deliver.

The output feeds two things: the [Semantic Scholar open question](README.md#open-questions)
(include it only if a real, material gap shows here), and the honesty of the onboarding /
source-health UX in the spec set.

## Constraints

- **No Google contact, ever.** Calibration reads only from the recovered old DB (for the known
  authors and their known publication titles) and from **official APIs**. Nothing in this
  method touches `scholar.google.com`.
- **Polite OpenAlex etiquette.** Use the `mailto` contact parameter on every request and keep a
  modest request rate with backoff. Calibration is a good citizen just like the service will be.

## Method

Input: the **492 authors** from the safety dump
(`/opt/stacks/scholarr/.backup/scholarr-pgdump-20260721.dump`; see the runbook's Assets
section for provenance and the real-email handling rule). For each author:

1. **Candidate search.** Query **OpenAlex `/authors`** by the author's name to get a candidate
   list.
2. **Works-overlap voting.** Pull each candidate's works and compare against the **author's
   known publication titles from the old DB**. The candidate whose works overlap the known
   titles most strongly wins the vote. Overlap is title-based (identifier-based where the old DB
   happens to have an identifier), which is exactly the disambiguation signal a same-name
   collision needs.
3. **Classify the mapping** into one of:
   - **auto-match** - a single clear winner, high overlap; safe to map without human review.
   - **needs-review** - ambiguous (multiple plausible candidates, or a weak winner); surface to
     a human.
   - **unmatched** - no acceptable candidate found.
4. **Measure per-author title coverage** - of the author's known titles, what fraction appear
   in the matched OpenAlex author's works. This is the coverage-expectation number.

**Freshness note (record, do not resolve):** sources differ in lag. **OpenAlex** typically lags
**days to weeks** behind publication; **arXiv** is **near-instant** for preprints. The sync
engine and the "recently published" UX must account for this per-source, and the coverage
numbers here should be read with the OpenAlex lag in mind (a very recent title missing from
OpenAlex is a freshness artifact, not a coverage failure).

**Caveat carried from the dataset facts:** the old titles are themselves a partial floor (the
scraper was already being blocked; 97 profiles never completed a baseline). "Coverage vs the old
DB" therefore measures agreement with an incomplete reference, not agreement with ground truth.
Report it as such.

## Results

**Calibration COMPLETE 2026-07-22.** Full run over all 492 dump rows finished
(completion fraction 1.0, 1287 OpenAlex requests). The 2026-07-21 attempt stalled at 75/492
under an OpenAlex IP-level rate block; the completion run used the recovered polite-pool API
key (separate rate-limit pool) and saw **zero HTTP 429** at a <= 2 requests/second pace. Raw
artifacts live under `/opt/stacks/scholarr/.experiment/` (git-excluded): `summary.json`,
`authors_matched.csv`, `authors_results.json`, and the experiment `RESULTS.md`.

### Headline (492 followed-author rows)

97 rows are **no-data** shells (no display_name and 0 publications in the dump, so nothing to
name-search). The other **395 matchable** rows are the denominator for the match rates.

| Class | Count | % of matchable | % of all 492 |
|---|---|---|---|
| auto-match | 352 | 89.1% | 71.5% |
| needs-review | 20 | 5.1% | 4.1% |
| unmatched | 23 | 5.8% | 4.7% |
| no-data shell | 97 | n/a | 19.7% |

The 89.1% auto-match rate held: the 75-author partial run showed 87.1%, and the full run came
in slightly higher at 89.1%, so the early number was representative, not lucky.

### Per user (percentages of that user's matchable rows)

| user | total | matchable | auto | needs-review | unmatched | no-data |
|---|---|---|---|---|---|---|
| Justin (1) | 242 | 240 | 215 (89.6%) | 12 (5.0%) | 13 (5.4%) | 2 |
| dad (2) | 250 | 155 | 137 (88.4%) | 8 (5.2%) | 10 (6.5%) | 95 |

Auto-match quality is essentially identical for both users; the only large gap is no-data
shells, which are almost entirely dad's un-crawled follows (95 of the 97).

### Over the 253 distinct authors (after cross-user dedup)

The 492 rows collapse to **253 distinct authors** (see dedup finding below). Counting each
person once, taking the better-resolved copy when the two users disagree:

| Class | Count | % of distinct-matchable (246) | % of 253 |
|---|---|---|---|
| auto-match | 222 | 90.2% | 87.7% |
| needs-review | 11 | 4.5% | 4.3% |
| unmatched | 13 | 5.3% | 5.1% |
| no-data shell | 7 | n/a | 2.8% |

Deduplicating raises the effective auto-match rate to **90.2%** and, more importantly, cuts
the no-data shells from 97 rows to just **7 true shells** (people un-crawled for *every*
following user). The other 90 no-data rows are the same person that another user already has
fully resolved.

### Title coverage of auto-matches

Fraction of ALL an author's dump titles found in the matched OpenAlex author's works (up to
600 works fetched per candidate).

- Overall title coverage: min 0.398, **Q1 0.730, median 0.800, Q3 0.872**, max 1.0, mean 0.789.
- Recent (year >= 2024) coverage, over the 345 auto-matches that have 2024+ dump pubs:
  **Q1 0.769, median 0.882, Q3 1.0**, mean 0.856.

Recent coverage sits above overall coverage, which is the expected shape: the older long tail
of a dump has more title-formatting drift and more pre-OpenAlex-era gaps than recent work.
Read all coverage against the two standing caveats: the OpenAlex publication lag (days to
weeks) and the fact that the dump titles are an incomplete floor, not ground truth.

### Failure-mode patterns

- **No-data shells (97 rows / 7 distinct):** the single largest bucket, and almost entirely a
  dedup artifact. See the dedup finding.
- **Common-name collisions:** 20 needs-review-or-unmatched rows returned >= 8 candidates
  (crowded name space). These are the genuine hard cases: e.g. Bin Wang, Liang Meng, Ying
  Yang, ZHANG Kai (10 candidates, no clear works-overlap winner), and near-miss reviews like
  Sander van der Linden and Stephan Lewandowsky (top ~0.33 with a close runner-up). Short,
  common, or heavily-shared names are where works-overlap voting earns its place.
- **Non-latin / alt-script names:** only 3 rows carry CJK characters in the display_name;
  2 of those (Haotian Zhang 张昊天) did not auto-match, while Xiaomin Sun (孙晓敏) did.
  Volume is tiny, but the parenthesized-alt-script pattern is a real edge case for name
  cleaning.
- **Sparse / titled-name authors:** a handful of true 0-candidate misses are sparse profiles
  or names carrying academic titles the cleaner does not fully strip (e.g. "Dr. phil. Marius
  Jais" leaves a "phil." fragment; EJ Horberg and Joseph Yap Haw are genuinely thin). These
  are correct "unmatched" outcomes, not throttle artifacts: the 4 zero-candidate cases flagged
  as throttle-corrupted in the partial run were re-searched cleanly on the keyed pool, and one
  of them (Marina Milyavskaya, 107 dump pubs) recovered to a confident auto-match at 0.867.
- **Prolific authors (>= 200 dump pubs) with < 60% coverage:** 5. This is the OpenAlex
  600-works fetch cap and title-formatting drift, not a wrong match (scores are still high).
- **Review queue is small and mostly easy:** 20 needs-review total, 17 with a top score
  >= 0.3 (likely-correct, quick human confirm).

### Cross-user dedup finding

The 492 profile rows cover only **253 distinct scholar_ids**, and **239** of those are
followed by BOTH Justin and dad. Concretely: 82 authors are auto-matched for one user but a
bare no-data shell for the other, so a shared resolved identity would immediately cure 90 of
the 97 no-data shells. This is direct evidence for the [identity model](identity-model.md):
key `FollowedAuthor` on a resolved identifier and share one canonical resolution across users,
with per-user follow rows on top. It roughly halves the true match-plus-review workload.

### Provider-etiquette lessons (feed the provider-contracts spec)

The run doubled as a live test of OpenAlex etiquette, and every finding argues for
**per-provider persisted rate clocks as a core feature, not a nicety**:

- **A ~2 requests/second sustained ceiling is the safe operating point.** The 2026-07-21
  bursts that ran hotter triggered the block; the 2026-07-22 completion run held <= 2 req/s
  with exponential backoff and saw zero 429s across 1287 requests.
- **Keyed and anonymous pools are separate.** The recovered polite-pool API key sailed
  through while anonymous requests from the same IP were still blocked. The rewrite should
  treat "has a provider key" as its own rate-limit lane and persist the key per provider.
- **IP-level blocks outlast the daily reset.** The 2026-07-21 block from bursty requests
  survived the daily quota reset and kept returning 429 to anonymous probes into the next day.
  A rate limiter that only reasons about a rolling daily quota is not enough; the clock and any
  cooldown must be **persisted across process restarts** so a restart cannot re-burst straight
  into a fresh block.

### Semantic Scholar call

**No material gap that justifies adding Semantic Scholar for coverage.** OpenAlex alone
auto-matches ~90% of distinct authors with a median title coverage of 0.80, and the residual
misses are common-name disambiguation and genuinely sparse profiles that a second aggregator
would not obviously fix. Semantic Scholar stays a possible later addition, not a v1
requirement. See the [open question](README.md#open-questions).
