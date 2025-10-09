import os
from fastapi import FastAPI
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
import pytesseract
from openai import OpenAI

app = FastAPI()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------
# Extract text from PDF (OCR)
# ---------------------------
TESSERACT_CMD = os.getenv("TESSERACT_CMD")
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# Poppler directory (contains pdftoppm/pdftocairo). Often not needed on Linux when on PATH.
POPPLER_PATH = os.getenv("POPPLER_PATH")

# ---------------------------
# Extract text from PDF
# ---------------------------
def extract_text_from_pdf(file_path: str) -> str:
    text = ""
    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"

        # If no selectable text, fallback to OCR
        if not text.strip():
            pages = convert_from_path(file_path, poppler_path=POPPLER_PATH)
            for page in pages:
                text += pytesseract.image_to_string(page) + "\n"
    except Exception as e:
        print("[ERROR] PDF extraction failed:", e)
    return text


# ---------------------------
# Split text into chunks
# ---------------------------
def chunk_text(text: str, max_chars=3000) -> list[str]:
    chunks = []
    while len(text) > max_chars:
        split_index = text[:max_chars].rfind(".")
        if split_index == -1:
            split_index = max_chars
        chunks.append(text[:split_index+1].strip())
        text = text[split_index+1:]
    if text.strip():
        chunks.append(text.strip())
    return chunks


# ---------------------------
# Summarize a chunk
# ---------------------------
def summarize_chunk(chunk: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": (
                    "Rewrite the following PDF section as a summary that is clear but includes ALL factual details. "
                    "Do not omit or compress important information like numbers, measurements, specifications, floor plans with all the sizes if present, "
                    "lists, or technical terms. Preserve bullet points or lists where present. "
                    "Your job is to organize the text, not to shorten it aggressively."
                )},
            {"role": "user", "content": chunk}
        ],
        max_tokens=600
    )
    return response.choices[0].message.content.strip()


# ---------------------------
# Merge summaries
# ---------------------------
def merge_summaries(summaries: list[str]) -> str:
    combined_text = "\n".join(summaries)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": """You are tasked with merging partial summaries of a PDF.
Your goal is to create a single unified summary that includes ALL details from the partial summaries.
Do not omit or compress any important information such as numbers, sizes, specifications, floor plans, or lists.
Ensure the final summary is coherent, but preserve every piece of factual information from the partial summaries."""},
            {"role": "user", "content": combined_text}
        ],
        max_tokens=1000
    )
    return response.choices[0].message.content.strip()


# ---------------------------
# Main service function (for controller)
# ---------------------------
def process_pdf_from_path(file_path: str, source: str) -> dict:
    raw_text = extract_text_from_pdf(file_path)

    if not raw_text.strip():
        return {
            "source": source,
            "total_chunks": 0,
            "partial_summaries": [],
            "final_summary": "No text could be extracted from this PDF. It may contain only images."
        }

    chunks = chunk_text(raw_text)
    partial_summaries = [summarize_chunk(c) for c in chunks]
    final_summary = merge_summaries(partial_summaries)

    return {
        "source": source,
        "total_chunks": len(chunks),
        "partial_summaries": partial_summaries,
        "final_summary": final_summary
    }