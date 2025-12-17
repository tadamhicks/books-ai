## books-ai

`books-ai` is a small FastAPI + Postgres service that stores book records and uses **AWS Bedrock** to:

- Validate whether a requested book appears to exist (strict `yes` / `no`)
- Generate a short summary when creating a new record

It’s intentionally instrumented with **OpenLLMetry** (Traceloop) so you can analyze LLM usage and message-level details in **groundcover**.

OpenLLMetry repo: `https://github.com/traceloop/openllmetry`

### API endpoints

- **Health**: `GET /health`
- **Lookup by title**: `GET /books/title?title=...`
- **Lookup by author (last name)**: `GET /books/author?author_last_name=...`
- **Lookup by ISBN**: `GET /books/isbn/{isbn}`
- **Create**: `POST /books`
- **Delete**: `DELETE /books/{isbn}`

### Data model (Postgres)

Schema: `books`  
Table: `books.books`

Columns: `isbn` (13 chars, PK), `title`, `author_first_name`, `author_last_name`, `summary`, `created_at`

### Local development

1) Create venv + install deps:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Start Postgres (any method you prefer) and ensure the `books` schema exists (the k8s manifest runs `db/init.sql` automatically).

3) Configure env:

```bash
cp example.env .env
```

4) Run the API:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Container build (Apple Container)

The `Makefile` targets `linux/amd64` from an ARM Mac:

```bash
make build
make run
```

### Kubernetes deployment (manifests)

The repo includes:

- `k8s/namespace.yaml`
- `k8s/postgres.yaml` (Postgres 16 + init SQL)
- `k8s/api.yaml` (API Deployment + Service)
- `k8s/k6.yaml` (steady-load + hourly delete)
- `k8s/secrets.example.yaml` (placeholders only)

Apply in-cluster (example):

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secrets.example.yaml
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/api.yaml
kubectl apply -f k8s/k6.yaml
```

### Observability: OpenLLMetry + groundcover

This service exports OTLP traces directly to the groundcover sensor endpoint (see `OTEL_EXPORTER_OTLP_ENDPOINT`).

#### Capturing chat content as a span event

The Bedrock client records message payloads as span events (and also adds attributes like prompt hashes, token usage when available, and response previews). See `app/services/bedrock_client.py` for:

- `span.add_event("llm.message", {... "content": prompt[:16000] ...})`
- `span.add_event("llm.response", {... "content": text[:16000] ...})`

In groundcover, you can then search traces for those events/attributes to inspect prompt/response behavior under load (from the k6 workloads).

### Git safety (prevent committing secrets)

This repo includes:

- A strict `.gitignore` that excludes `.env`, `.aws/`, `k8s/secrets*.yaml`, and common key/cert files.
- Repo-local git hooks in `.githooks/` that block commits if they detect common secret patterns.

Install hooks:

```bash
make hooks
```


