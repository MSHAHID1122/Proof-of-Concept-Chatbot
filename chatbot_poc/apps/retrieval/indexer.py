"""
Simple indexer that reads JSON payloads produced by the ingest management command
and indexes them into a Haystack ElasticsearchDocumentStore using the haystack_pipeline helpers.

Provides:
- index_json_payload(json_path: str, delete_existing: bool=False) -> dict
- reindex_all_from_folder(folder_path: str) -> dict

The functions are defensive: they log progress and return summary dicts. They try to
continue indexing other files in a folder even if one file fails.
"""

import json
import os
import logging
import traceback
from typing import Dict, Any

from . import haystack_pipeline

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def index_json_payload(json_path: str, delete_existing: bool = False) -> Dict[str, Any]:
    """
    Index a single JSON payload file into the configured Haystack document store.

    Args:
        json_path: Path to the JSON file created by ingest_pdfs (an array of {"content":..., "meta":{...}}).
        delete_existing: If True, recreate the target index (development mode).

    Returns:
        Summary dict: {"indexed": <n>, "index": <index_name>} or includes "error" on failure.
    """
    logger.info("Indexing JSON payload: %s (delete_existing=%s)", json_path, delete_existing)
    if not os.path.exists(json_path):
        msg = f"JSON payload not found: {json_path}"
        logger.error(msg)
        return {"indexed": 0, "index": None, "error": msg}

    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            docs = json.load(fh)
        if not isinstance(docs, list):
            msg = f"Unexpected JSON structure in {json_path}: expected list of docs."
            logger.error(msg)
            return {"indexed": 0, "index": None, "error": msg}
    except Exception as e:
        logger.exception("Failed to read/parse JSON payload: %s", json_path)
        return {"indexed": 0, "index": None, "error": str(e)}

    # Create / connect document store
    try:
        document_store = haystack_pipeline.get_document_store(refresh_index=delete_existing)
        index_name = getattr(document_store, "index", None)
    except Exception as e:
        logger.exception("Failed to get document store.")
        return {"indexed": 0, "index": None, "error": str(e)}

    # Create retriever (needed for embedding updates)
    try:
        retriever = haystack_pipeline.get_retriever(document_store)
    except Exception as e:
        logger.exception("Failed to create retriever.")
        return {"indexed": 0, "index": index_name, "error": str(e)}

    # Write documents
    try:
        haystack_pipeline.write_documents(document_store, docs)
        indexed_count = len(docs)
        logger.info("Wrote %d documents to index %s", indexed_count, index_name)
    except Exception as e:
        logger.exception("Failed to write documents to document store.")
        return {"indexed": 0, "index": index_name, "error": str(e)}

    # Update embeddings
    try:
        haystack_pipeline.update_embeddings(document_store, retriever)
        logger.info("Embeddings update triggered for index %s", index_name)
    except Exception as e:
        # Embedding update failure is serious but we report it rather than raising, to allow partial success
        tb = traceback.format_exc()
        logger.exception("Failed to update embeddings for index %s: %s", index_name, e)
        return {"indexed": indexed_count, "index": index_name, "error": str(e), "traceback": tb}

    return {"indexed": indexed_count, "index": index_name}


def reindex_all_from_folder(folder_path: str, delete_existing: bool = False) -> Dict[str, Any]:
    """
    Iterate through all JSON files in folder_path and index them sequentially.

    Args:
        folder_path: Directory containing JSON payload files.
        delete_existing: If True, refresh the index before indexing each file (dev only).

    Returns:
        Summary dict with per-file results and aggregate counts:
        {
            "total_files": n,
            "succeeded": m,
            "failed": k,
            "details": { "file1.json": {...}, ... }
        }
    """
    logger.info("Reindexing all JSON payloads in folder: %s", folder_path)
    if not os.path.isdir(folder_path):
        msg = f"Folder not found: {folder_path}"
        logger.error(msg)
        return {"total_files": 0, "succeeded": 0, "failed": 0, "details": {}, "error": msg}

    results = {}
    succeeded = 0
    failed = 0
    files = sorted([f for f in os.listdir(folder_path) if f.lower().endswith(".json")])
    total = len(files)
    logger.info("Found %d JSON files to index.", total)

    for i, fname in enumerate(files, start=1):
        path = os.path.join(folder_path, fname)
        logger.info("(%d/%d) Indexing %s", i, total, path)
        try:
            res = index_json_payload(path, delete_existing=delete_existing)
            results[fname] = res
            if res.get("indexed", 0) > 0 and "error" not in res:
                succeeded += 1
            else:
                # treat as failed if error exists or zero indexed
                if res.get("indexed", 0) > 0:
                    succeeded += 1
                else:
                    failed += 1
        except Exception as e:
            logger.exception("Unhandled exception while indexing %s: %s", path, e)
            results[fname] = {"indexed": 0, "index": None, "error": str(e)}
            failed += 1

    summary = {"total_files": total, "succeeded": succeeded, "failed": failed, "details": results}
    logger.info("Reindexing completed. summary=%s", summary)
    return summary


# Short usage examples (illustrative)
# From a shell:
#   python -c "from apps.retrieval import indexer; print(indexer.index_json_payload('media/documents/index_payloads/42.json'))"
#
# From a bash script:
#   #!/bin/bash
#   PYTHONPATH=. python -c "from apps.retrieval import indexer; print(indexer.index_json_payload('media/documents/index_payloads/42.json'))"
#
# In Django management commands or other Python code:
#   from apps.retrieval import indexer
#   summary = indexer.index_json_payload('/path/to/media/documents/index_payloads/42.json')
#   print(summary)
