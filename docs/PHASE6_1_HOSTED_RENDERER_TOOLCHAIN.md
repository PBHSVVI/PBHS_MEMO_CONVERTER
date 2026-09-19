# Phase 6.1 — Hosted Renderer Toolchain

The first hosted Phase 6 acceptance run proved that RAW remained blocked and that
GOLD reached a clean 150/150 renderer-ready canonical state. Rendering then stopped
because Pandoc was absent from the GitHub Actions Ubuntu runner.

This hotfix changes only runner provisioning. It installs/verifies Tesseract,
Pandoc, LibreOffice Writer, Poppler pdffonts, and approved glyph-complete Linux
fallback fonts (DejaVu, Noto and Liberation). No interpretation, canonicalization,
arithmetic, renderer, layout, or mark logic changes.
