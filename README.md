# Agrobank RAG Backend

Backend-only prototype for synchronizing Agrobank's public content API into PostgreSQL + Qdrant and answering questions with RAG.

## Architecture

Agrobank menu API -> recursive API page discovery -> raw JSON in PostgreSQL -> normalization/chunking -> multilingual E5 embeddings -> Qdrant -> retrieval -> LLM.

The worker periodically re-fetches discovered pages. A SHA-256 hash of the canonical API JSON prevents re-embedding unchanged pages.

## Run

```bash
cp .env.example .env
# edit GEMINI_API_KEY (and GEMINI_MODEL if needed) when you want /chat to work

docker compose build
docker compose up -d
```

Trigger the first synchronization:

```bash
curl -X POST http://localhost:8000/sync
```

Inspect discovered resources:

```bash
curl http://localhost:8000/resources
```

Ask a question:

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"What business tariff plans does Agrobank offer?","language":"uz"}'
```

## Current scope

The first version follows internal page routes exposed by `menu.json` and additional internal page links found in page API JSON. It stores raw API responses and indexes page content in Qdrant.

Next ingestion additions should handle PDF/XLSX/document URLs as first-class resources and then add stronger parsing rules for each Agrobank block type.
