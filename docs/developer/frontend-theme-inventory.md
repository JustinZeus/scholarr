---
title: Frontend Theme Inventory
sidebar_position: 6
---

# Frontend Theme Inventory

## Token Domains

The theme system uses semantic tokens organized into domains:

### Scale Colors

Color ramps from `50` to `950` for each intent:

- `brand` - Primary brand color
- `info` - Informational elements
- `success` - Success states
- `warning` - Warning states
- `danger` - Error/destructive states

### Surface

Background colors for major UI areas:

| Token | Usage |
|-------|-------|
| `app` | Application background |
| `nav` | Navigation bar |
| `nav_active` | Active navigation item |
| `card` | Card backgrounds |
| `card_muted` | Muted card variant |
| `table` | Table body |
| `table_header` | Table header |
| `input` | Form inputs |
| `overlay` | Modal/dialog overlays |

### Text

| Token | Usage |
|-------|-------|
| `primary` | Default text |
| `secondary` | Supporting text |
| `muted` | Disabled/placeholder text |
| `inverse` | Text on dark backgrounds |
| `link` | Hyperlinks |

### Border

| Token | Usage |
|-------|-------|
| `default` | Standard borders |
| `strong` | Emphasized borders |
| `subtle` | Light separators |
| `interactive` | Hover/focus borders |

### Focus

| Token | Usage |
|-------|-------|
| `ring` | Focus ring color |
| `ring_offset` | Focus ring offset color |

### Action Variants

Each action type (`primary`, `secondary`, `ghost`, `danger`) provides:

`bg`, `border`, `text`, `hover_bg`, `hover_border`, `hover_text`

### State Variants

Each state (`info`, `success`, `warning`, `danger`) provides:

`bg`, `border`, `text`

## Theme Presets

Presets are loaded from `frontend/src/theme/presets/*.{json,js}`. Each contains both `light` and `dark` mode token definitions.

Current presets:

| Preset | Format |
|--------|--------|
| `parchment` | JS |
| `lilac` | JS |
| `dune` | JS |
| `oatmeal` | JS |
| `scholarly` | JSON |
| `graphite` | JSON |
| `tide` | JSON |

## Tokenized Components

Foundation components using the token system:

- `AppButton`, `AppCard`, `AppCheckbox`, `AppEmptyState`
- `AppHelpHint`, `AppInput`, `AppSelect`, `AppTable`
- `AppModal`, `AppHeader`, `AppNav`, `AppAlert`
- `AppBadge`, `RunStatusBadge`, `QueueHealthBadge`

## Enforcement

- Token policy check: `frontend/scripts/check_theme_tokens.mjs`
- CI step in `frontend-quality` workflow
- Preset integrity tests: `frontend/src/theme/presets.test.ts`
