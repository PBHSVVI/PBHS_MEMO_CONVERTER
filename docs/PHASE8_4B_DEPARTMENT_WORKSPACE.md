# Phase 8.4B department workspace

Phase 8.4B replaces the authenticated recent-conversions landing screen with a compact departmental paper workspace. Its hierarchy is department, work state, ownership scope, one active form tab, and a full-width paper list.

## Data sources

**My papers** continues to read the authenticated teacher's owner-scoped `jobs` rows. This preserves access to historical work before department-profile and safe-summary backfill are complete. Teacher metadata is mapped into the shared paper presentation model; absent subject or form metadata remains explicitly unclassified and is not guessed.

**All papers** reads only `public.paper_library_summary`. It does not query another teacher's raw job, canonical artifact, or storage object. Existing Phase 8.3A RLS remains the authority for department-wide visibility. Other-owner summary cards therefore present safe summary information without attempting to open a raw job or private output.

No database migration, RLS change, storage-policy change, historical backfill, or staff provisioning is part of this phase.

## Presentation

The workspace provides Mathematics and FS Mathematics departments, In progress and Completed states, All papers and My papers ownership filters, and horizontally scrollable Form 1–5 tabs. Both owner jobs and safe library summaries render through the same paper-card component. Metadata identifies a paper before its source filename; the filename remains a fallback or secondary detail.

The authenticated header now uses a white surface with navy typography, a gold structural line, and a narrow red identity accent. White and light-neutral working surfaces dominate the page. Green remains reserved for completed work, red for selected or attention indicators, and gold for identity and focus. The palette remains provisional and crest-derived rather than an official PBHS colour specification.
