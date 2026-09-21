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
                    │   Sync Worker       │
                    │                     │
                    │ discovery           │
                    │ fetching            │
                    │ normalization       │
                    │ chunking             │
                    │ change detection     │
                    └───────┬─────┬───────┘
                            │     │
                   raw data │     │ embeddings
                            │     │
                            ▼     ▼
                     PostgreSQL  Qdrant
                            │      │
                            │      │ vector search
                            │      ▼
                            │  Top-K chunks
                            │      │
                            └──────┼──────────────┐
                                   ▼              │
                              FastAPI API         │
                                   │              │
                                   ▼              │
                              Groq / LLM ◄────────┘
                                   │
                                   ▼
                             Chat response
                                   │
                                   ▼
                              Web frontend
```

## RAG Pipeline

A typical request follows this flow:

1. The user sends a question.
2. The question is converted into an embedding using `intfloat/multilingual-e5-small`.
3. Qdrant performs cosine-similarity search.
4. The system retrieves up to `TOP_K` relevant chunks.
5. Results below `MIN_RETRIEVAL_SCORE` are discarded.
6. The retrieved chunks are assembled into the LLM context.
7. Groq generates the final response.
8. The API returns the answer and retrieved source metadata.

The LLM is explicitly instructed to avoid inventing fees, rates, limits, dates, eligibility rules, or other banking details that are not present in the retrieved context.

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

The current embedding model is:

```text
intfloat/multilingual-e5-small
```

Configuration:

```text
EMBEDDING_DIM=384
```

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
TOP_K=6
MIN_RETRIEVAL_SCORE=0.30
```

Language filtering can also be applied during Qdrant search when a language is supplied to the `/chat` endpoint.

## LLM

The project currently uses Groq.

Default model:

```text
openai/gpt-oss-20b
```

The LLM configuration can be changed through:

```text
GROQ_MODEL
```

The response generation uses a low-temperature configuration and a bounded completion length.

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
| Embedding model | `intfloat/multilingual-e5-small` |
| LLM provider | Groq |
| Frontend | HTML / CSS / JavaScript |
| Web server | Nginx |
| Containerization | Docker / Docker Compose |
| Python | 3.12 |

## Project Structure

```text
bank-support-chat/
├── app/
│   ├── api/
│   │   ├── routes.py
│   │   └── schemas/
│   ├── core/
│   │   └── config.py
│   ├── ingestion/
│   │   ├── bank_client.py
│   │   ├── discovery.py
│   │   ├── normalizer.py
│   │   └── sync_service.py
│   ├── rag/
│   │   ├── embeddings.py
│   │   ├── vector_store.py
│   │   └── llm.py
│   ├── service/
│   │   └── context.py
│   ├── db.py
│   ├── main.py
│   └── worker.py
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   ├── nginx.conf
│   └── Dockerfile
├── bruno-docs/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Requirements

For the Docker-based setup you need:

- Docker
- Docker Compose

No local Python installation is required to run the full stack through Docker Compose.

## Configuration

Create a `.env` file in the project root.

Example:

```env
APP_ENV=dev
API_PORT=8000

BANK_BASE_URL=https://agrobank.uz
BANK_MENU_URL=https://agrobank.uz/api/v1/menu.json
BANK_API_URL=https://agrobank.uz/api/v1/
BANK_LANGUAGES=uz,ru,en
SYNC_INTERVAL_SECONDS=900

DATABASE_URL=postgresql+psycopg://rag:rag@postgres:5432/rag

QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=agrobank_pages

EMBEDDING_MODEL=intfloat/multilingual-e5-small
EMBEDDING_DIM=384
CHUNK_SIZE=1200
CHUNK_OVERLAP=150
TOP_K=6
MIN_RETRIEVAL_SCORE=0.30

GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-20b
```

`DATABASE_URL` and `GROQ_API_KEY` are the important values for the default Docker Compose setup.

Do not commit `.env` or any API keys to Git.

## Run with Docker Compose

Build the images:

```bash
docker compose build
```

Start the application:

```bash
docker compose up -d
```

Check service status:

```bash
docker compose ps
```

View API logs:

```bash
docker compose logs -f api
```

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
| `postgres` | Resource metadata and raw content | internal |
| `qdrant` | Vector storage and similarity search | `6333` |

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

Qdrant is exposed on:

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

### List Resources

```http
GET /resources
```

Example:

```bash
curl "http://localhost:8000/resources?limit=20"
```

The endpoint returns discovered Agrobank resources and processing metadata.

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
    "language": "uz"
  }'
```

The `language` field is optional.

Example response:

```json
{
  "answer": "....",
  "sources": [
    {
      "title": "....",
      "page_url": "....",
      "score": 0.87
    }
  ]
}
```

The web interface can use the API through the Nginx `/api/` reverse proxy.

## Frontend

The frontend is a lightweight static chatbot interface served by Nginx.

It provides:

- chatbot-style conversation UI
- Agrobank branding
- Uzbek, Russian, and English response-language selection
- example prompts
- conversation clearing
- character counting
- API health status
- responsive layout

The frontend container proxies `/api/*` requests to the FastAPI `api:8000` service.

## Database Design

PostgreSQL stores one resource record for each discovered Agrobank page.

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

`content_text` contains the normalized page text used during processing, while `raw_json` preserves the original API response.

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

Vectors are stored in the `agrobank_pages` collection using cosine similarity.

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

Stop the stack and remove persisted database/vector volumes:

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

Verify that `GROQ_API_KEY` is present in `.env`.

### No useful answers are returned

Check the worker:

```bash
docker compose logs -f worker
```

You should see synchronization progress, including discovered, fetched, changed, embedded, and chunk counts.

Also check:

```bash
curl http://localhost:8000/resources
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
- similarity-score filtering
- Groq LLM generation
- FastAPI REST API
- Docker Compose deployment
- web chatbot frontend
- Bruno API documentation

