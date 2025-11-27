import asyncio
import logging
import os
from typing import cast
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
import pytesseract  # type: ignore

from services.json_utils import safe_json_parse
from services.openai_client import chat_completion


# ---------------------------
# Extract text from PDF (OCR)
# ---------------------------
TESSERACT_CMD = os.getenv("TESSERACT_CMD")
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# Poppler directory (contains pdftoppm/pdftocairo). Often not needed on Linux when on PATH.
POPPLER_PATH = os.getenv("POPPLER_PATH")

logger = logging.getLogger(__name__)


# ---------------------------
# Main service function (for controller)
# ---------------------------
async def process_pdf_from_path(file_path: str, source: str) -> dict:
    raw_text = await _extract_text_from_pdf(file_path)

    if not raw_text.strip():
        return {
            "source": source,
            "total_chunks": 0,
            "partial_summaries": [],
            "final_summary": "No text could be extracted from this PDF. It may contain only images.",
        }

    chunks = _chunk_text(raw_text)
    partial_summaries = await asyncio.gather(*[_summarize_chunk(c) for c in chunks])
    final_summary = await _merge_summaries(partial_summaries)

    return {
        "source": source,
        "total_chunks": len(chunks),
        "partial_summaries": partial_summaries,
        "final_summary": final_summary,
    }


# ---------------------------
# Extract text from PDF
# ---------------------------
async def _extract_text_from_pdf(file_path: str) -> str:
    """Extract text from PDF using OCR on all pages to capture both text and images."""
    text = ""
    try:
        # Get total page count for logging
        reader = PdfReader(file_path)
        total_pages = len(reader.pages)

        logger.info(f"Starting OCR extraction for {total_pages} pages from {file_path}")

        # Convert all pages to images at once
        page_images = convert_from_path(file_path, poppler_path=cast(str, POPPLER_PATH))

        # OCR each page
        for page_num, page_image in enumerate(page_images, start=1):
            logger.info(f"OCR-ing page {page_num}/{total_pages}...")
            ocr_text = pytesseract.image_to_string(page_image)
            text += ocr_text + "\n"

        logger.info(f"OCR extraction completed. Extracted {len(text)} characters.")
        return text

    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""


# ---------------------------
# Split text into chunks
# ---------------------------
def _chunk_text(text: str, max_chars=3000) -> list[str]:
    chunks = []
    while len(text) > max_chars:
        split_index = text[:max_chars].rfind(".")
        if split_index == -1:
            split_index = max_chars
        chunks.append(text[: split_index + 1].strip())
        text = text[split_index + 1 :]
    if text.strip():
        chunks.append(text.strip())
    return chunks


# ---------------------------
# Summarize a chunk
# ---------------------------
# TODO: improve summarization by not doing summarization for each chunk, but for group of chunks.
async def _summarize_chunk(chunk: str) -> str:
    response = await chat_completion(
        messages=[
            {
                "role": "system",
                "content": (
                    "Rewrite the following PDF section as a summary that is clear but includes ALL factual details. "
                    "Do not omit or compress important information like numbers, measurements, specifications, floor plans with all the sizes if present, "
                    "lists, or technical terms. Preserve bullet points or lists where present. "
                    "Your job is to organize the text, not to shorten it aggressively."
                ),
            },
            {"role": "user", "content": chunk},
        ],
        model="gpt-4o-mini",
        max_tokens=600,
    )

    raw_output = response.choices[0].message.content.strip()
    return safe_json_parse(raw_output)


# ---------------------------
# Merge summaries
# ---------------------------
async def _merge_summaries(summaries: list[str]) -> str:
    combined_text = "\n".join(summaries)
    response = await chat_completion(
        messages=[
            {
                "role": "system",
                "content": """You are tasked with merging partial summaries of a PDF.
Your goal is to create a single unified summary that includes ALL details from the partial summaries.
Do not omit or compress any important information such as numbers, sizes, specifications, floor plans, or lists.
Ensure the final summary is coherent, but preserve every piece of factual information from the partial summaries.""",
            },
            {"role": "user", "content": combined_text},
        ],
        model="gpt-4o-mini",
        max_tokens=1000,
    )

    return response.choices[0].message.content.strip()
