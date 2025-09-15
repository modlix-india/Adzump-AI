# import os
# import shutil
# from PyPDF2 import PdfReader
# from openai import OpenAI

# client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# # ---------------------------
# # Extract text from PDF
# # ---------------------------
# def extract_text_from_pdf(file_path: str) -> str:
#     reader = PdfReader(file_path)
#     text = ""
#     for page in reader.pages:
#         text += page.extract_text() or ""
#     return text

# # ---------------------------
# # Split into chunks
# # ---------------------------
# def chunk_text(text, max_chars=3000):
#     chunks = []
#     while len(text) > max_chars:
#         split_index = text[:max_chars].rfind(".")
#         if split_index == -1:
#             split_index = max_chars
#         chunks.append(text[:split_index+1])
#         text = text[split_index+1:]
#     chunks.append(text)
#     return chunks

# # ---------------------------
# # Summarize a chunk
# # ---------------------------
# def summarize_chunk(chunk: str) -> str:
#     response = client.chat.completions.create(
#         model="gpt-4o-mini",
#         messages=[
#             {"role": "system", "content": "Summarize the following PDF section clearly and concisely."},
#             {"role": "user", "content": chunk}
#         ],
#         max_tokens=400
#     )
#     return response.choices[0].message.content.strip()

# # ---------------------------
# # Merge multiple summaries
# # ---------------------------
# def merge_summaries(summaries: list[str]) -> str:
#     combined_text = "\n".join(summaries)
#     response = client.chat.completions.create(
#         model="gpt-4o-mini",
#         messages=[
#             {"role": "system", "content": "Combine the following partial summaries into a single coherent summary."},
#             {"role": "user", "content": combined_text}
#         ],
#         max_tokens=600
#     )
#     return response.choices[0].message.content.strip()

# # ---------------------------
# # Main summarize pipeline
# # ---------------------------
# def process_pdf(file, filename: str):
#     file_path = f"uploads/{filename}"
#     os.makedirs("uploads", exist_ok=True)

#     # Save uploaded file
#     with open(file_path, "wb") as buffer:
#         shutil.copyfileobj(file, buffer)

#     # Extract + process
#     raw_text = extract_text_from_pdf(file_path)
#     chunks = chunk_text(raw_text)
#     partial_summaries = [summarize_chunk(c) for c in chunks]
#     final_summary = merge_summaries(partial_summaries)

#     return {
#         "file_name": filename,
#         "total_chunks": len(chunks),
#         "partial_summaries": partial_summaries,
#         "final_summary": final_summary
#     }


import os
import shutil
from fastapi import FastAPI, UploadFile, File
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
import pytesseract
from openai import OpenAI

app = FastAPI()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------
# Extract text from PDF (OCR)
# ---------------------------
def extract_text_from_pdf(file_path: str) -> str:
    text = ""
    try:
        # First try extracting selectable text
        reader = PdfReader(file_path)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"

        # If no text found, fallback to OCR
        if not text.strip():
            pages = convert_from_path(file_path)
            for page in pages:
                text += pytesseract.image_to_string(page) + "\n"

    except Exception as e:
        print("PDF extraction failed:", e)
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
            {"role": "system", "content": "Summarize the following PDF section clearly and concisely."},
            {"role": "user", "content": chunk}
        ],
        max_tokens=400
    )
    return response.choices[0].message.content.strip()

# ---------------------------
# Merge multiple summaries
# ---------------------------
def merge_summaries(summaries: list[str]) -> str:
    combined_text = "\n".join(summaries)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Combine the following partial summaries into a single coherent summary."},
            {"role": "user", "content": combined_text}
        ],
        max_tokens=600
    )
    return response.choices[0].message.content.strip()

# ---------------------------
# Main PDF processing pipeline
# ---------------------------
def process_pdf(file, filename: str):
    os.makedirs("uploads", exist_ok=True)
    file_path = f"uploads/{filename}"

    # Save uploaded file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file, buffer)

    # Extract text + process
    raw_text = extract_text_from_pdf(file_path)

    if not raw_text.strip():
        return {
            "file_name": filename,
            "total_chunks": 0,
            "partial_summaries": [],
            "final_summary": "No text could be extracted from this PDF. It may contain images only."
        }

    chunks = chunk_text(raw_text)
    partial_summaries = [summarize_chunk(c) for c in chunks]
    final_summary = merge_summaries(partial_summaries)

    return {
        "file_name": filename,
        "total_chunks": len(chunks),
        "partial_summaries": partial_summaries,
        "final_summary": final_summary
    }
