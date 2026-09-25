from app.rag.embeddings import get_embedding_service
from app.rag.vector_store import get_vector_store
from app.core.config import settings

def build_context(question: str, language: str | None):
    embedder = get_embedding_service()
    vector_store = get_vector_store()

    query_vector = embedder.embed_query(question) #embedding the query

    hits = vector_store.search(query_vector, settings.top_k, language) #searching from the vector db

    return [hit for hit in hits if hit["score"] >= settings.min_retrieval_score]
