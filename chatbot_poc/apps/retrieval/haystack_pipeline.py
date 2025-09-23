"""
Haystack pipeline helpers for the POC (FAISS-based).

Provides:
- get_document_store(refresh_index: bool = False)
- get_retriever(document_store)
- write_documents(document_store, docs: List[dict])
- update_embeddings(document_store, retriever)
- retrieve_top_k(query: str, retriever, top_k: int = 5)

Notes:
- Expects `farm-haystack` (pip: farm-haystack) installed.
- Uses FAISSDocumentStore instead of Elasticsearch (no external service required).
"""

from typing import List, Dict, Any
import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Defaults
_DEFAULT_EMBEDDING_DIM = 384
_DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_INDEX_PATH = getattr(settings, "FAISS_INDEX_PATH", "faiss_index")
_DEFAULT_SQL_URL = getattr(settings, "FAISS_SQL_URL", "sqlite:///faiss_doc_store.db")


def get_document_store(refresh_index: bool = False, embedding_dim: int = _DEFAULT_EMBEDDING_DIM):
    """
    Create and return a FAISSDocumentStore.

    Args:
        refresh_index: If True, delete any existing FAISS index/db (development use only).
        embedding_dim: Dimensionality of the embedding vectors stored.

    Returns:
        An instance of FAISSDocumentStore.
    """
    try:
        from haystack.document_stores import FAISSDocumentStore
    except Exception as e:
        logger.exception("Haystack (farm-haystack) with FAISS is required but not installed.")
        raise

    faiss_index_path = _DEFAULT_INDEX_PATH
    sql_url = _DEFAULT_SQL_URL

    if refresh_index:
        try:
            if os.path.exists(faiss_index_path):
                os.remove(faiss_index_path)
                logger.info("Deleted existing FAISS index file: %s", faiss_index_path)
        except Exception as e:
            logger.warning("Could not delete FAISS index: %s", e)

    try:
        document_store = FAISSDocumentStore(
            sql_url=sql_url,
            faiss_index_factory_str="Flat",
            embedding_dim=embedding_dim
        )
        logger.info("Connected to FAISSDocumentStore at %s", sql_url)
    except Exception as conn_err:
        logger.exception("Failed to instantiate FAISSDocumentStore: %s", conn_err)
        raise

    return document_store


def get_retriever(document_store, embedding_model: str = None, use_gpu: bool = False):
    """Create an EmbeddingRetriever for the FAISS store."""
    try:
        from haystack.nodes import EmbeddingRetriever
    except Exception as e:
        logger.exception("Haystack nodes are required but not installed.")
        raise

    embedding_model = (
        embedding_model
        or getattr(settings, "EMBEDDING_MODEL", None)
        or _DEFAULT_EMBEDDING_MODEL
    )

    try:
        retriever = EmbeddingRetriever(
            document_store=document_store,
            embedding_model=embedding_model,
            model_format="sentence_transformers",
            use_gpu=use_gpu,
        )
        logger.info("Created EmbeddingRetriever using model=%s", embedding_model)
    except Exception as e:
        logger.exception("Failed to create EmbeddingRetriever: %s", e)
        raise

    return retriever


def write_documents(document_store, docs: List[Dict[str, Any]]):
    """Write documents to FAISS store."""
    try:
        document_store.write_documents(docs)
        logger.info("Wrote %d documents to FAISS index", len(docs))
    except Exception as e:
        logger.exception("Failed to write documents: %s", e)
        raise


def update_embeddings(document_store, retriever):
    """Update embeddings in FAISS store using the retriever."""
    try:
        document_store.update_embeddings(retriever)
        logger.info("Updated embeddings in FAISS index.")
    except Exception as e:
        logger.exception("Failed to update embeddings: %s", e)
        raise


def retrieve_top_k(query: str, retriever, top_k: int = 5) -> List[Dict[str, Any]]:
    """Retrieve top-k documents for a query using FAISS retriever."""
    results: List[Dict[str, Any]] = []
    try:
        docs = retriever.retrieve(query=query, top_k=top_k)
        for d in docs[:top_k]:
            content = getattr(d, "content", None) or d.get("content")
            meta = getattr(d, "meta", None) or d.get("meta", {})
            score = getattr(d, "score", None) or d.get("score", None)
            results.append({"content": content, "meta": meta, "score": score})
    except Exception as e:
        logger.exception("Retrieval failed for query=%s: %s", query, e)
        raise

    return results