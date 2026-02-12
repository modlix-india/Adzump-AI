import os
import json
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

TESSERACT_CMD = os.getenv("TESSERACT_CMD")
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    logger.info("Tesseract CMD configured", component="pdf-ocr")

POPPLER_PATH = os.getenv("POPPLER_PATH")
if POPPLER_PATH:
    logger.info("Custom Poppler path set", component="pdf-ocr")


def extract_text_from_pdf(file_path: str) -> str:
    logger.info("Extracting text from PDF", component="pdf", file_path=file_path)

    text = ""
    try:
        reader = PdfReader(file_path)
        logger.info("PDF loaded, extracting pages", component="pdf", page_count=len(reader.pages))

        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            logger.debug("Page text extracted", component="pdf", page=i, length=len(page_text) if page_text else 0)

            if page_text:
                text += page_text + "\n"

        if not text.strip():
            logger.warning("No text found, running OCR fallback", component="pdf-ocr")
            pages = convert_from_path(file_path, poppler_path=POPPLER_PATH)

            for i, page in enumerate(pages):
                logger.debug("Running OCR on page", component="pdf-ocr", page=i)
                text += pytesseract.image_to_string(page) + "\n"

    except Exception as e:
        logger.exception("PDF extraction failed", component="pdf-ocr", error=str(e))

    logger.info("Text extraction complete", component="pdf", text_length=len(text))
    return text


def chunk_text(text: str, max_chars=3000) -> list[str]:
    chunks = []
    while len(text) > max_chars:
        split_index = text[:max_chars].rfind(".")
        if split_index == -1:
            split_index = max_chars

        chunk = text[:split_index + 1].strip()
        logger.debug("Chunk created", component="pdf-chunk", length=len(chunk))

        chunks.append(chunk)
        text = text[split_index + 1:]

    if text.strip():
        logger.debug("Final chunk created", component="pdf-chunk", length=len(text.strip()))
        chunks.append(text.strip())

    logger.info("Text chunking complete", component="pdf-chunk", chunk_count=len(chunks))
    return chunks


async def summarize_chunk(chunk: str) -> str:
    logger.info("Summarizing chunk", component="pdf-chunk", chunk_length=len(chunk))

    prompt = prompt_loader.format_prompt("business/pdf_chunk_summary.txt", text=chunk)

    response = await chat_completion(
        messages=[{"role": "user", "content": prompt}],
        model="gpt-4o-mini",
        max_tokens=600,
        temperature=0.2
    )

    summary = response.choices[0].message.content.strip()
    logger.debug("Chunk summarized", component="pdf-chunk", summary_length=len(summary))

    return summary


async def merge_summaries(summaries: list[str]) -> str:
    logger.info("Merging partial summaries", component="pdf-merge", count=len(summaries))

    combined = "\n".join(summaries)
    logger.debug("Combined text prepared", component="pdf-merge", combined_length=len(combined))

    prompt = prompt_loader.format_prompt("business/pdf_merge_summary.txt", summaries=combined)

    response = await chat_completion(
        messages=[{"role": "user", "content": prompt}],
        model="gpt-4o-mini",
        max_tokens=7000,
        temperature=0.2
    )

    raw_response = response.choices[0].message.content.strip()
    logger.debug("Merge response received", component="pdf-merge", response_length=len(raw_response))

    try:
        parsed = json.loads(raw_response)
        final_text = parsed.get("mergedSummary", raw_response)
        logger.info("Merged summary parsed", component="pdf-merge", summary_length=len(final_text))
    except json.JSONDecodeError:
        logger.warning("Failed to parse merge JSON, using raw response", component="pdf-merge")
        final_text = raw_response

    return final_text


async def process_pdf_from_path(
    file_path: str,
    source_url: str,
    business_url: str,
    access_token: str,
    client_code: str,
    x_forwarded_host: str,
    x_forwarded_port: str
):

    logger.info("Starting PDF processing", component="pdf", business_url=business_url)

    business_url = normalize_url(business_url)
    logger.info("Business URL normalized", component="pdf", business_url=business_url)

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

    logger.info("Checking business record in storage", component="pdf-storage")
    record_response = await storage_service.read_page_storage(read_request)

    if not record_response.success:
        logger.error("Storage read failed", component="pdf-storage")
        raise HTTPException(500, "Storage read failed")

    records = (
        record_response.result[0]
        .get("result", {})
        .get("result", {})
        .get("content", [])
    )

    if not records:
        logger.error("No product found for business URL", component="pdf-storage", business_url=business_url)
        raise HTTPException(404, "No product found for this businessUrl")

    record = records[-1]
    product_id = record.get("_id")

    logger.info("Product found in storage", component="pdf-storage", product_id=product_id)

    raw_text = extract_text_from_pdf(file_path)

    if not raw_text.strip():
        logger.warning("No extractable text in PDF", component="pdf")
        pdf_summary = "No extractable text found. PDF might contain only images."
    else:
        chunks = chunk_text(raw_text)
        partial_summaries = [
            await summarize_chunk(chunk)
            for chunk in chunks
        ]
        pdf_summary = await merge_summaries(partial_summaries)

    logger.info("PDF summary generated", component="pdf")

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
        logger.error("Failed updating assets", component="pdf-storage", product_id=product_id)
        raise HTTPException(500, "Failed adding PDF summary")

    logger.info("PDF summary added to storage", component="pdf-storage", product_id=product_id)

    final_summary_result = await generate_final_summary(
        business_url=business_url,
        access_token=access_token,
        client_code=client_code,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port
    )

    logger.info("Final summary regenerated after PDF upload", component="pdf")

    return {
        "pdfSummary": pdf_summary,
        "finalSummary": final_summary_result["finalSummary"],
        "updatedStorageId": product_id
    }
