import os
import logging
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .serializers import UploadSerializer

from chatbot_poc.apps.core.models import Document
from chatbot_poc.apps.retrieval import haystack_pipeline
from chatbot_poc.apps.retrieval import indexer as retrieval_indexer

logger = logging.getLogger(__name__)


class UploadPDFView(APIView):
    """
    POST /api/upload/
    Accepts a 'file' multipart upload (PDF). Saves Document and triggers ingestion
    (synchronous) via the ingest_pdfs management command for simplicity.
    """
    def post(self, request, *args, **kwargs):
        serializer = UploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            doc = serializer.save()
        except Exception as e:
            logger.exception("Failed to save uploaded document")
            return Response({"error": "Failed to save document."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Trigger ingestion synchronously via management command call
        try:
            # call_command accepts named args matching dest: use doc_id
            call_command("ingest_pdfs", doc_id=doc.id)
        except Exception as e:
            # Log but still return doc metadata (ingestion may have failed)
            logger.exception("Ingestion command failed for document %s", doc.id)
            return Response(
                {"id": doc.id, "status": doc.status, "error": "Ingestion failed. See server logs."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"id": doc.id, "status": doc.status}, status=status.HTTP_201_CREATED)


class TriggerIndexView(APIView):
    """
    POST /api/index/
    Body: { "doc_id": <int> }
    Calls apps.retrieval.indexer.index_json_payload for the doc's JSON payload and returns summary.
    """
    def post(self, request, *args, **kwargs):
        doc_id = request.data.get("doc_id")
        if not doc_id:
            return Response({"error": "doc_id required"}, status=status.HTTP_400_BAD_REQUEST)

        doc = get_object_or_404(Document, pk=doc_id)

        payload_path = os.path.join(settings.MEDIA_ROOT, "documents", "index_payloads", f"{doc.id}.json")
        if not os.path.exists(payload_path):
            return Response({"error": "Payload JSON not found. Ensure ingestion ran."}, status=status.HTTP_404_NOT_FOUND)

        try:
            result = retrieval_indexer.index_json_payload(payload_path)
        except Exception as e:
            logger.exception("Indexing failed for doc %s", doc.id)
            return Response({"error": "Indexing failed", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"doc_id": doc.id, "index_result": result}, status=status.HTTP_200_OK)


class QueryView(APIView):
    """
    POST /api/query/
    Body: { "query": "text", "top_k": 5 (optional) }

    Uses haystack_pipeline to retrieve top-k chunks, then attempts to call an LLM helper
    at apps.retrieval.llm_client.generate_answer(query, retrieved_chunks).
    If llm_client is missing/not configured, returns raw chunks.
    """
    def post(self, request, *args, **kwargs):
        query = request.data.get("query")
        if not query:
            return Response({"error": "query is required"}, status=status.HTTP_400_BAD_REQUEST)

        top_k = int(request.data.get("top_k", 5))

        try:
            # connect to document store and retriever
            document_store = haystack_pipeline.get_document_store()
            retriever = haystack_pipeline.get_retriever(document_store)
            chunks = haystack_pipeline.retrieve_top_k(query=query, retriever=retriever, top_k=top_k)
        except Exception as e:
            logger.exception("Retrieval error for query: %s", query)
            return Response({"error": "Retrieval failed", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Attempt to use LLM helper to generate final answer
        try:
            from apps.retrieval import llm_client  # llm_client implemented in a later prompt
            if hasattr(llm_client, "generate_answer"):
                answer = llm_client.generate_answer(query=query, retrieved_chunks=chunks)
                return Response({"answer": answer, "source_chunks": chunks}, status=status.HTTP_200_OK)
            else:
                # llm_client present but no generate_answer function
                return Response({"warning": "LLM helper not configured", "chunks": chunks}, status=status.HTTP_200_OK)
        except Exception:
            # If import fails or LLM call errors, return raw chunks as fallback
            logger.warning("LLM helper not available or failed; returning raw chunks.")
            return Response({"chunks": chunks}, status=status.HTTP_200_OK)


class DocumentStatusView(APIView):
    """
    GET /api/docs/<id>/status/
    Returns Document metadata (title, status, uploaded_at, text_extracted)
    """
    def get(self, request, id: int, *args, **kwargs):
        doc = get_object_or_404(Document, pk=id)
        data = {
            "id": doc.id,
            "title": doc.title,
            "status": doc.status,
            "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
            "text_extracted": doc.text_extracted,
            "notes": doc.notes,
        }
        return Response(data, status=status.HTTP_200_OK)
