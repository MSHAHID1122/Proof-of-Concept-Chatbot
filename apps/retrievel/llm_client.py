"""
Lightweight LLM client abstraction for the chatbot POC.

Provides:
- generate_answer(query: str, retrieved_chunks: List[dict], model: str = "gpt-4o-mini") -> dict

Behavior:
- If OPENAI_API_KEY is present in the environment, call OpenAI ChatCompletion API (via `openai` package)
  with a carefully crafted system prompt that *enforces* "answer only from provided documents".
- If OPENAI_API_KEY is missing, return a deterministic fallback that concatenates the top chunks and
  marks the model as "fallback".

Safety / prompt size:
- The function implements a simple character-based heuristic to avoid creating a prompt that is obviously
  too large for model token limits. It will truncate the number of chunks and/or truncate each chunk if
  the combined size exceeds an upper bound.
- We approximate tokens ~ chars / 4 for a rough guard (not exact). For production, replace with a real tokenizer.

Note:
- Requires `openai` package to actually call OpenAI.
- The design intentionally forces the model to reply "Answer not found in provided documents." if the
  answer cannot be found verbatim or confidently in the provided excerpts — this is enforced via the
  system prompt and by including the full excerpts as the only context the model may use.
"""

from typing import List, Dict, Any, Optional
import os
import logging
import textwrap

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Heuristics / limits
_APPROX_CHARS_PER_TOKEN = 4  # rough heuristic: 4 chars ~= 1 token
_MAX_TOKENS_CONTEXT = 32000  # permissive upper bound for long-context models (adjust per model)
_MAX_CHARS_CONTEXT = _MAX_TOKENS_CONTEXT * _APPROX_CHARS_PER_TOKEN
_DEFAULT_MAX_CHUNKS = 10
_DEFAULT_TRUNC_PER_CHUNK = 4000  # chars per chunk if we need to truncate

# Default model
_DEFAULT_MODEL = "gpt-4o-mini"


def _prepare_context_chunks(retrieved_chunks: List[dict], max_total_chars: int = _MAX_CHARS_CONTEXT,
                            max_chunks: int = _DEFAULT_MAX_CHUNKS,
                            max_chars_per_chunk: int = _DEFAULT_TRUNC_PER_CHUNK) -> List[dict]:
    """
    Given retrieved chunks (list of {"content":..., "meta":...}), prepare a safe subset that
    fits within approximate character budget. Returns a list of (possibly truncated) chunk dicts.
    """
    if not retrieved_chunks:
        return []

    # Start by taking up to max_chunks (prefer the first/top chunks)
    selected = retrieved_chunks[:max_chunks]

    total_chars = sum(len(c.get("content", "")) for c in selected)
    if total_chars <= max_total_chars:
        return selected

    # Otherwise, truncate each selected chunk to at most max_chars_per_chunk, preserve beginning of chunk
    truncated = []
    for c in selected:
        content = c.get("content", "") or ""
        if len(content) > max_chars_per_chunk:
            content = content[:max_chars_per_chunk] + "\n\n[TRUNCATED]"
        truncated.append({"content": content, "meta": c.get("meta", {})})
    # If still too big, further reduce number of chunks
    total_chars = sum(len(c["content"]) for c in truncated)
    while total_chars > max_total_chars and truncated:
        truncated.pop()  # drop the last chunk
        total_chars = sum(len(c["content"]) for c in truncated)

    return truncated


def _build_prompt_system() -> str:
    """
    Return the system-level instructions that strictly bound the model to the provided documents.
    """
    system = textwrap.dedent(
        """
        You are an assistant that MUST answer using ONLY the provided document excerpts.
        Important rules (follow exactly):
        1. You are RESTRICTED to using ONLY the information contained in the provided document excerpts.
           Do NOT use external knowledge, world knowledge, or make assumptions.
        2. If the answer cannot be found in the provided excerpts, respond exactly with:
           "Answer not found in provided documents."
           (Do NOT provide any other text or attempt to guess or hallucinate.)
        3. When you provide an answer, include a short "SOURCES:" section listing the document titles or IDs
           that you used (from the provided metadata). If you used multiple excerpts, list them comma-separated.
        4. Keep the answer concise and focused on the user's question.
        5. If the question is ambiguous and the answer is present in documents only for one plausible interpretation,
           answer based on the document evidence and do not invent clarifying assumptions.
        6. If the documents contain contradictory information, indicate that the documents disagree and cite the sources.
        """
    ).strip()
    return system


def _build_user_prompt(query: str, context_chunks: List[dict]) -> str:
    """
    Construct the user prompt containing the concatenated context and the user question.
    Each chunk is prefixed with metadata for traceability.
    """
    lines = []
    lines.append("DOCUMENT EXCERPTS (use ONLY these to answer):")
    for i, c in enumerate(context_chunks, start=1):
        meta = c.get("meta") or {}
        meta_parts = []
        if isinstance(meta, dict):
            if "title" in meta:
                meta_parts.append(f"title={meta.get('title')}")
            if "doc_id" in meta:
                meta_parts.append(f"doc_id={meta.get('doc_id')}")
            if "page" in meta:
                meta_parts.append(f"page={meta.get('page')}")
        meta_str = ", ".join(meta_parts) if meta_parts else f"chunk_index={i}"
        lines.append(f"--- EXCERPT {i} | {meta_str} ---")
        lines.append(c.get("content", ""))
        lines.append("")  # blank line between excerpts

    lines.append("END OF EXCERPTS")
    lines.append("")
    lines.append("USER QUESTION:")
    lines.append(query)
    lines.append("")
    lines.append(
        "INSTRUCTIONS: Answer using ONLY the excerpts above. If the answer is not present, EXACTLY respond: "
        "\"Answer not found in provided documents.\""
    )

    return "\n".join(lines)


def generate_answer(query: str, retrieved_chunks: List[dict], model: str = _DEFAULT_MODEL) -> Dict[str, Any]:
    """
    Generate an answer for `query` using `retrieved_chunks`.

    Args:
        query: User query string.
        retrieved_chunks: List of dicts with keys "content" and "meta".
        model: Model name to use for OpenAI (e.g., "gpt-4o-mini").

    Returns:
        dict: {
            "answer": <str>,
            "sources": [<title_or_doc_id>, ...],
            "model": <used_model>
        }

    Behavior:
        - If OPENAI_API_KEY is set in the environment, calls OpenAI ChatCompletion API.
        - Otherwise returns a fallback dict with concatenated chunks.
    """
    # Prepare sources list (metadata titles or ids)
    sources = []
    for c in retrieved_chunks:
        meta = c.get("meta") or {}
        title = meta.get("title") if isinstance(meta, dict) else None
        doc_id = meta.get("doc_id") if isinstance(meta, dict) else None
        if title:
            sources.append(str(title))
        elif doc_id:
            sources.append(str(doc_id))
        else:
            sources.append("unknown")

    # Prepare safe context
    context_chunks = _prepare_context_chunks(retrieved_chunks)

    # If OPENAI not configured, return fallback
    if not os.environ.get("OPENAI_API_KEY"):
        logger.info("OPENAI_API_KEY not found; returning fallback concatenated chunks.")
        concatenated = "\n\n---\n\n".join([c.get("content", "") for c in context_chunks]) or "No context available."
        fallback_answer = (
            "LLM not configured. Returning top document excerpts concatenated below.\n\n" + concatenated
        )
        return {"answer": fallback_answer, "sources": sources, "model": "fallback"}

    # Build prompts
    system_prompt = _build_prompt_system()
    user_prompt = _build_user_prompt(query, context_chunks)

    # For clarity, we prepare a combined length estimate and truncate if needed
    approx_chars = len(system_prompt) + len(user_prompt)
    if approx_chars > _MAX_CHARS_CONTEXT:
        # As a last resort, reduce number of chunks drastically
        logger.warning("Combined prompt length (%d chars) exceeds safe limit (%d). Truncating context.", approx_chars, _MAX_CHARS_CONTEXT)
        context_chunks = _prepare_context_chunks(retrieved_chunks, max_total_chars=_MAX_CHARS_CONTEXT//2, max_chunks=3, max_chars_per_chunk=1000)
        user_prompt = _build_user_prompt(query, context_chunks)

    # Now call OpenAI
    try:
        import openai
    except Exception as e:
        logger.exception("openai package is not installed but OPENAI_API_KEY is set.")
        # fallback behavior
        concatenated = "\n\n---\n\n".join([c.get("content", "") for c in context_chunks]) or "No context available."
        fallback_answer = "OpenAI client library not available. Returning concatenated excerpts.\n\n" + concatenated
        return {"answer": fallback_answer, "sources": sources, "model": "fallback"}

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    openai.api_key = openai_api_key

    # Construct messages for chat completion
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        # safe defaults
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages,
            max_tokens=1024,  # response length cap; adjust as needed
            temperature=0.0,  # deterministic
        )
        # Extract text
        choice = response.choices[0]
        text = choice.message.get("content", "").strip() if hasattr(choice, "message") else choice.text.strip()
        return {"answer": text, "sources": sources, "model": model}
    except Exception as e:
        logger.exception("OpenAI API call failed: %s", e)
        # return fallback concatenated chunks in case of API failure
        concatenated = "\n\n---\n\n".join([c.get("content", "") for c in context_chunks]) or "No context available."
        fallback_answer = "OpenAI API call failed. Returning concatenated excerpts.\n\n" + concatenated
        return {"answer": fallback_answer, "sources": sources, "model": "fallback", "error": str(e)}


# Example of the final concatenated prompt that would be sent to OpenAI (for clarity)
_EXAMPLE_PROMPT = """SYSTEM:
You are an assistant that MUST answer using ONLY the provided document excerpts.
Important rules (follow exactly):
1. You are RESTRICTED to using ONLY the information contained in the provided document excerpts.
...

USER:
DOCUMENT EXCERPTS (use ONLY these to answer):
--- EXCERPT 1 | title=Accounting Guidance, doc_id=42 ---
[excerpt text here...]

--- EXCERPT 2 | title=Revenue Rules, doc_id=17 ---
[excerpt text here...]

END OF EXCERPTS

USER QUESTION:
How should revenue be recognised for service contracts?

INSTRUCTIONS: Answer using ONLY the excerpts above. If the answer is not present, EXACTLY respond: "Answer not found in provided documents."
"""

# The _EXAMPLE_PROMPT variable above is illustrative and shows the structure of the system + user messages
# that will be sent to the OpenAI ChatCompletion API.
