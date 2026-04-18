# Alex x Raenest UI Handover Guide

## Purpose

This guide defines the UI standards needed for Raenest to own and evolve Alex with a consistent enterprise-grade experience.

## UI Direction Implemented

1. Reframed the product UI around "Alex for Raenest" and "US Shares Intelligence Layer".
2. Added a dedicated handover route: `frontend/pages/handover.tsx`.
3. Introduced reusable enterprise UI primitives:
 - `frontend/components/EnterpriseStatusStrip.tsx`
 - `frontend/components/HandoverReadinessCard.tsx`
4. Updated core pages with production-friendly status and trust signals:
 - `frontend/pages/dashboard.tsx`
 - `frontend/pages/advisor-team.tsx`
 - `frontend/pages/analysis.tsx`
5. Refreshed global style system in `frontend/styles/globals.css` with reusable surface/status classes.

## Design Tokens (Current Baseline)

The following CSS variables are the source of truth in `frontend/styles/globals.css`:

1. `--primary`: Brand action color for primary CTAs and highlights.
2. `--secondary`: Secondary supporting color.
3. `--dark`: Primary text color for headers and key labels.
4. `--success`: Positive state color.
5. `--warning`: Caution/risk state color.
6. `--danger`: Error/critical state color.

## Reusable Enterprise Components

### Enterprise Status Strip

File: `frontend/components/EnterpriseStatusStrip.tsx`

Use this at the top of operational pages to communicate:
1. Integration context (Raenest US Shares)
2. Environment (Development/Production)
3. Last analysis timestamp
4. Lightweight health indicator

### Handover Readiness Card

File: `frontend/components/HandoverReadinessCard.tsx`

Use this for:
1. Checklist-based readiness categories
2. Ownership tracking for engineering/ops/product
3. Audit-friendly summary cards

## Utility Classes Added

Defined in `frontend/styles/globals.css`:

1. `.surface-card`
2. `.surface-card-muted`
3. `.status-chip`
4. `.status-chip-info`
5. `.status-chip-success`
6. `.status-chip-warning`
7. `.status-chip-error`
8. `.enterprise-hero`

These should be reused before creating new ad-hoc card styles.

## UX Standards for Raenest Ownership

1. Every key workflow page should expose operational state (environment, freshness, health).
2. Financial insight pages should include trust language and non-advisory disclaimers.
3. Loading and empty states must be explicit and action-oriented.
4. Critical actions should have clear user feedback (toast, button state, status chips).
5. Navigation labels should remain role/task focused ("Dashboard", "Advisor Team", "Analysis", "Handover").

## Accessibility and Responsiveness

1. Maintain minimum body text size of `text-sm` for readability.
2. Keep contrast suitable for enterprise daylight usage.
3. Ensure each updated page remains mobile-safe (`grid-cols-1` fallback and responsive paddings).
4. Use semantic headings in order (`h1`, `h2`, `h3`) for screen-reader clarity.

## Production QA Checklist

1. Verify `/dashboard`, `/advisor-team`, `/analysis`, and `/handover` render correctly on mobile and desktop.
2. Confirm status strip timestamps show "Not available" gracefully when no jobs exist.
3. Confirm no layout shift when Clerk user data loads.
4. Confirm all trust/disclaimer copy is visible in footer and analysis pages.
5. Confirm no broken navigation links in desktop and mobile menus.

## Future UI Polish (Recommended)

1. Add a shared design-token TypeScript map for runtime usage.
2. Add Storybook for component-level ownership across teams.
3. Add dark-theme parity only if Raenest design system requires it.
4. Add role-based dashboard variants for support/admin/ops personas.
5. Add analytics instrumentation for critical UI actions (analysis start, retry, sync, handover view).
