# Scholarr — Design Contract (DESIGN.md)

This is the binding design specification for the Scholarr web app. It is written
for the engineering team building the Vue 3 SPA. Everything visual in the app is
expressed through the tokens in `tokens.css`; every screen is a composition of the
named components below. If an implementation choice is not covered here, prefer the
option that is calmest, most honest about data, and easiest for a non-technical
seventy-year-old to understand.

The working reference implementation is `Scholarr.dc.html` (all pages, all states,
light/dark, responsive). This document is the contract; the file is the proof.

---

## 1. Product principles that shape the UI

1. **Honesty about sources is a feature.** Never fake real-time. Show "last delivered"
   facts and set the expectation that data lags reality by days to weeks. Every source
   has a visible health state.
2. **Identity is probabilistic.** Matching a followed name to a database identity has a
   confidence level. Ambiguous cases go to a human review queue — a first-class daily
   surface, not an admin afterthought.
3. **Nothing destructive by default.** Bulk actions preview and count before they act;
   every consequential decision is undoable.
4. **Two audiences, one app.** The founding user is a retired academic who wants to know
   "anything new for me?" in one glance. The admin wants dense, clutter-free control.
   The Dashboard belongs to the reader; Sources/Activity/Settings belong to the admin.
5. **Self-hostable and private.** System-font stacks only; no CDN, no externally loaded
   fonts, no third-party assets.

---

## 2. Signature & aesthetic

- **Concept: "the living bibliography."** The reading surface is typeset like a reference
  list — serif titles, monospace identifiers (DOIs, arXiv IDs), a measured reading column.
- **Signature element:** the mortarboard-with-descending-binary logo (bundled as
  `logo-light-tight.png` / `logo-dark-tight.png`), echoed by the honest **"as of" / "last
  delivered" freshness stamps** that appear anywhere data is shown.
- **Type roles:** serif for titles & publication entries; sans for all chrome/UI; mono for
  identifiers, timestamps, counts and uppercase micro-labels. Never set body UI in serif.
- **Restraint:** at most two background tones per screen. The binary motif appears only in
  the logo — never as decoration.

---

## 3. Color tokens

Authored in oklch (see `tokens.css`); sRGB hex below for tools that need it. Semantic
colors are shared by two vocabularies: **matching confidence** and **source health**.

| Token | Role | Light | Dark |
|---|---|---|---|
| `--paper` | app background | `#fcfaf6` | `#161719` |
| `--surface` | cards, panels | `#fffefc` | `#1f2123` |
| `--surface-2` | insets, hover, skeleton | `#f6f3ee` | `#2b2d30` |
| `--ink` | primary text | `#29231d` | `#e9ebee` |
| `--ink-soft` | secondary text | `#5d5751` | `#afb1b4` |
| `--ink-faint` | meta / disabled | `#8b8580` | `#7e8084` |
| `--line` | hairline borders | `#e1ddd9` | `#35373a` |
| `--line-strong` | control borders | `#cbc6c1` | `#505357` |
| `--accent` | primary action fill | `#2e6799` | `#6aaae6` |
| `--accent-soft` | tinted backgrounds | `#dceeff` | `#1f3654` |
| `--accent-ink` | accent text | `#055085` | `#98cdff` |
| `--hi` / `--hi-soft` | **healthy / confident** | `#519160` / `#d9f3dd` | `#6cc185` / `#193d2f` |
| `--mid` / `--mid-soft` | **cooling down / likely** | `#bd8630` / `#fce9c6` | `#deaf56` / `#46381a` |
| `--low` / `--low-soft` | **failing / uncertain** | `#c0453f` / `#ffe0d8` | `#f47c6e` / `#562e27` |

Rules: text on `--paper`/`--surface` uses `--ink`/`--ink-soft`. Solid `--accent`/`--hi`/
`--mid`/`--low` fills always pair with near-white text (`oklch(0.99 0 0)`) — verify AA.
`-soft` tokens are backgrounds only; pair with the matching solid token for text.

---

## 4. Typography

| Role | Font | Size | Weight | Notes |
|---|---|---|---|---|
| Page title (H1) | serif | `clamp(21px, 4vw, 27px)` | 700 | letter-spacing −0.015em |
| Section / card title | serif | 15–17px | 700 | |
| Publication title | serif | 14.5–16.5px | 700 unread / 500 read | `text-wrap: pretty` |
| Body | sans | 13–14px | 400–500 | line-height 1.45 |
| Meta / secondary | sans | 11.5–12.5px | 400 | `--ink-soft` |
| Identifiers, timestamps, counts | mono | 10.5–11.5px | 400–700 | `--ink-faint` |
| Uppercase micro-label | mono | 10px | 700 | letter-spacing 0.08–0.12em |

Minimum body text 12px. Titles truncate to one line with ellipsis in dense lists; wrap in
detail/feed views.

---

## 5. Space, radius, elevation

- **Space scale:** 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40. Lay groups out with flex/grid + `gap`.
- **Radius:** `--r-sm` 6 (controls), `--r-md` 10 (option cards), `--r-lg` 16 (panels), `--r-pill` 20 (chips/badges).
- **Elevation:** `--sh-1` resting cards; `--sh-2` overlays (mobile bars, modals, toasts). Borders (`--line`) do most of the separation work; shadows are subtle.
- **Reading column:** dashboard ≤ 780px, publications/authors ≤ 1100px, detail/review/forms ≤ 820–900px, centered.

---

## 6. The two badge vocabularies

Both render as a pill: `--r-pill`, mono 10–11px 700, `-soft` background + solid-token text,
optional leading dot. **These words are the end-user language — do not show raw scores or
internal states in the UI.**

### Matching confidence (author identity)
| Internal | Badge label | Token | When |
|---|---|---|---|
| high (≥ ~90%) | **Confident** | `--hi` | Identifiers + works agree across sources |
| medium | **Likely** | `--mid` | Probable, but the name is shared — worth a look |
| low | **Uncertain** | `--low` | Weak evidence; review before trusting |
| shell | **Not yet identified** | `--ink-faint` | A name with no database identity |

### Source health
| Internal | Badge label | Token | Plain-language meaning |
|---|---|---|---|
| healthy | **Healthy** | `--hi` | Delivering normally |
| cooling | **Cooling down** | `--mid` | We asked too fast; the source told us to slow down. Resumes on its own. |
| failing | **Not connected** | `--low` | Sign-in/credentials failed; matching continues from other sources |

### Open-access availability (per publication)
`◈ OA` (`--hi`) available · `◇ ?` (`--ink-faint`) checking Unpaywall · `⊘` (`--low`) no free PDF found.

---

## 7. Component inventory (with states)

Every component below is component-shaped: repeated instances are structurally identical,
styled only through tokens, translatable 1:1 to a scoped Vue component.

- **Buttons** — *primary* (`--accent` fill, near-white text), *secondary* (`--surface` +
  `--line-strong` border), *ghost* (transparent, `--ink-soft`), *destructive-lite*
  (`--low` text on `--surface`). States: default / hover (`--surface-2` or darker accent) /
  focus-visible (2px `--accent` ring) / disabled (`--ink-faint`, dashed border for
  unavailable actions like a missing PDF) / active-pressed.
- **Inputs & selects** — `--surface-2` fill, `--line-strong` border, label in `--ink-soft`
  12px. Focus ring as global. (Static in mockups; real fields in Vue.)
- **Filter chips / segmented control** — pill, active = `--accent-soft` bg + `--accent-ink`
  text + `--accent` border; inactive = `--surface` + `--line`. Optional mono count sub-pill.
- **List row (publication)** — `[unread dot] [field tag · serif title (truncate)] [meta line:
  authors · venue · year · id · source] [NEW marker slot] [OA badge] [PDF button] [read toggle]`.
  Unread: filled `--unread` dot with `--accent-soft` halo, title 700. Read: hollow dot,
  title 500, row opacity 0.66. Hover: `--surface-2`.
- **List row (author)** — `[checkbox] [avatar] [name (+ transliteration)] [field] [confidence
  badge] [last sync] [new count]`. Selectable; header row labels the columns.
- **Table header** — mono uppercase micro-labels, `--line` bottom border.
- **Cards / panels** — `--surface`, `--line` border, `--r-lg`, `--sh-1`; header row with serif
  title + optional mono meta, hairline-separated body.
- **Avatar** — circle, initials, `--surface-2` (neutral) or `--accent-soft` (self/active).
- **Badges** — confidence / source-health / OA / role, per §6.
- **Freshness stamp** — mono `--ink-faint`, always phrased "as of …" or "last delivered …".
- **Progress bar** — 6px track `--surface-2`, `--accent` fill (review queue, bulk import).
- **Modal / overlay** — `--surface`, `--sh-2`, `--r-lg`; dim scrim. (Pattern; compose as needed.)
- **Toast** — `-soft` bg + matching solid icon + `--sh-2`; auto-dismiss, carries an Undo action
  for consequential changes.
- **Empty state** — centered glyph + serif headline + one sentence of `--ink-soft` guidance +
  one primary action. Never a dead end.
- **Skeleton** — `--surface-2`→`--line` shimmer, respects reduced-motion (freezes). Mirrors the
  real row's shape and count.
- **Bottom tab bar (mobile)** — fixed, `--surface`, `--sh-2`, 5 destinations, badge dots.

### Required states per page
Populated, **empty**, **loading (skeleton)**, and **degraded** are demonstrated in the
reference file. Degraded truths that must remain visible: a cooling-down source (Unpaywall),
a not-connected source (ORCID), an unresolvable PDF, an author shell, and a
three-plausible-candidates review case.

---

## 8. Interaction patterns

- **Navigation** — persistent collapsible left sidebar on desktop; a fixed bottom tab bar on
  phone. The nav must never scroll horizontally (v1's bug). Below 760px the sidebar is replaced,
  not shrunk.
- **Theme** — system / light / dark switch. System follows `prefers-color-scheme`; explicit
  choice sets `data-theme` on the root.
- **Bulk selection** — row checkboxes reveal a selection bar with count + non-destructive actions
  (re-sync, send to review) + Clear. Nothing acts without an explicit button.
- **Keyboard triage (Review queue)** — one decision at a time. `1`/`2`/`3` choose a candidate,
  `S` skip, `U` undo, `J`/`K` (or ↑/↓) move. Visible `<kbd>` hints. Every decision is reversible.
- **Undo** — bulk imports and review decisions are undoable; imports can be reversed from Activity.
- **Freshness** — show relative times ("2h ago") plus absolute where precision matters. Never imply
  live data.

---

## 9. Copy rules & phrase glossary

- Address the reader plainly and warmly; avoid jargon and internal terms.
- **No em dashes.** Use periods, commas, or a middot (·) separator.
- Numbers and identifiers in mono; prose in sans.
- Never say "scraped", "crawler", "confidence score 0.71", "rate-limited (HTTP 429)". Say the
  plain-language equivalent.

| Say this | Not this |
|---|---|
| Confident match / Likely / Uncertain | 0.98 / 0.71 / 0.48, high/med/low |
| Not yet identified (author shell) | null identity, orphan record |
| Cooling down — resumes on its own | rate-limited, HTTP 429, backoff |
| Not connected — sign-in was rejected | auth failure 401 |
| No free PDF found | Unpaywall miss |
| open-access PDF | OA green/gold, self-archived |
| last delivered 2h ago / as of … | live, real-time, up to the second |
| We will keep checking on schedule | polling, cron |

---

## 10. Accessibility

- **Contrast:** WCAG AA for all text and meaningful UI. Verify solid-fill + near-white text and
  every `-soft`/solid pairing in both themes.
- **Focus:** visible 2px `--accent` ring on every interactive element (`:focus-visible`).
- **Reduced motion:** `prefers-reduced-motion` freezes skeleton shimmer and all transitions.
- **Color is never the only signal:** confidence and health always pair the color with a word
  (and often a dot/icon); unread/read pair color with dot fill and weight.
- **Targets:** ≥ 44px hit targets on mobile controls.
- **Semantics:** real headings, buttons for actions, labels tied to inputs; transliterated names
  carry the Latinized form alongside.

---

## 11. Vue 3 mapping notes

- Ship `tokens.css` once at the app root; never hard-code a color, font, radius, or shadow —
  reference a `var(--token)`. Theme switching only toggles `data-theme` on the root.
- Each component in §7 becomes one scoped SFC. Keep markup identical across repeated instances
  (the reference file already does this) so the port is mechanical.
- Derived styles that depend on data (confidence color, read/unread weight, active chip) should
  be computed props returning token names, not literal colors.
- No technique in the reference relies on anything Vue-hostile: no global class cascade beyond
  tokens + a few resets, no runtime style injection, no third-party fonts or assets.


---

## 3b. Contrast proof (WCAG AA)

Measured contrast ratios for every token pairing used for **text** (AA needs 4.5:1 for body, 3:1 for large). Ratios ≥ 4.5 unless noted.

New text-safe tokens added this round: `--hi-ink` / `--mid-ink` / `--low-ink` (AA text on the matching `-soft` background), and `--on-accent` (text on solid fills — flips near-white in light, near-black in dark).

| Pairing | Light | Dark |
|---|---|---|
| `--ink` on `--surface` | 15.4 | 13.5 |
| `--ink-soft` on `--surface` | 7.1 | 7.5 |
| `--ink-faint` on `--surface` | 4.8 | 5.2 |
| `--accent-ink` on `--surface` | 8.4 | 9.6 |
| `--accent-ink` on `--accent-soft` | 7.1 | 7.3 |
| `--hi-ink` on `--hi-soft` | 6.2 | 7.9 |
| `--mid-ink` on `--mid-soft` | 6.4 | 7.4 |
| `--low-ink` on `--low-soft` | 6.0 | 6.3 |
| `--on-accent` on `--accent` (primary btn) | 5.8 | 7.7 |
| `--on-accent` on `--low` (destructive btn) | 4.9 | 7.2 |

Rule that made the earlier "Likely / Cooling down" badge (2.66:1) pass: **solid semantic colours (`--hi`/`--mid`/`--low`) are never used as badge text.** Badge text is always the `-ink` variant on the `-soft` background. Solid fills only ever carry `--on-accent` text, and only for `--accent`/`--low` (never `--hi`/`--mid`, whose light-theme solids fail with white). `--ink-faint` was darkened to clear AA on `--surface`.

## 12. Motion & interaction spec

Tokens (in `tokens.css`): `--dur-fast` 120ms, `--dur-base` 180ms, `--dur-slow` 260ms; `--ease-out` cubic-bezier(.2,0,0,1), `--ease-in-out` cubic-bezier(.4,0,.2,1).

- **Animates:** hover/focus colour transitions (fast); toggle-switch knob (base); filter/theme chip selection (fast); skeleton shimmer (1.4s loop); toast slide-up + fade (base); modal scrim fade + card rise (base); tooltip fade+rise (fast).
- **Never animates:** content arriving from a sync (rows appear without shifting neighbours — reserve space with skeletons); route/screen changes (instant, no cross-fade — this is a data tool); numbers/counts (no count-up); the reading list on mark-read (opacity change only, no reflow/animation of position).
- **Reduced motion** (`prefers-reduced-motion: reduce`, handled globally in tokens.css): all transitions/animations collapse to ~0ms; skeleton shimmer freezes to a static tint; tooltips and toasts appear/disappear instantly; no scroll animation.

**Keyboard triage (Review queue)** — one decision on screen at a time:

| Key | Action |
|---|---|
| `1` `2` `3` | Choose candidate 1/2/3 |
| `S` | Skip (decide later) |
| `U` | Undo last decision |
| `J` / `↓` | Next item |
| `K` / `↑` | Previous item |

Every decision is reversible; the queue shows progress (`n of N`) and an always-available Undo. Nothing is committed to the shared identity graph until the user decides.

**Bulk selection** (Authors): row checkboxes reveal a selection bar with a live count and only non-destructive actions (Re-sync, Send to review) plus Clear. No action fires without an explicit button press; destructive operations route through the confirm modal (§17).

## 13. Responsive spec

Breakpoint: **phone < 760px**, **wide ≥ 760px** (single breakpoint by design — the tool is comfortable on a 13" laptop, usable on a phone). Documented as `--bp-phone: 760px`; because custom properties can't drive `@media`, the Vue app defines the query once in a composable and the value must match this token.

Per-surface reflow:
- **Navigation:** wide = persistent left sidebar (collapsible to 64px icon rail); phone = fixed **bottom tab bar** + a slim top bar. The nav never scrolls horizontally (the v1 bug). Below 760 the sidebar is *replaced*, not shrunk.
- **Dashboard:** hero + feed stack to one column; the "new work from" author chips wrap.
- **Publications:** rows keep their shape; the meta line truncates with ellipsis; filter chips scroll inside their own contained track (never the page).
- **Authors table:** columns drop progressively on phone — keep Author + Identity(confidence) + New; hide Field and Last-sync (available in author detail). The row stays the same component, columns toggle via the breakpoint.
- **Author detail / Add / Review / forms:** two-column layouts collapse to one; the identity panel moves below the publications list.
- **Modal:** full-width minus 20px margin on phone; **toast** spans near-full width, bottom, above the tab bar.
- Reading-column caps: dashboard 780, publications/authors 1100, detail/sources/activity 900, review/add/forms 820.

## 14. Form rules

- **Labels above inputs**, 12px `--ink-soft` 600. Required fields marked with `*` in `--low-ink` and stated once ("Fields marked * are required").
- **Validation on save**, not per keystroke (calm for the founding user). On failure: input gets `--low` border, an inline message below the field (`--low-ink`, 11.5px, leading `warning` icon), AA-legible; focus moves to the first invalid field.
- **Submit states:** default "Save changes" → disabled "Saving…" → success shows an inline "saved" banner (`--hi-soft`/`--hi-ink` + check) AND a toast. Cancel reverts to the read-only view with no change.
- Read-only view shows values as plain text (not disabled inputs); an explicit **Edit** button enters the form. This mirrors the Settings → Profile states (view / editing / error / saving / saved).

## 15. Copy glossary (complete — one term per concept)

Confidence: **Confident** · **Likely** · **Uncertain** · **Not yet identified** (shell).
Source health: **Healthy** · **Cooling down** · **Not connected**.
Open access: **open-access PDF** (available) · **checking** (Unpaywall resolving) · **no free PDF** (none found).
Freshness (always relative + honest, never "live"): **"last delivered {t}"**, **"as of {t}"**, **"last checked {t}"**, **"Up to date · {t}"**, **"arXiv can run a day or two behind. That is normal."**
Review actions: **Skip for now** · **Undo** · **None of these** / **Reject match** / **Keep separate** / **Keep both** / **Leave as shell** (reject label varies by case) · **Merge** (duplicates).
Bulk import: **"We checked your {n} lines before importing anything"**, **"look valid"**, **"could not be read"**, **"duplicates within your list"**, **"already in your followed list"**, **"Follow {n} confident matches"**, **"Send {n} to review"**, **"Safe by default: nothing is followed until you confirm."**
Empty states (one line each): Publications "Nothing to read yet." · Authors "You are not following anyone yet." · Author detail "No publications from this author are in your library yet." · Review "Queue is clear." · Sources "No sources connected yet." · Dashboard feed "You are all caught up."
Error patterns: **404** "That page is not on the shelf. … Nothing is broken." · Login fail "That username or password was not recognised. Please try again." · Field "Enter a valid email address, for example name@example.org." · Source fail "Not delivering. Sign-in or credentials failed; the other sources keep working."
Destructive confirm: **"Remove {name}?"** + what is and isn't affected + **"Remove user"** / **Cancel**; success toast **"{name} was removed. Undo?"**
Never shown to users: raw scores/percentages as the label, "scraped", "crawler", "rate-limited/429", "auth 401", "polling/cron", "real-time".

## 16. Icon set

All icons: 24×24 viewBox, `fill:none; stroke:currentColor; stroke-width:1.8; round caps/joins`. Shipped as `assets/icons/{name}.svg` and as an inline `<symbol id="ic-{name}">` sprite. Inherit colour from context; size via width/height.

`dashboard` (nav: home/overview) · `publications` (nav: reading list) · `authors` (nav: followed people) · `review` (nav: identity triage / balance) · `sources` (nav: data providers / database) · `activity` (nav: sync history) · `settings` (nav: gear) · `search` · `check` (read / confirmed / valid) · `circle` (unread-toggle empty / read-only) · `dot` (filled status dot) · `plus` (add) · `external` (outbound link / open PDF in new tab) · `chev-left` / `chev-right` (collapse / paginate) · `arrow-left` (back) · `undo` · `sun` / `moon` / `system` (theme) · `signout` · `warning` (caution / validation) · `x` (close / remove) · `oa` (open padlock = open-access available) · `lock` (closed padlock = no free PDF) · `pending` (dashed circle = checking) · `book` (empty reading state) · `upload` (bulk import) · `eye` (colour-blind toggle).

Typographic characters kept intentionally (NOT icons): `→` `←` `·` in prose/buttons. No em dashes anywhere.

## 17. Global patterns

- **Toast + undo:** bottom-centre, inverse surface (`--ink` bg / `--paper` text), one at a time, auto-dismiss 5s, always offers **Undo** for consequential changes. New toast replaces the current one.
- **Modal / confirm dialog:** scrim (`oklch(.2 .02 60/.5)`) + centred `--surface` card, `--sh-2`, title (serif) + body + footer actions right-aligned (Cancel secondary, destructive uses `--low` fill + `--on-accent`). Used for every destructive action (delete user, remove author with follow-data, reconnect source).
- **404:** full-bleed, in the product's calm voice, reassures nothing is broken, single primary action back to the dashboard.
- **Reader (non-admin) view:** admin-only surfaces are **hidden, not disabled** — Sources and Activity drop out of the nav; Users & roles, Sign-in and Source-credentials sections drop out of Settings. Toggle via "View as" (demo affordance; in production the role comes from the account).
- **Tooltips:** hover **and** keyboard-focus reveal (`.tip`/`.tip-pop`), used to explain status badges in place (replaces a static legend). Instant under reduced motion.
- **Colour-blind mode:** adds solid/dashed/dotted outlines to status badges so the three-stop scale is distinguishable without hue; toggle in the sidebar and in Settings → Accessibility; persisted in `localStorage` (`scholarr-cb`). Colour is never the only signal even with the mode off (every badge carries a word).

## 18. Build note — support.js is tool-only

The reference implementation `Scholarr.dc.html` loads a small runtime (`support.js`) that belongs to **the design tool only**. It is **not part of the production build and must not be shipped**. The Vue app reproduces the same markup and behaviour natively; every page must render correctly with no `support.js` present. The only runtime assets are `tokens.css`, the icon SVGs, the logos and the favicons.

## 19. Vue handoff appendix

**Theming strategy (pick one, this is it):** attribute strategy — `data-theme` on the root element, with `prefers-color-scheme` as the default when the attribute is absent (exactly as `tokens.css` is written). No component sets a raw colour; **all** colour/space/radius/shadow/motion flows through `var(--token)`. Scoped Vue `<style>` blocks reference tokens only.

**Component tree & responsibilities:**

- `AppShell` — CSS grid, owns theme + role + colour-blind state; slots `PrimaryNav`, the active view, `MobileTabBar`, `ToastHost`, `ModalHost`.
  - `PrimaryNav` (sidebar; `collapsed` prop) → `NavItem`(icon, label, badge, active), `ThemeSwitch`(model system|light|dark), `ColorblindToggle`, `RoleSwitch`, `UserCard`.
  - `MobileTabBar` → `TabItem`(icon, label, badge).
  - Views (one per route): `DashboardView`, `PublicationsView`, `AuthorsView`, `AuthorDetailView`, `ReviewView`, `AddAuthorView`, `BulkImportView`, `SourcesView`, `ActivityView`, `SettingsView`, `LoginView`, `OnboardingView`, `NotFoundView`.
- Shared components (props → slots):
  - `PageHeader`(title, meta, actions-slot)
  - `FreshnessStamp`(kind: last-delivered|as-of|last-checked, time)
  - `ConfidencePill`(level: high|medium|low|shell) — renders label + tooltip; reads colour-blind flag for outline.
  - `SourceHealthBadge`(state: healthy|cooling|failing) and `SourceHealthCard`(source) with reconnect action.
  - `OaBadge`(status: pdf|pending|none) — icon + label + tooltip.
  - `PubRow`(pub, read, isNew; emits open-pdf, toggle-read) — the bibliography-style entry.
  - `AuthorRow`(author, selected; emits toggle-select, open).
  - `FilterChip`(label, count, active), `StatePreviewToggle` (dev-only, remove in prod).
  - `Skeleton`(shape: row|card, count), `EmptyState`(icon, title, body, action-slot).
  - `Tooltip` (`.tip`/`.tip-pop`; hover + focus).
  - `Modal` / `ConfirmDialog`(title, body, confirmLabel, destructive) — emits confirm/cancel.
  - `Toast`(message, undo) via `ToastHost`.
  - `Card`, `Button`(variant: primary|secondary|ghost|danger; disabled), `Field`(label, required, error), `ToggleSwitch`(checked), `Avatar`(initials, tone).
  - `TriageDeck` (Review) — current item + keyboard handling + progress + undo.
  - `CandidateCard` (Add author disambiguation), `BulkStepper` (import phases).

Repeated markup is already identical instance-to-instance in the reference file, so each maps to one component with no structural surprises.

## 20. Asset finalization

- **Logos:** `assets/logo-light.png` (dark mark, for light backgrounds) and `assets/logo-dark.png` (light mark, for dark backgrounds). The app swaps by effective theme. Minimum display 24px; clear space ≥ 25% of the mark's height on all sides; never recolour, rotate, or stretch — the descending-binary tail is part of the mark and the signature.
- **Favicons / PWA:** `assets/favicon.png` and `assets/favicon-512.png` (maskable-safe square).
- **Icons:** `assets/icons/*.svg` (29 files) plus the inline sprite; `currentColor`, 24 viewBox, 1.8 stroke — see §16.

## 21. Deliverables in this package

- `Scholarr.dc.html` — the living reference implementation: all 13 screens, every state (populated / loading / empty / degraded), light + dark, responsive, colour-blind mode, working review triage, confirm modal, undo toast, 404. (Runs on the tool's support.js — see §18; not shipped.)
- `component-reference.html` — every component in its states, both themes, self-contained (links `tokens.css`, own stylesheet, vanilla-JS theme/colour-blind toggles). Open it directly.
- `tokens.css` — the frozen token layer (colour incl. `-ink`/`--on-accent`, type, space, radius, elevation, motion).
- `DESIGN.md` — this contract.
- `assets/` — icons, logos, favicons.
