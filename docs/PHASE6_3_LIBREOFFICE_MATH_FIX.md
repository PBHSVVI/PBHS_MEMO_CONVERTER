# Phase 6.3 — Hosted native-math rendering fix

## Evidence from Phase 6.2

The hosted GOLD diagnostic PDF contained the memo tables, prose, figures and
mark annotations but omitted most native Word/OMML equations. This shortened
the output to 8 pages and caused the Unicode preflight to report mathematical
symbols as missing.

Re-rendering the exact same diagnostic DOCX in the controlled local
environment, where LibreOffice Math is installed, restored the equations and
the memo paginated to 11 pages.

## Fix

The GitHub Actions runner now installs:
- libreoffice-math in addition to libreoffice-writer;
- fonts-freefont-otf and fonts-stix as additional math-capable fallbacks.

The workflow prints package/font resolution diagnostics before the worker runs.

The Phase 6.2 dual-extractor PDF checks remain active.

The pdffonts parser is also corrected. pdffonts rows are now parsed relative
to their fixed trailing columns (`encoding emb sub uni object generation`);
this prevents multi-word font-type fields from being mistaken for the
embedding flag.

No interpretation, canonicalization, arithmetic, mark, table-layout or
render-ready safety gate is weakened.
