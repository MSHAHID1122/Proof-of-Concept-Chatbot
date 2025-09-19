"""
PDF ingestion utilities.

Provides:
- extract_text_from_pdf(path: str) -> str
- is_scanned_pdf(path: str) -> bool
- split_text(text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]

Notes:
- Requires Tesseract OCR installed on the host to use pytesseract.
  If Tesseract is not on PATH, set:
    pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'
  (or the appropriate path for your OS)
"""

from typing import List
import logging

import fitz  # PyMuPDF
from PIL import Image
import pytesseract

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Heuristics
_MIN_TEXT_LENGTH_FOR_NO_OCR = 50  # chars: if text shorter than this, treat as no-extractable-text (use OCR)
_SCANNED_THRESHOLD_RATIO = 0.30  # if >30% pages need OCR -> scanned


def extract_text_from_pdf(path: str) -> str:
    """
    Extract text from a PDF file. For each page:
      - try to extract selectable text via PyMuPDF (page.get_text()).
      - if the text is empty/very short, render the page to an image and apply Tesseract OCR.

    Returns:
        Single string with the concatenated page texts separated by two newlines.
    """
    logger.info("Starting text extraction for PDF: %s", path)
    texts: List[str] = []
    try:
        doc = fitz.open(path)
    except Exception as e:
        logger.exception("Failed to open PDF %s: %s", path, e)
        raise

    for page_number in range(len(doc)):
        try:
            page = doc.load_page(page_number)
            page_text = page.get_text().strip()  # default text extraction
            used_ocr = False

            if len(page_text) < _MIN_TEXT_LENGTH_FOR_NO_OCR:
                # fallback to OCR
                logger.debug("Page %d: text too short (%d chars). Running OCR.", page_number, len(page_text))
                try:
                    # render at higher resolution for better OCR results
                    mat = fitz.Matrix(2.0, 2.0)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    mode = "RGB" if pix.n < 4 else "RGBA"
                    img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                    if mode == "RGBA":
                        img = img.convert("RGB")
                    ocr_text = pytesseract.image_to_string(img)
                    if ocr_text:
                        page_text = ocr_text.strip()
                        used_ocr = True
                        logger.debug("Page %d: OCR produced %d chars.", page_number, len(page_text))
                    else:
                        logger.debug("Page %d: OCR produced no text.", page_number)
                except Exception as ocr_err:
                    # don't fail the whole extraction if OCR fails for a page
                    logger.exception("OCR failed for page %d of %s: %s", page_number, path, ocr_err)

            if page_text:
                texts.append(page_text)
            else:
                logger.debug("Page %d produced no text after extraction and OCR.", page_number)

            # We intentionally do not persist page-level OCR flag here; is_scanned_pdf() will re-check cheaply.
        except Exception as page_err:
            logger.exception("Failed processing page %d of %s: %s", page_number, path, page_err)
            # continue with other pages

    full_text = "\n\n".join(texts).strip()
    logger.info("Completed extraction for PDF: %s (chars=%d)", path, len(full_text))
    return full_text


def is_scanned_pdf(path: str) -> bool:
    """
    Heuristic to determine whether a PDF is scanned (image-based) by checking how many pages
    have no or very little selectable text.

    Returns:
        True if more than _SCANNED_THRESHOLD_RATIO of pages appear to need OCR.
    """
    logger.info("Checking if PDF is scanned (heuristic): %s", path)
    try:
        doc = fitz.open(path)
    except Exception as e:
        logger.exception("Failed to open PDF %s: %s", path, e)
        raise

    total_pages = len(doc)
    if total_pages == 0:
        logger.debug("PDF %s has 0 pages; treating as not scanned.", path)
        return False

    ocr_needed_pages = 0
    for i in range(total_pages):
        try:
            page = doc.load_page(i)
            text = page.get_text().strip()
            if len(text) < _MIN_TEXT_LENGTH_FOR_NO_OCR:
                ocr_needed_pages += 1
        except Exception as e:
            logger.exception("Error checking page %d of %s: %s", i, path, e)
            # consider this page as needing OCR (conservative)
            ocr_needed_pages += 1

    ratio = ocr_needed_pages / total_pages
    logger.debug("PDF %s: %d/%d pages need OCR (ratio=%.2f)", path, ocr_needed_pages, total_pages, ratio)
    return ratio > _SCANNED_THRESHOLD_RATIO


def split_text(text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
    """
    Split text into chunks by words.

    Args:
        text: Input text.
        chunk_size: Maximum number of words per chunk.
        overlap: Number of words to overlap between consecutive chunks.

    Returns:
        List of string chunks. Attempts to preserve sentence boundaries by
        preferring to split at the last period inside the chunk if available.
    """
    if not text:
        return []

    # normalize whitespace and split into words
    words = text.strip().split()
    if not words:
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: List[str] = []
    start = 0
    total_words = len(words)

    while start < total_words:
        end = min(start + chunk_size, total_words)
        # raw candidate chunk
        candidate = " ".join(words[start:end])

        # attempt to preserve sentence boundary: prefer last period '.' inside candidate
        split_idx = candidate.rfind('.')
        if split_idx != -1 and split_idx > int(len(candidate) * 0.3):
            # split at the sentence end (include the period)
            chunk_text = candidate[:split_idx + 1].strip()
            # compute how many words that chunk consumed
            consumed_words = len(chunk_text.split())
            if consumed_words == 0:
                # fallback to simple split
                chunk_text = candidate
                consumed_words = end - start
        else:
            chunk_text = candidate
            consumed_words = end - start

        # append chunk if non-empty
        if chunk_text:
            chunks.append(chunk_text)

        # advance start index with overlap
        start = start + consumed_words - overlap
        if start <= 0:
            # guard against non-progress
            start = consumed_words
        # ensure we don't loop forever
        if start >= total_words:
            break

    # final cleanup: remove any empty or whitespace-only chunks
    final_chunks = [c.strip() for c in chunks if c and c.strip()]
    logger.info("split_text: created %d chunks (chunk_size=%d, overlap=%d)", len(final_chunks), chunk_size, overlap)
    return final_chunks


if __name__ == "__main__":
    # simple illustrative unit-test-like functions (do not require test framework)
    def _test_split_text():
        sample = (
            "This is the first sentence. Here is the second sentence which is a bit longer and "
            "should ideally stay together. Finally, the last short sentence."
        )
        chunks = split_text(sample, chunk_size=10, overlap=2)
        print("SPLIT RESULT:", chunks)
        # expected: at least 1-2 chunks, with splits preferring sentence boundaries.

    def _test_extract_text():
        # Note: This is an explanatory example. It won't run without a real PDF file path.
        example_path = "/path/to/sample.pdf"
        print("Would extract text from:", example_path)
        print("is_scanned_pdf(example_path) ->", "<True/False depending on file>")
        print("extract_text_from_pdf(example_path) ->", "<long string of extracted text>")
        # To run for real:
        # text = extract_text_from_pdf(example_path)
        # print(text[:500])

    # run the illustrative tests
    _test_split_text()
    _test_extract_text()
