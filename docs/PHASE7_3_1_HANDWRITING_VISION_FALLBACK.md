# Phase 7.3.1 — Handwriting OCR fallback

The real phone-photo acceptance image was visually clear but exposed two
production issues:

1. the JPEG used EXIF Orientation=6, while Tesseract was being fed raw pixels;
2. Tesseract remained unreliable on the handwritten `11.2.1` even after
   deterministic orientation correction.

The correction route remains local-first:

1. normalise phone EXIF orientation;
2. run Tesseract;
3. accept local OCR only when it passes the existing deterministic correction
   constraints;
4. otherwise, for image evidence only, send the small correction image to the
   approved Groq vision model `qwen/qwen3.8-27b`;
5. request transcription only through strict JSON schema;
6. run the returned identifier through the same deterministic exception/suggestion
   checks;
7. still require teacher show-back confirmation before application.

The vision model is deliberately not given the expected answer. It is asked only
to transcribe what is visibly written. Existing deterministic suggestions are
used after transcription as a validation gate.

No full memo, filename, teacher identity or unrelated source content is included
in the vision request. Provider failure leaves the correction awaiting review.
