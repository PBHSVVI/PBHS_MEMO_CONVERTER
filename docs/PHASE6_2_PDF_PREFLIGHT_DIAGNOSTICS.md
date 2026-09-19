# Phase 6.2 — PDF preflight diagnostics and dual extraction

The Phase 6.1 hosted GOLD run reached a valid 150/150 canonical object and
successfully entered rendering, but failed the generic PDF preflight gate.

This patch does not weaken the rendering gate.

Changes:
- uses both pypdf and Poppler pdftotext for Unicode codepoint verification;
- treats a required glyph as preserved when either independent extractor
  recovers that exact codepoint;
- keeps replacement-character, page, total and font-embedding checks active;
- parses pdffonts using fixed-width columns more robustly;
- logs exact preflight issue codes;
- on failure, stores the generated DOCX, PDF and preflight JSON under the
  private internal/render_failure namespace;
- emits a phase6_render_failed audit event containing issue codes and paths.

A failed render remains failed_retryable and no diagnostic output is promoted
to the normal output namespace.
