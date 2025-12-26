import os
import pytesseract
from structlog import get_logger    #type: ignore
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
from fastapi import HTTPException
from services.openai_client import chat_completion
from utils import prompt_loader
from utils.helpers import normalize_url
from oserver.models.storage_request_model import (
    StorageFilter,
    StorageReadRequest,
    StorageUpdateWithPayload
)
from oserver.services.storage_service import StorageService
from services.final_summary_service import generate_final_summary

logger = get_logger(__name__)

# -------------------------------------------------------------
# OCR / Poppler Setup
# -------------------------------------------------------------
TESSERACT_CMD = os.getenv("TESSERACT_CMD")
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    logger.info("[PDF-OCR] Tesseract CMD set.")

POPPLER_PATH = os.getenv("POPPLER_PATH")
if POPPLER_PATH:
    logger.info("[PDF-OCR] Using custom Poppler path.")


# -------------------------------------------------------------
# 1. Extract text from PDF
# -------------------------------------------------------------
def extract_text_from_pdf(file_path: str) -> str:
    logger.info(f"[PDFService] Extracting text from: {file_path}")

    text = ""
    try:
        reader = PdfReader(file_path)
        logger.info("[PDFService] PDF loaded successfully, extracting text pages...")

        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            logger.debug(f"[PDFService] Extracted text length from page {i}: {len(page_text) if page_text else 0}")

            if page_text:
                text += page_text + "\n"

        if not text.strip():
            logger.warning("[PDF-OCR] No text found, running OCR fallback...")
            pages = convert_from_path(file_path, poppler_path=POPPLER_PATH)

            for i, page in enumerate(pages):
                logger.debug(f"[PDF-OCR] Running OCR on page {i}")
                text += pytesseract.image_to_string(page) + "\n"

    except Exception as e:
        logger.exception(f"[PDF-OCR] PDF extraction failed: {e}")

    logger.info(f"[PDFService] Total extracted text length: {len(text)}")
    return text


# -------------------------------------------------------------
# 2. Split text into chunks
# -------------------------------------------------------------
def chunk_text(text: str, max_chars=3000) -> list[str]:
    logger.info("[PDFService] Splitting text into chunks...")

    chunks = []
    while len(text) > max_chars:
        split_index = text[:max_chars].rfind(".")
        if split_index == -1:
            split_index = max_chars

        chunk = text[:split_index + 1].strip()
        logger.debug(f"[PDF-Chunk] Created chunk of length {len(chunk)}")

        chunks.append(chunk)
        text = text[split_index + 1:]

    if text.strip():
        logger.debug(f"[PDF-Chunk] Final chunk of length {len(text.strip())}")
        chunks.append(text.strip())

    logger.info(f"[PDFService] Total chunks created: {len(chunks)}")
    return chunks


# -------------------------------------------------------------
# 3. Summarize one chunk
# -------------------------------------------------------------
async def summarize_chunk(chunk: str) -> str:
    logger.info(f"[PDF-Chunk] Summarizing chunk length={len(chunk)}")

    prompt = prompt_loader.format_prompt("business/pdf_chunk_summary.txt", text=chunk)

    response = await chat_completion(
        messages=[{"role": "user", "content": prompt}],
        model="gpt-4o-mini",
        max_tokens=600,
        temperature=0.2
    )

    summary = response.choices[0].message.content.strip()
    logger.debug(f"[PDF-Chunk] Summary length={len(summary)}")

    return summary


# -------------------------------------------------------------
# 4. Merge all chunk summaries
# -------------------------------------------------------------
async def merge_summaries(summaries: list[str]) -> str:
    logger.info(f"[PDF-Merge] Merging {len(summaries)} partial summaries...")

    combined = "\n".join(summaries)
    logger.debug(f"[PDF-Merge] Combined text length before merge={len(combined)}")

    prompt = prompt_loader.format_prompt("business/pdf_merge_summary.txt", summaries=combined)

    response = await chat_completion(
        messages=[{"role": "user", "content": prompt}],
        model="gpt-4o-mini",
        max_tokens=7000,
        temperature=0.2
    )

    final_text = response.choices[0].message.content.strip()
    logger.info(f"[PDF-Merge] Final merged summary length={len(final_text)}")

    return final_text


# -------------------------------------------------------------
# 5. Main PDF processing flow
# -------------------------------------------------------------
async def process_pdf_from_path(
    file_path: str,
    source_url: str,
    business_url: str,
    access_token: str,
    client_code: str,
    x_forwarded_host: str,
    x_forwarded_port: str
):

    logger.info(f"[PDFService] Starting PDF processing for businessUrl={business_url}")

    # ---------------------------------------------------------
    # STEP A: FIRST validate businessUrl exists in storage
    # ---------------------------------------------------------
    business_url = normalize_url(business_url)
    logger.info(f"[PDFService] Normalized businessUrl: {business_url}")

    read_request = StorageReadRequest(
        storageName="AISuggestedData",
        appCode="marketingai",
        clientCode=client_code,
        filter=StorageFilter(field="businessUrl", value=business_url)
    )

    storage_service = StorageService(
        access_token=access_token,
        client_code=client_code,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port
    )

    logger.info("[PDF-Storage] Checking if business record exists...")
    record_response = await storage_service.read_page_storage(read_request)

    if not record_response.success:
        logger.error("[PDF-Storage] Storage read failed.")
        raise HTTPException(500, "Storage read failed")

    # Extract the record
    records = (
        record_response.result[0]
        .get("result", {})
        .get("result", {})
        .get("content", [])
    )

    if not records:
        logger.error("[PDF-Storage] No product found for this businessUrl")
        raise HTTPException(404, "No product found for this businessUrl")

    record = records[-1]
    product_id = record.get("_id")

    logger.info(f"[PDF-Storage] Product found in storage. ID={product_id}")

    # ---------------------------------------------------------
    # STEP B: Extract PDF + Summaries AFTER confirming product
    # ---------------------------------------------------------
    raw_text = extract_text_from_pdf(file_path)

    if not raw_text.strip():
        logger.warning("[PDFService] No extractable text found in the PDF.")
        pdf_summary = "No extractable text found. PDF might contain only images."
    else:
        chunks = chunk_text(raw_text)
        partial_summaries = [
            await summarize_chunk(chunk)
            for chunk in chunks
        ]
        pdf_summary = await merge_summaries(partial_summaries)

    logger.info("[PDFService] PDF summary generated successfully.")

    # ---------------------------------------------------------
    # STEP C: Update assets[] with PDF summary
    # ---------------------------------------------------------
    assets = record.get("assets", [])
    assets.append({
        "fileName": source_url,
        "fileSummary": pdf_summary
    })

    update_request = StorageUpdateWithPayload(
        storageName="AISuggestedData",
        dataObjectId=product_id,
        clientCode=client_code,
        appCode="",
        dataObject={"assets": assets}
    )

    update_result = await storage_service.update_storage(update_request)

    if not update_result.success:
        logger.error("[PDF-Storage] Failed updating assets[]")
        raise HTTPException(500, "Failed adding PDF summary")

    logger.info("[PDF-Storage] PDF summary added successfully.")

    # ---------------------------------------------------------
    # STEP D: Regenerate final summary
    # ---------------------------------------------------------
    final_summary_result = await generate_final_summary(
        business_url=business_url,
        access_token=access_token,
        client_code=client_code,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port
    )

    logger.info("[PDF-FinalSummary] Final summary regenerated after PDF upload.")

    # ---------------------------------------------------------
    # STEP E: Return final API response
    # ---------------------------------------------------------
    return {
        "pdfSummary": pdf_summary,
        "finalSummary": final_summary_result["finalSummary"],
        "updatedStorageId": product_id
    }