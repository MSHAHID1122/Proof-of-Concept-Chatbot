"""
Django management command to ingest uploaded PDF Documents.

Usage (shown in help text below as well):
  # Ingest a single document by id
  python manage.py ingest_pdfs --doc-id 42

  # Ingest all uploaded documents and attempt to call indexer
  python manage.py ingest_pdfs --all --call-index

Behavior:
- If --doc-id <id> is provided, the command will ingest only that Document.
- If --all is provided, the command will ingest all Documents with status == 'uploaded'.
- For each document:
    * status -> 'processing'
    * extract_text_from_pdf (with OCR fallback)
    * split_text into chunks
    * write JSON payload to MEDIA_ROOT/documents/index_payloads/<doc_id>.json
    * set text_extracted=True and keep status='processing' (indexing is separate)
- If --call-index is provided, the command will attempt to import apps.retrieval.indexer and call
  indexer.index_json_payload(path_to_json). If the import or call fails, a warning is printed and processing continues.

Note:
- This command expects the Document model (apps.core.models.Document) and the ingest utilities to exist.
- The indexer module is optional and may not exist in this project skeleton.
"""

from __future__ import annotations

import json
import os
import traceback
import logging
from typing import List, Optional

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from chatbot_poc.apps.core.models import Document
from chatbot_poc.apps.ingest.utils import extract_text_from_pdf, split_text

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Ingest uploaded PDF Documents into JSON payloads for indexing.\n\n"
        "Examples:\n"
        "  python manage.py ingest_pdfs --doc-id 42\n"
        "  python manage.py ingest_pdfs --all --call-index\n"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--doc-id",
            type=int,
            help="ID of the Document to ingest. Mutually exclusive with --all.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Ingest all Documents with status 'uploaded'.",
        )
        parser.add_argument(
            "--call-index",
            action="store_true",
            help="Attempt to call apps.retrieval.indexer.index_json_payload on created JSON files.",
        )

    def handle(self, *args, **options):
        doc_id: Optional[int] = options.get("doc_id")
        ingest_all: bool = options.get("all", False)
        call_index: bool = options.get("call_index", False)

        if bool(doc_id) and ingest_all:
            raise CommandError("Provide either --doc-id or --all, not both.")

        if not doc_id and not ingest_all:
            raise CommandError("You must provide --doc-id <id> or --all to run this command.")

        if doc_id:
            try:
                docs: List[Document] = [Document.objects.get(pk=doc_id)]
            except Document.DoesNotExist:
                raise CommandError(f"Document with id {doc_id} does not exist.")
        else:
            docs = list(Document.objects.filter(status=Document.STATUS_UPLOADED))

        if not docs:
            self.stdout.write(self.style.NOTICE("No documents to ingest."))
            return

        # prepare output dir
        out_base = os.path.join(settings.MEDIA_ROOT, "documents", "index_payloads")
        os.makedirs(out_base, exist_ok=True)

        self.stdout.write(self.style.SUCCESS(f"Starting ingestion of {len(docs)} document(s)."))
        for doc in docs:
            self.stdout.write(f"\n--- Ingesting Document id={doc.id} title={doc.title!r} ---")
            try:
                # mark processing
                doc.status = Document.STATUS_PROCESSING
                doc.save(update_fields=["status"])
                self.stdout.write(f"Set status -> {doc.status}")

                # get file path
                try:
                    pdf_path = doc.get_file_path()
                except Exception:
                    # Fallback to FileField path attribute, but prefer get_file_path method.
                    pdf_path = getattr(doc.file, "path", None)
                if not pdf_path or not os.path.exists(pdf_path):
                    raise FileNotFoundError(f"PDF file for Document {doc.id} not found at {pdf_path}")

                self.stdout.write(f"Extracting text from: {pdf_path}")
                text = extract_text_from_pdf(pdf_path)
                if not text:
                    self.stdout.write(self.style.WARNING("No text extracted; payload will be empty."))

                self.stdout.write("Splitting text into chunks...")
                chunks = split_text(text)
                self.stdout.write(f"Created {len(chunks)} chunk(s).")

                # approximate page assignment: distribute chunks across pages
                # Try to read page count using fitz if available (avoid importing if not)
                try:
                    import fitz  # PyMuPDF
                    pdf_doc = fitz.open(pdf_path)
                    page_count = len(pdf_doc)
                except Exception:
                    page_count = None

                payload = []
                total_chunks = max(1, len(chunks))
                for i, chunk in enumerate(chunks):
                    approx_page = None
                    if page_count:
                        # distribute chunks evenly across pages, pages numbered from 1..page_count
                        approx_page = int((i * page_count) / total_chunks) + 1
                        if approx_page < 1:
                            approx_page = 1
                        if approx_page > page_count:
                            approx_page = page_count
                    item = {
                        "content": chunk,
                        "meta": {"doc_id": doc.id, "title": doc.title, "page": approx_page},
                    }
                    payload.append(item)

                # write JSON
                out_path = os.path.join(out_base, f"{doc.id}.json")
                with open(out_path, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False, indent=2)

                self.stdout.write(self.style.SUCCESS(f"Wrote payload: {out_path}"))

                # mark text_extracted but keep status as processing (indexing separate)
                doc.text_extracted = True
                doc.status = Document.STATUS_PROCESSING
                doc.save(update_fields=["text_extracted", "status"])
                self.stdout.write(self.style.SUCCESS(f"Document {doc.id} marked text_extracted=True."))

                # optionally call indexer
                if call_index:
                    try:
                        from apps.retrieval import indexer  # type: ignore
                        if hasattr(indexer, "index_json_payload"):
                            self.stdout.write("Calling indexer.index_json_payload(...)")
                            try:
                                indexer.index_json_payload(out_path)
                                self.stdout.write(self.style.SUCCESS("Indexer call completed."))
                            except Exception as idx_err:
                                self.stdout.write(self.style.WARNING(f"Indexer raised an error: {idx_err}"))
                                self.stdout.write(traceback.format_exc())
                        else:
                            self.stdout.write(self.style.WARNING("apps.retrieval.indexer exists but has no index_json_payload function."))
                    except Exception as import_err:
                        self.stdout.write(self.style.WARNING("Could not import apps.retrieval.indexer: " + str(import_err)))
                        self.stdout.write(self.style.WARNING("Indexing skipped for this payload."))

            except Exception as e:
                tb = traceback.format_exc()
                self.stdout.write(self.style.ERROR(f"Error ingesting document {doc.id}: {e}"))
                logger.exception("Ingestion error for Document %s", doc.id)

                # update document status & notes
                try:
                    doc.status = Document.STATUS_FAILED
                    prev_notes = doc.notes or ""
                    doc.notes = prev_notes + "\n\nIngestion error:\n" + str(e) + "\n\n" + tb
                    doc.save(update_fields=["status", "notes"])
                except Exception:
                    # if saving fails, log and continue
                    logger.exception("Failed to update Document status/notes for %s", doc.id)

        self.stdout.write(self.style.SUCCESS("\nIngestion run completed."))
