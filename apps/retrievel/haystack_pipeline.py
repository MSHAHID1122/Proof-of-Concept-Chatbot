"""
Haystack pipeline helpers for the POC.

Provides:
- get_document_store(refresh_index: bool = False)
- get_retriever(document_store)
- write_documents(document_store, docs: List[dict])
- update_embeddings(document_store, retriever)
- retrieve_top_k(query: str, retriever, top_k: int = 5) -> List[dict]

Notes:
- Expects `farm-haystack` (pip: farm-haystack) installed.
- This module keeps things simple and defensive: it's intended as glue for the POC.
"""

from typing import List, Dict, Any
import logging

from django.conf import settings

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Default embedding dim for sentence-transformers/all-MiniLM-L6-v2
_DEFAULT_EMBEDDING_DIM = 384
_DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_INDEX = getattr(settings, "HAYSTACK_INDEX", "haystack_document_index")


def get_document_store(refresh_index: bool = False, embedding_dim: int = _DEFAULT_EMBEDDING_DIM):
    """
    Create and return an ElasticsearchDocumentStore configured from Django settings.

    Args:
        refresh_index: If True, attempt to delete the target index (development use only).
        embedding_dim: Dimensionality of the embedding vectors stored.

    Returns:
        An instance of ElasticsearchDocumentStore.

    Raises:
        ImportError if farm-haystack is not installed.
        Exception for underlying Elasticsearch errors.
    """
    try:
        from haystack.document_stores import ElasticsearchDocumentStore
    except Exception as e:
        logger.exception("Haystack (farm-haystack) is required but not installed.")
        raise

    host = getattr(settings, "ELASTICSEARCH_HOST", "localhost")
    port = int(getattr(settings, "ELASTICSEARCH_PORT", 9200))
    index = getattr(settings, "HAYSTACK_INDEX", _DEFAULT_INDEX)

    try:
        # instantiate document store
        document_store = ElasticsearchDocumentStore(
            host=host,
            port=port,
            index=index,
            embedding_dim=embedding_dim,
            scheme="http",
        )
        logger.info("Connected to ElasticsearchDocumentStore at %s:%s index=%s", host, port, index)
    except Exception as conn_err:
        logger.exception("Failed to instantiate ElasticsearchDocumentStore: %s", conn_err)
        raise

    if refresh_index:
        try:
            # Try deleting the index via haystack helper if available
            try:
                # Some versions have delete_index helper
                document_store.delete_index(index=document_store.index)
                logger.info("Deleted existing index via document_store.delete_index(%s).", document_store.index)
            except Exception:
                # Fallback to raw client call
                client = getattr(document_store, "client", None)
                if client is not None:
                    client.indices.delete(index=document_store.index, ignore=[400, 404])
                    logger.info("Deleted existing index via client.indices.delete(%s).", document_store.index)
                else:
                    logger.warning("Could not delete index: no document_store.client available.")
            # After deletion, re-create index by writing an empty mapping (haystack will create when writing documents)
        except Exception as del_err:
            logger.exception("Failed to refresh index %s: %s", document_store.index, del_err)
            raise

    return document_store


def get_retriever(document_store, embedding_model: str = None, use_gpu: bool = False):
    """
    Create an EmbeddingRetriever for the given document store.

    Args:
        document_store: Haystack DocumentStore instance.
        embedding_model: Model name/path for sentence-transformers. Falls back to settings or default.
        use_gpu: Whether to attempt to use GPU (if available).

    Returns:
        An EmbeddingRetriever instance.

    Raises:
        ImportError if haystack nodes are unavailable.
    """
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
        logger.exception("Failed to create EmbeddingRetriever with model=%s: %s", embedding_model, e)
        raise

    return retriever


def write_documents(document_store, docs: List[Dict[str, Any]]):
    """
    Write a list of documents into the Haystack document store.

    Args:
        document_store: Haystack DocumentStore instance.
        docs: List of dicts in the form {"content": "...", "meta": {...}}.

    Returns:
        None

    Notes:
        This will append documents to the configured index.
    """
    try:
        # haystack accepts documents as list of dicts
        document_store.write_documents(docs)
        logger.info("Wrote %d documents to index %s", len(docs), getattr(document_store, "index", "<unknown>"))
    except Exception as e:
        logger.exception("Failed to write documents to document store: %s", e)
        raise


def update_embeddings(document_store, retriever):
    """
    Compute/update embeddings for documents in the store using the retriever.

    Args:
        document_store: Haystack DocumentStore instance.
        retriever: EmbeddingRetriever instance.

    Returns:
        None
    """
    try:
        # document_store.update_embeddings expects a retriever
        document_store.update_embeddings(retriever)
        logger.info("Triggered document_store.update_embeddings().")
    except Exception as e:
        logger.exception("Failed to update embeddings: %s", e)
        raise


def retrieve_top_k(query: str, retriever, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Retrieve top-k documents for a query using the given retriever.

    Args:
        query: The user query string.
        retriever: EmbeddingRetriever (or compatible retriever) instance.
        top_k: Number of results to return.

    Returns:
        List of dicts: [{"content": str, "meta": dict, "score": float}, ...]
    """
    results: List[Dict[str, Any]] = []
    try:
        # Many haystack Retriever implementations provide a .retrieve(...) method.
        if hasattr(retriever, "retrieve"):
            docs = retriever.retrieve(query=query, top_k=top_k)
        else:
            # fallback: compute query embedding and query the document_store directly if available
            logger.debug("Retriever has no 'retrieve' method; attempting fallback to embed_queries + document_store.query_by_embedding")
            if not hasattr(retriever, "embed_queries"):
                raise RuntimeError("Retriever has no retrieve or embed_queries methods.")
            query_emb = retriever.embed_queries(texts=[query])[0]
            ds = getattr(retriever, "document_store", None)
            if ds is None:
                raise RuntimeError("Cannot access document_store from retriever for fallback retrieval.")
            # Attempt to use document_store.query_by_embedding if available
            if hasattr(ds, "query_by_embedding"):
                docs = ds.query_by_embedding(query_emb, top_k=top_k)
            elif hasattr(ds, "query"):
                # last-resort: plain text query (not semantic)
                docs = ds.query(query=query, top_k=top_k)
            else:
                raise RuntimeError("Document store has no compatible query method for fallback retrieval.")
        # docs is expected to be iterable of haystack.Document objects or dict-like
        for d in docs[:top_k]:
            try:
                content = getattr(d, "content", None) or d.get("content")
                meta = getattr(d, "meta", None) or d.get("meta", {})
                score = getattr(d, "score", None) or d.get("score", None)
                results.append({"content": content, "meta": meta, "score": score})
            except Exception:
                # tolerate unexpected document shape
                logger.exception("Failed to parse retrieved document: %s", d)
    except Exception as e:
        logger.exception("Retrieval failed for query=%s: %s", query, e)
        raise

    return results
