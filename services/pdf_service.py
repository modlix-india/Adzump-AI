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
from pdf2image.exceptions import PDFInfoNotInstalledError
import pytesseract
from openai import OpenAI

app = FastAPI()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------
# Extract text from PDF (OCR)
# ---------------------------
POPPLER_PATH = r"C:\Users\CEPL\Downloads\Release-25.07.0-0\poppler-25.07.0\Library\bin" 
pytesseract.pytesseract.tesseract_cmd = r"C:\Users\CEPL\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"

def extract_text_from_pdf(file_path: str) -> str:
    text = ""
    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"

        if text.strip():
            print("[INFO] Extracted text directly from PDF")
        else:
            print("[INFO] No selectable text found, trying OCR...")
            try:
                pages = convert_from_path(file_path, poppler_path=POPPLER_PATH)
                print(f"[INFO] OCR mode: {len(pages)} pages found")
                for i, page in enumerate(pages):
                    ocr_text = pytesseract.image_to_string(page)
                    print(f"[DEBUG] OCR Page {i+1} length: {len(ocr_text.strip())}")
                    text += ocr_text + "\n"
            except Exception as e:
                print("[ERROR] OCR failed:", e)

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
