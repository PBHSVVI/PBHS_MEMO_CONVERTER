# Memo Builder External Architecture v1

## 1. Operating model

```text
Teacher Browser
      |
      v
GitHub Pages
Static web application
      |
      v
Supabase
Auth + Postgres + private Storage + Edge Function
      |
      | workflow_dispatch(job_id)
      v
GitHub Actions
Ephemeral Ubuntu runner
      |
      v
Python Memo Engine
      |
      +--> deterministic extraction / validation / caching
      +--> AI provider router
      +--> canonical memo model
      +--> GDE renderer
      |
      v
Supabase Storage + Postgres
      |
      v
Teacher review / download
```

Google Drive is the controlled project record, standards library and benchmark archive, but is not a production-runtime dependency.

## 2. Why GitHub Actions is the pilot compute layer

The expected PBHS load is low: approximately one or two memo conversions per week. The job model therefore favours ephemeral compute over an always-on server.

GitHub Actions:
- starts only when a job is dispatched;
- provides a temporary Linux runner;
- can run Python and install document-processing tooling;
- can call external AI APIs;
- can write results back to Supabase;
- disappears after the job.

The Memo Engine must not depend on GitHub-specific APIs. GitHub Actions is only the first **Job Executor**.

Future executors may include Cloud Run or another container host.

## 3. Service boundaries

### Web application
Responsibilities:
- authentication;
- upload;
- create conversion job;
- invoke dispatch function;
- display status;
- show Amber/Red exceptions;
- submit corrections;
- confirm reinterpretations;
- download final DOCX/PDF.

The browser receives only:
- Supabase project URL;
- Supabase publishable key;
- user session token.

It never receives server, GitHub or AI secrets.

### Supabase
Responsibilities:
- Auth;
- canonical job metadata;
- user-scoped RLS;
- private source/output storage;
- exception/correction records;
- audit events;
- lightweight dispatch Edge Function.

Supabase does not perform heavy OCR, LibreOffice conversion, or long-running memo interpretation.

### GitHub Actions
Responsibilities:
- provision disposable compute;
- run Memo Engine for one job;
- provide protected secrets to the worker;
- terminate after processing.

Workflow inputs contain only `job_id` and later a controlled resume/retry mode.

### Memo Engine
Responsibilities:
- claim/read job;
- download source;
- compute hashes;
- deterministic extraction;
- page/question classification;
- selective OCR/vision;
- provider routing;
- canonical schema construction;
- deterministic validation;
- confidence overrides;
- renderer;
- output upload;
- status/event updates.

The engine is ordinary Python and remains portable.

## 4. AI tier model

### Tier 0 — No AI
Hashing, file validation, digital-text extraction, page splitting, duplicate detection, mark arithmetic, schema validation, caching, deterministic rendering.

### Tier 1 — Cheap / abundant AI
Text cleanup, classification, simple JSON extraction, structural inference.

### Tier 2 — Document / vision specialists
Poor scans, handwriting, failed equations, diagrams, tables, arrows, ticks and visual annotations.

### Tier 3 — Strong reasoning
Ambiguous mathematics or marking logic only.

### Tier 4 — Human review
Teacher resolves remaining uncertainty.

## 5. Green safety model

Green is **earned**, never self-declared by a model.

Any applicable failure below blocks Green:
- schema invalid;
- expected assigned content omitted;
- duplicate item;
- numbering conflict;
- critical symbol disagreement;
- source text and canonical maths semantic disagreement;
- observed vs computed mark mismatch;
- subtotal/final-total mismatch;
- unresolved source contradiction;
- unresolved Amber/Red exception;
- unconfirmed correction;
- required figure missing;
- required glyph/render preflight failure.

## 6. Storage structure

Private bucket target: `memo-files`

```text
{user_id}/
  {job_id}/
    source/
      original.<ext>
    pages/
      page-001.png
    internal/
      extraction.json
      canonical.json
      validation.json
    corrections/
      {correction_id}.<ext>
    output/
      memo.docx
      memo.pdf
```

Client uploads are restricted to user-owned `source/` and `corrections/` paths.
Server-side workers may write internal and output paths.

## 7. Security boundary

Frontend:
- publishable key only;
- authenticated JWT;
- direct access only where RLS permits.

Edge Function:
- verifies user JWT;
- confirms job ownership through RLS;
- uses server secret only for controlled status transition;
- stores GitHub token as function secret.

GitHub Actions:
- Supabase server secret stored in Actions secrets;
- AI keys stored in Actions secrets;
- no document content in workflow input, job name or logs.

Storage:
- private bucket;
- user can read own prefix;
- user can upload only source/correction paths;
- generated outputs written by server context.

## 8. Privacy modes reserved for later implementation

- `ALLOW_FREE_EXTERNAL`
- `APPROVED_EXTERNAL_ONLY`
- `PRIVATE_PROVIDER_ONLY`
- `LOCAL_ONLY`

## 9. Portability

The executor boundary is:

```text
dispatch(job_id) -> execute Memo Engine -> update durable job state
```

Moving from GitHub Actions to a later compute platform must not change the canonical memo schema, frontend contract, database job contract, storage layout, renderer contract or provider adapter interface.
