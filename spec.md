# books-ai API — spec (implemented)

This document describes what exists in the repository today and the intended operational behavior in Kubernetes.

## Product intent

`books-ai` is a small REST API + Postgres database that:

- Allows users to **query books** by title, author (last name), or ISBN.
- Allows users to **create a book record** by title + author. Creation is gated by an **AWS Bedrock LLM existence check** ("does this book exist? yes/no"). If the LLM says "yes", the record is created with a generated 13‑digit ISBN and a Bedrock-generated summary.
- Allows users to **delete a book** by ISBN.

The system is designed to continuously generate meaningful **LLM telemetry** (tokens, prompt/response previews, and message content in span events) so it can be analyzed in **groundcover**.

## API surface (FastAPI)

Base: the service listens on port 8000 (k8s Service exposes port 80 → 8000).

- `GET /health`
  - Returns: `{ "status": "ok" }`
- `GET /books/title?title=...`
  - Returns a single book:
    - `isbn`, `title`, `author_first_name`, `author_last_name`, `summary`, `created_at`
  - `404` if not found.
- `GET /books/author?author_last_name=...`
  - Returns:
    - `author_first_name`, `author_last_name`, `titles: [BookRead...]`
  - `404` if no books found for that author.
- `GET /books/isbn/{isbn}`
  - Returns a single book (`BookRead`).
  - `404` if not found.
- `POST /books`
  - Body:
    - `title`, `author_first_name`, `author_last_name`
  - Behavior:
    - If title already exists in DB: returns `{ created: false, book: ..., note: "Book already exists" }`
    - If title does not exist:
      - Calls Bedrock to check existence (strict yes/no).
      - If "yes": creates row with generated ISBN and Bedrock summary; returns `{ created: true, book: ... }`
      - If "no": returns `422` with Bedrock-generated suggestions in `detail`
- `DELETE /books/{isbn}`
  - Returns `{ deleted: true, isbn: "..." }`
  - `404` if not found.

## Data model

Postgres schema: `books`

Table: `books.books`

- `isbn` (VARCHAR(13), primary key)
- `title` (VARCHAR(512), indexed)
- `author_first_name` (VARCHAR(256))
- `author_last_name` (VARCHAR(256), indexed)
- `summary` (TEXT nullable)
- `created_at` (TIMESTAMPTZ default now())

## Bedrock interaction (LLM behavior)

On create (`POST /books` when not already present):

- **Existence check**: prompt requires a strict `'yes'` or `'no'` answer; unsure must be `'no'`.
- **Summary generation**: if exists, requests a concise 3–5 sentence summary.
- **Suggestions**: if not exists, requests up to 3 likely intended titles/authors.

The design goal is that prompts are **highly parseable** and the API can make deterministic decisions from model output.

## Observability (OpenLLMetry + groundcover)

This service is instrumented with OpenLLMetry (Traceloop SDK): `https://github.com/traceloop/openllmetry`.

- Traces are exported via OTLP/gRPC directly to the **groundcover sensor** service in-cluster (no separate collector required by this repo).
- The Bedrock client attaches useful span attributes (model id, token usage when available, prompt/response hashes) and also records **chat messages as span events**.

## Load testing (k6)

Two k6 workloads exist under `k6/` and are also embedded into `k8s/k6.yaml`:

- **Steady load**: constant arrival rate of ~30 requests/min (bounded between 10 and 60) for 15 minutes.
  - For each title: `GET /books/title`.
  - If missing: `POST /books` to trigger Bedrock existence + summary flow.
- **Hourly delete**: a CronJob runs hourly and attempts 60 deletes (within the requested 50–100 window).
  - It looks up a random title to get the ISBN, then calls `DELETE /books/{isbn}`.

The `k6/titles.json` list contains a mix of real classics plus intentionally invalid/mismatched titles to ensure the "does not exist" path is exercised.

## Containerization

- Image: built from `Dockerfile` (Python slim base) and runs via `uvicorn`.
- Local build on Apple Silicon targets `linux/amd64` (see `Makefile`).

## Kubernetes deployment (manifests)

Namespace: `books-ai`

Workloads:

- `k8s/postgres.yaml`: Postgres 16 + init SQL (creates schema/table/indexes).
- `k8s/api.yaml`: books API Deployment + Service.
- `k8s/k6.yaml`: k6 Deployment for steady load + hourly CronJob delete.

Secrets:

- Real secrets **must** be provided via Kubernetes Secret objects.
- This repo provides an example secret manifest (`k8s/secrets.example.yaml`) with placeholder values only.
