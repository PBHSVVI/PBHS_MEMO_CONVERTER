# Phase 7.4.1 — GitHub Pages phone capture fix

Supabase Edge Functions on the shared `*.supabase.co` domain deliberately rewrite
GET `text/html` responses to `text/plain`. The QR therefore exposed raw HTML.

The phone UI is now a static GitHub Pages page:

https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/camera-handoff/

Supabase remains API-only.

The authenticated desktop function creates a random 256-bit opaque token and
returns the GitHub Pages URL with that token. The public Supabase API accepts
only the token and one JPEG/PNG upload into the pre-bound correction namespace.

One-time GitHub Pages configuration:
Repository Settings -> Pages -> Build and deployment -> Deploy from a branch ->
Branch: main -> Folder: /docs -> Save.
