# Web application

Target: React + Vite static application deployed to GitHub Pages.

Phase 0 deliberately freezes backend/security contracts before generating UI boilerplate.

Planned screens:
1. Sign in
2. Dashboard / recent conversions
3. Upload memo
4. Conversion progress
5. Review Amber/Red exceptions
6. Confirm correction
7. Download DOCX/PDF

Frontend variables:
- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_PUBLISHABLE_KEY`

No server, GitHub or AI secret may appear in `VITE_*` variables.
