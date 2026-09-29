# Agrobank AI Support

An AI-powered customer support chatbot for Agrobank. The system continuously synchronizes public Agrobank website content, cleans and chunks the content, creates multilingual embeddings, stores them in Qdrant, and uses Retrieval-Augmented Generation (RAG) to answer customer questions.

The project includes a FastAPI backend, a background synchronization worker, PostgreSQL for resource metadata/raw content, Qdrant for vector search, and a lightweight web chat interface.

## Overview

The system is designed to answer questions about information published on Agrobank's public website, such as:

- bank cards and card services
- tariffs and fees
- banking products
- transfers and services
- requirements and public information

It is a retrieval-based system: the language model is given retrieved Agrobank website content and is instructed to answer only from that context.

## Architecture

```text
                    Agrobank Public Website
                              │
                              ▼
                    ┌─────────────────────┐
                    │  Menu / Page APIs   │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Sync worker         │
                    │ discover → normalize│
                    │ → chunk → embed     │
                    └───────┬─────┬───────┘
                            │     │
                   raw data │     │ embeddings
                            │     │
                            ▼     ▼
                     PostgreSQL  Qdrant
                     resources   chunk vectors
                     chat history   │
                            │       │
                            └───┬───┘
                                ▼
                    Frontend → FastAPI API
                                │
                     router: language + intent
                         ┌──────┴──────┐
                         ▼             ▼
                    live rates API   hybrid search
                         │          + reranking
                         └──────┬──────┘
                                ▼
                        Groq final answer
                                ▼
                     cited answer + history
```

## RAG Pipeline

A typical request follows this flow:

1. The user sends a question.
2. A Groq router classifies intent and language, and decides whether retrieval or the live exchange-rates tool is needed.
3. For retrieval, the question is converted into an E5 embedding.
4. Qdrant retrieves semantic (dense) and exact-term BM25 (sparse) candidates in that language.
5. Qdrant combines the two ranked lists with reciprocal rank fusion (RRF).
6. A local cross-encoder reranks the candidate chunks against the search query.
7. The best `CONTEXT_TOP_K` chunks are assembled into the LLM context. Exchange-rate questions instead fetch fresh rates from Agrobank's API; mixed questions can use both paths.
8. Groq generates structured answer parts and source references. The API returns the cited answer, sources, and session ID and saves the conversation in PostgreSQL.

The LLM is explicitly instructed to avoid inventing fees, rates, limits, dates, eligibility rules, or other banking details that are not present in the retrieved context.

The web chat uses `POST /chat/stream` for newline-delimited progress events:
analyzing the question, fetching live exchange rates or retrieving documents,
and generating the final answer. The last event contains the same response as
`POST /chat`, which remains available for non-streaming clients. The Nginx
proxy disables buffering for the streaming route so these stages appear as
they start.

Current currency exchange-rate questions take a live-tool path instead of
relying on previously indexed Qdrant chunks. `app/tools/exchange_rates.py`
fetches Agrobank's public page API for every such question and supplies the
exchange-office, ATM, and international-transfer tables separately, including
each quoted rate's update time. A zero or missing quote is treated as not
published. The answer links to Agrobank's readable exchange-rates page; if the
live API is unavailable, the chatbot reports an error rather than using stale
rates. Mixed questions can also retrieve non-rate information from Qdrant.

## Data Ingestion

The synchronization worker runs continuously.

By default:

```text
SYNC_INTERVAL_SECONDS=900
```

That means the worker performs a synchronization every 15 minutes.

### Discovery

The worker starts from Agrobank's menu API for the configured languages:

```text
uz, ru, en
```

It then recursively discovers additional internal page routes found in the page API JSON.

External domains and common document/media paths are excluded from page discovery.

### Fetching

Pages are requested through Agrobank's public API:

```text
?action=pages&code=<page-code>
```

The raw API response is stored in PostgreSQL.

### Normalization

The ingestion layer extracts useful textual content from the API JSON and removes known noise fields such as:

- image metadata
- SEO/OpenGraph metadata
- tags and properties
- screenshot/image data
- viewer counters
- unnecessary URL/path fields

HTML inside text values is decoded and stripped before indexing.

### Change Detection

Each normalized page is hashed with SHA-256.

If the content hash has not changed, the page is not re-embedded.

For new or changed pages:

```text
page
  → normalized text
  → chunks
  → embeddings
  → Qdrant
```

Old vectors for the same resource are removed before the new vectors are inserted.

## Chunking

The current chunking configuration is:

```text
CHUNK_SIZE=1200
CHUNK_OVERLAP=150
```

The splitter first tries to keep paragraphs together. Long paragraphs are split into fixed-size pieces, and neighboring chunks receive overlap to preserve local context across chunk boundaries.

## Embeddings

The configured embedding model and Qdrant dimension must match. The example
Docker setup mounts a local E5-base model directory and uses:

```text
EMBEDDING_MODEL=/models/multilingual-e5-base
EMBEDDING_DIM=768
```

The code defaults, when these settings are omitted, are E5-small with 384
dimensions. Do not switch between the 384- and 768-dimensional models against
the same Qdrant collection without rebuilding its vectors.


Documents are embedded using the E5 document format:

```text
passage: <text>
```

Queries are embedded using:

```text
query: <question>
```

Embeddings are normalized and stored in Qdrant using cosine distance.

## Retrieval

Current retrieval defaults:

```text
RETRIEVAL_CANDIDATE_K=20
CONTEXT_TOP_K=6
RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
RERANKER_BATCH_SIZE=8
```

The router supplies a search query and language. Both Qdrant prefetches use that language filter. BM25 uses the same tokenizer at ingest and query time, with English stemming disabled so Uzbek and Russian terms are not stemmed as English. Qdrant's RRF score and the cross-encoder's score have different scales from cosine similarity, so the old `MIN_RETRIEVAL_SCORE` setting is no longer applied. `TOP_K` is retained as a legacy setting but does not set the final context size; use `CONTEXT_TOP_K` instead.

The existing dense Qdrant collection is preserved. On startup, the new sparse vector name is added to it; at the start of each worker sync, missing BM25 vectors are backfilled from existing chunk payloads without recalculating dense embeddings. During backfill, dense retrieval still works. Qdrant must support adding sparse vector names to an existing collection (Qdrant 1.18+).

The reranker and BM25 tokenizer assets download on first use unless already cached. The Docker Compose files persist those downloads in the `model_cache` volume. The default multilingual MiniLM reranker is substantially smaller than BGE v2-m3, but its Uzbek ranking quality needs to be checked against the Qdrant-only baseline. The cross-encoder runs on CUDA when available, otherwise CPU; benchmark latency on your hardware before production use. To change its model, set `RERANKER_MODEL` to a compatible model ID or local model path.

## LLM

The project currently uses Groq.

Default model:

```text
openai/gpt-oss-20b
```

The router and answer stages can use separate credentials and models:

```text
GROQ_ROUTER_API_KEY
GROQ_ROUTER_MODEL
GROQ_FINAL_API_KEY
GROQ_FINAL_MODEL
```

Both model settings default to `openai/gpt-oss-20b`. The router selects the
language and whether to use retrieval, live exchange rates, or a direct
response. The final stage produces structured headings, paragraphs, bullets,
and steps with source IDs; the frontend renders at most one linked source icon
beside each answer part.

If Groq rejects a structured response with `json_validate_failed`, the app
retries once in JSON Object Mode and still validates the result locally,
including citations. A second failure returns a retryable error instead of
saving an incomplete answer.

The system prompt requires the model to:

- answer only from the retrieved context
- avoid inventing banking information
- respond in the user's language
- prefer newer information when retrieved context contains conflicting timestamps
- keep answers concise and direct

## Technology Stack

| Component | Technology |
|---|---|
| Backend API | FastAPI |
| ASGI server | Uvicorn |
| Background worker | Python |
| Database | PostgreSQL 17 |
| ORM | SQLAlchemy |
| Vector database | Qdrant |
| Embeddings | Sentence Transformers |
| Embedding model | Multilingual E5 (local base model in the example Docker setup) |
| LLM provider | Groq |
| Frontend | HTML / CSS / JavaScript |
| Web server | Nginx |
| Containerization | Docker / Docker Compose |
| Python | 3.12 |

## Project Structure

```text
bank-support-ai/
├── app/
│   ├── api/
│   │   ├── routes.py
│   │   ├── debug_router.py
│   │   └── schemas/
│   ├── core/
│   │   └── config.py
│   ├── ingestion/
│   │   ├── bank_client.py
│   │   ├── discovery.py
│   │   ├── normalizer.py
│   │   └── sync_service.py
│   ├── encoder/
│   │   ├── embeddings.py
│   │   ├── reranker.py
│   │   └── sparse_embeddings.py
│   ├── llm/
│   │   └── llm.py
│   ├── tools/
│   │   └── exchange_rates.py
│   ├── vector_db/
│   │   └── vector_store.py
│   ├── service/
│   │   ├── chat_history.py
│   │   ├── context.py
│   │   └── llm_system_promts.py
│   ├── db.py
│   ├── main.py
│   └── worker.py
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── agrobank-chatbot.png
│   ├── styles.css
│   ├── nginx.conf
│   └── Dockerfile
├── bruno-docs/
├── docs/
│   └── postgres-schema.svg
├── Dockerfile.dev
├── Dockerfile.prod
├── docker-compose.yml
├── docker-compose.gpu.yml
├── requirements.txt
└── README.md
```

## Requirements

For the Docker-based setup you need:

- Docker
- Docker Compose

No local Python installation is required to run the full stack through Docker Compose.

## Configuration

Copy `.env.example` to `.env` in the project root and set the keys and model
paths for your deployment. `.env` is ignored by Git.

Example:

```env
APP_ENV=dev
API_PORT=8000
LOG_LEVEL=INFO

BANK_BASE_URL=https://agrobank.uz
BANK_MENU_URL=https://agrobank.uz/api/v1/menu.json
BANK_API_URL=https://agrobank.uz/api/v1/
BANK_LANGUAGES=uz,ru,en
SYNC_INTERVAL_SECONDS=900

DATABASE_URL=postgresql+psycopg://rag:rag@postgres:5432/rag

QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=agrobank_pages

EMBEDDING_MODEL=/models/multilingual-e5-base
EMBEDDING_DIM=768
EMBEDDING_DEVICE=cpu
CHUNK_SIZE=1200
CHUNK_OVERLAP=150
RETRIEVAL_CANDIDATE_K=20
CONTEXT_TOP_K=6
RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
RERANKER_BATCH_SIZE=8

GROQ_ROUTER_API_KEY=your_groq_api_key
GROQ_ROUTER_MODEL=openai/gpt-oss-20b
GROQ_FINAL_API_KEY=your_groq_api_key
GROQ_FINAL_MODEL=openai/gpt-oss-20b
```

The mounted `/models/multilingual-e5-base` path requires a matching
`./models/multilingual-e5-base` directory on the host. Use `EMBEDDING_DEVICE=cpu`
for the default Compose file. The embedding dimension must match both the model
and the existing Qdrant collection. Set both Groq keys; `GROQ_API_KEY` and
`GROQ_MODEL` are not read by the current application.

Do not commit `.env` or any API keys to Git.

## Run with Docker Compose

The default `docker-compose.yml` does not request a GPU. Set `APP_ENV=dev` or
`APP_ENV=prod` to select `Dockerfile.dev` or `Dockerfile.prod`, respectively.
Build the images:

```bash
docker compose build
```

Start the application:

```bash
docker compose up -d
```

On a host where Docker can access an NVIDIA GPU, use
`docker compose -f docker-compose.gpu.yml up -d --build` instead. That file
requests a GPU for both API and worker. It cannot start those services on a
host without GPU passthrough. The production Dockerfile installs dependencies
without the development build cache; its first build can be large and slow.

Check service status:

```bash
docker compose ps
```

View API logs:

```bash
docker compose logs -f api
```

Application logs use UTC timestamps, a request ID, and a configurable `LOG_LEVEL`
(`INFO` by default; use `DEBUG` for per-page worker details). For a retrieval
request, look for `vector_search.completed`, `reranker.completed`, and
`retrieval.completed`. The last line reports both chunk counts and distinct
document counts before and after reranking, plus stage timings. The API also
returns `X-Request-ID` so a response can be matched to its logs. Questions,
answers, retrieved text, and API keys are not included in application logs.
Compose also disables Uvicorn's access log so debug GET query strings are not
printed separately.

View synchronization logs:

```bash
docker compose logs -f worker
```

The worker starts a synchronization when it starts, then repeats it according to `SYNC_INTERVAL_SECONDS`.

To force a new synchronization by restarting the worker:

```bash
docker compose restart worker
```

## Services and Ports

The default Docker Compose configuration starts:

| Service | Purpose | Port |
|---|---|---|
| `frontend` | Web chat UI | `8080` |
| `api` | FastAPI backend | `8000` |
| `worker` | Periodic Agrobank synchronization | none |
| `postgres` | Resources and chat messages | `5432` |
| `qdrant` | Vector storage and hybrid search | internal `6333`; random host port in the default Compose file |

Open the chatbot in your browser:

```text
http://localhost:8080
```

Open the FastAPI service directly:

```text
http://localhost:8000
```

FastAPI's automatic documentation is available at:

```text
http://localhost:8000/docs
```

Qdrant is available to other Compose services at `http://qdrant:6333`.
The default Compose file publishes it on a random host port; find that port
with `docker compose port qdrant 6333`. The GPU Compose file explicitly maps
host port 6333, so on that variant it is exposed on:

```text
http://localhost:6333
```

## API

### Health Check

```http
GET /health
```

Example:

```bash
curl http://localhost:8000/health
```

Response:

```json
{
  "status": "ok"
}
```

### Inspect Relevant Resources

```http
GET /relevants?question=<text>&language=<uz|ru|en>
```

Example:

```bash
curl "http://localhost:8000/relevants?question=Humo%20card&language=en"
```

This debug endpoint returns retrieved chunks and source metadata. It runs the
embedding, hybrid retrieval, and reranking stages. `/debug/analyze?question=...`
exposes the router's analysis for debugging.

### Chat

```http
POST /chat
Content-Type: application/json
```

Example:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Humo kartani chiqarish narxi qancha?",
    "session_id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

`session_id` is optional; the API creates one if omitted. The router detects
the question language. Reuse the returned session ID to continue a chat.

Example response:

```json
{
  "answer": "....",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "sources": [
    {
      "title": "....",
      "page_url": "....",
      "score": 0.87
    }
  ],
  "parts": [
    {"kind": "bullet", "text": "...", "source_ids": [1]}
  ]
}
```

`POST /chat/stream` accepts the same JSON and streams newline-delimited JSON
events: `phase` (`analyzing`, `exchange_rates`, `retrieving`, `generating`),
then `result` with the same response shape, or `error`. The web interface uses
this route through the Nginx `/api/` reverse proxy.

Chat history endpoints are `GET /chat/sessions` (latest eight),
`POST /chat/session` (load messages), and `DELETE /chat/session` (delete all
messages for a session). The latter two accept a JSON UUID `session_id`.

## Frontend

The frontend is a lightweight static chatbot interface served by Nginx.

It provides:

- chatbot-style conversation UI
- Agrobank branding
- automatic Uzbek, Russian, and English language routing
- new-chat action and per-chat deletion
- a collapsible history drawer with the eight most recently active chats in
  the database; selecting one reloads its messages and continues the session
- progress labels for routing, retrieval/live rates, and final generation
- character counting and source-link icons beside cited answer parts
- API health status
- responsive layout

The frontend container proxies `/api/*` requests to the FastAPI `api:8000` service.
Opening the page starts a new chat; selecting a sidebar item reopens that saved
session. The history API lists the latest chats across the database, so anyone
with access to this unauthenticated app can view and delete those conversations.
Previously saved answers are displayed from their plain-text message history;
source-link metadata from older answers was not stored in the database.

## Database Design

PostgreSQL has two tables: one `resources` row per discovered Agrobank page
and one `chat_messages` row per saved user or assistant message.

![PostgreSQL schema and logical relationships](docs/postgres-schema.svg)

Important fields include:

```text
id
code
language
page_url
api_url
title
content_text
raw_json
content_hash
discovered_from
source_updated_at
is_active
last_seen_at
last_processed_at
```

`content_text` contains normalized page text; `raw_json` preserves the original
API response. `resources.code` is unique. `chat_messages.session_id` groups
messages into conversations; there is no separate sessions table. The tables
have **no PostgreSQL foreign key between them**. Qdrant chunk payloads contain
`resource_id` referencing `resources.id` logically, but Qdrant is a separate
database and PostgreSQL does not enforce that relationship. Both PostgreSQL
and Qdrant data persist in named Docker volumes across ordinary rebuilds.

## Vector Store

Qdrant stores one vector point per text chunk.

Each vector payload contains:

```text
resource_id
chunk_index
language
title
page_url
text
```

Dense vectors use cosine similarity in the `agrobank_pages` collection; sparse
BM25 vectors use the `bm25` vector name. Dense and sparse search results are
fused with RRF before cross-encoder reranking.

When a page changes, its old vectors are deleted and the newly generated chunk vectors are inserted.

## Updating the Knowledge Base

The normal workflow is automatic:

```text
Agrobank API
    ↓
worker discovers pages
    ↓
worker checks content hash
    ↓
changed pages are normalized
    ↓
text is chunked
    ↓
chunks are embedded
    ↓
Qdrant is updated
    ↓
chat requests can retrieve the new information
```

You normally do not need to manually rebuild the database for ordinary Agrobank website content changes.

## Development

To run the backend outside Docker, the environment still needs access to PostgreSQL and Qdrant.

Install Python dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Run the synchronization worker separately:

```bash
python -m app.worker
```

For development, Docker Compose is the recommended way to start the complete application because it provides the API, worker, PostgreSQL, Qdrant, and frontend together.

## Useful Docker Commands

Stop the stack:

```bash
docker compose down
```

Destructive: stop the stack and **delete** persisted PostgreSQL, Qdrant, and
model-cache volumes (this permanently removes chat history and indexed data):

```bash
docker compose down -v
```

Rebuild after dependency or source changes:

```bash
docker compose build --no-cache
```

Follow all service logs:

```bash
docker compose logs -f
```

Restart only the API:

```bash
docker compose restart api
```

Restart only the worker:

```bash
docker compose restart worker
```

## Troubleshooting

### Chat returns a 503

Check the API logs:

```bash
docker compose logs -f api
```

Verify that `GROQ_ROUTER_API_KEY` and `GROQ_FINAL_API_KEY` are set in `.env`.

### No useful answers are returned

Check the worker:

```bash
docker compose logs -f worker
```

You should see synchronization progress, including discovered, fetched, changed, embedded, and chunk counts.

Also check:

```bash
curl "http://localhost:8000/relevants?question=Agrobank%20card&language=en"
```

If resources have not been ingested, the retrieval layer has no content to use.

### Qdrant connection problems

Check:

```bash
docker compose ps
docker compose logs qdrant
```

The backend should use:

```text
QDRANT_URL=http://qdrant:6333
```

inside Docker Compose.

### Database connection problems

The default Compose database is:

```text
database: rag
user: rag
password: rag
host: postgres
port: 5432
```

The corresponding SQLAlchemy URL is:

```text
postgresql+psycopg://rag:rag@postgres:5432/rag
```

## Current Scope and Limitations

The current system is designed for public Agrobank website information.

It does not perform customer-specific banking operations such as:

- checking private account balances
- making transfers
- opening accounts
- authenticating customers
- accessing private banking data

The ingestion pipeline currently focuses on Agrobank page API content. PDF, XLSX, and other document resources are not treated as first-class ingestion resources.

## Production Considerations

Before production deployment, review at least the following:

- replace default PostgreSQL credentials
- use strong secrets and a proper secret-management mechanism
- pin container image versions instead of relying on moving tags
- configure HTTPS/TLS
- add authentication and authorization where required
- add database backups
- add Qdrant backups/persistence procedures
- add monitoring and alerting
- add rate limiting
- evaluate retrieval quality with a representative test set
- validate generated answers for important financial information

## Data and Answer Quality

This project uses RAG instead of relying on the language model's internal knowledge.

Answer quality therefore depends on:

```text
source data quality
        +
normalization quality
        +
chunking quality
        +
embedding quality
        +
retrieval quality
        +
LLM generation
```

Improving the ingestion and retrieval pipeline is therefore as important as changing the language model.

## Project Status

Current implementation:

- continuous Agrobank page synchronization
- PostgreSQL resource storage
- normalized text extraction
- configurable chunking with overlap
- multilingual E5 embeddings
- Qdrant vector search
- dense/sparse hybrid search with reranking
- live exchange-rate retrieval for exchange offices, ATMs, and international transfers
- session-based PostgreSQL chat history and source-linked answers
- Groq LLM generation
- FastAPI REST API
- Docker Compose deployment
- web chatbot frontend
- Bruno API documentation

