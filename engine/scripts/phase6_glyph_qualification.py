from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader

REQUIRED_GLYPHS = "∴≤≥≠±−×÷√∈∪∩∅∞∠⟂∥≅✓"

MARKDOWN = r'''# Phase 6 Glyph Qualification

Required glyphs: ∴ ≤ ≥ ≠ ± − × ÷ √ ∈ ∪ ∩ ∅ ∞ ∠ ⟂ ∥ ≅ ✓

Representative native mathematics:

$$\frac{x^2+\sqrt{a^2+b^2}}{2y_1} \leq 5,\quad x\neq 0,\quad x\in\left(-\infty;2\right]\cup\left(3;\infty\right)$$

$$\sin\theta+\cos\alpha=1,\quad \angle ABC=90^\circ,\quad AB\perp BC,\quad DE\parallel AC$$

$$A\cong B,\quad \varnothing,\quad \pm 3,\quad 4\times5\div2=10$$
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="phase6-glyph-qualification")
    args = parser.parse_args()

    pandoc = shutil.which("pandoc")
    office = shutil.which("libreoffice") or shutil.which("soffice")
    if not pandoc or not office:
        raise SystemExit("Pandoc and LibreOffice are required.")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md = out / "qualification.md"
    docx = out / "qualification.docx"
    md.write_text(MARKDOWN, encoding="utf-8")

    subprocess.run([pandoc, str(md), "-o", str(docx)], check=True, timeout=120)
    with tempfile.TemporaryDirectory(prefix="pbhs-lo-") as profile:
        subprocess.run(
            [
                office,
                "--headless",
                f"-env:UserInstallation=file://{profile}/profile",
                "--convert-to",
                "pdf",
                "--outdir",
                str(out),
                str(docx),
            ],
            check=True,
            timeout=180,
        )

    pdf = out / "qualification.pdf"
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf)).pages)
    missing = [glyph for glyph in REQUIRED_GLYPHS if glyph not in text]
    if missing:
        raise SystemExit(f"Qualification failed; missing glyphs: {missing}")

    if "�" in text:
        raise SystemExit("Qualification failed; replacement character detected.")

    print(f"PASS: all {len(REQUIRED_GLYPHS)} required glyphs survived DOCX -> PDF.")
    print(docx)
    print(pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
