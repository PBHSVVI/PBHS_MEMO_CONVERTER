# Phase 8.4A visual polish

Phase 8.4A establishes a shared visual language for the PBHS Mathematics Memo Converter before real staff onboarding. It changes presentation only: authentication, authorization, database, storage, worker, and correction behaviour are unchanged.

## Visual audit

The previous Phase 8.2 presentation was functional but still used two partly independent colour systems. The Teacher App used large rounded panels, broad spacing, and decorative treatment associated with a generic dashboard, while the standalone review workspace retained several older navy, border, and status values. Sign-in and invite setup did not state the school and department hierarchy as clearly as the application shell. Completion language also competed with secondary status information.

The revised system uses one token source at `docs/pbhs-design-tokens.css`. The Teacher App imports it during the Vite build and the standalone review page links to it directly. Page-specific CSS remains responsible for layout, while common colours, type sizes, spacing, radii, shadows, and focus treatment come from the shared source.

## Provisional crest-derived UI palette

These are accessible interface colours derived provisionally from the supplied 2026 crest. They are not presented as official PBHS brand specifications.

| Role | Token | Value |
| --- | --- | --- |
| Main text | `--pbhs-ink` | `#182028` |
| Primary navy | `--pbhs-navy` | `#172f45` |
| Navy hover | `--pbhs-navy-hover` | `#244a64` |
| Deep navy | `--pbhs-navy-deep` | `#102536` |
| Red emphasis | `--pbhs-red` | `#a91f2c` |
| Gold accent | `--pbhs-gold` | `#b98208` |
| Accessible gold text | `--pbhs-gold-text` | `#775400` |
| Semantic success | `--pbhs-green` | `#146b43` |
| Working canvas | `--pbhs-canvas` | `#eef1f0` |
| Primary surface | `--pbhs-surface` | `#ffffff` |
| Muted surface | `--pbhs-surface-muted` | `#f8f9f8` |
| Secondary text | `--pbhs-muted` | `#59636d` |
| Border | `--pbhs-border` | `#cdd3d7` |

Gold is used for identity and selected accents rather than ordinary body copy. Red is reserved for emphasis and errors, and green is reserved for success. Core foreground and background combinations meet WCAG AA normal-text contrast. Keyboard focus uses a high-contrast gold outline with an outer white halo.

## Responsive and component baseline

The authenticated shell, sign-in, invite setup, upload, processing, completion, and review surfaces use the same crest and hierarchy. The review workspace retains its accepted tools and behaviour while using denser evidence panels, clear selected states, and a sticky save area. Breakpoints cover desktop, tablet, and narrow phone layouts; button groups and review controls stack before they can clip or overflow.

The original crest remains unchanged at `web/public/branding/pbhs-125-crest.png`. A future standard crest, wordmark, or official palette can replace the corresponding asset or tokens without restructuring the application.
