#!/usr/bin/env python3
"""
extract_curriculum.py — PDF методики → grade_XX_clean.sql

Использует:
  1. PyMuPDF (fitz) для рендера страниц в PNG
  2. Gemini Vision (gemini-3.1-pro) для OCR через Vertex AI ADC
  3. Gemini Pro с thinking для генерации SQL (формат clean-файлов 5-9 классов)

Запуск:
  python3 extract_curriculum.py 10 "/Users/arslan/Desktop/ALGO/Отсканированный документ 10.pdf"
  python3 extract_curriculum.py 11 "/Users/arslan/Desktop/ALGO/Отсканированный документ 11.pdf"
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF — pip install pymupdf
import requests

# ── Config ────────────────────────────────────────────────────────────────────
GCP_PROJECT    = "algo-495713"
MODEL_OCR      = "gemini-2.5-flash"        # для Vision батчей (высокий RPM)
MODEL_SQL      = "gemini-3.1-pro-preview"  # для SQL генерации (один запрос)
VERTEX_URL     = (
    "https://aiplatform.googleapis.com/v1/projects/{project}/"
    "locations/global/publishers/google/models/{model}:generateContent"
)
RENDER_DPI    = 200       # выше для сканов
BATCH_SIZE    = 2         # страниц за один запрос Vision (меньше = меньше 429)
REQUEST_DELAY = 6.0       # пауза между запросами (rate limit)
CACHE_DIR     = Path("/tmp/curriculum_ocr_cache")
CACHE_DIR.mkdir(exist_ok=True)

OUT_DIR = Path(__file__).parent.parent / "diagnostic-service" / "data" / "curriculum"
EXAMPLE_SQL = Path(__file__).parent.parent / "diagnostic-service" / "data" / "curriculum" / "grade_05_clean.sql"


# ── Vertex AI helpers ─────────────────────────────────────────────────────────
_GCLOUD_PATHS = [
    "gcloud",
    "/usr/local/bin/gcloud",
    "/opt/homebrew/bin/gcloud",
    os.path.expanduser("~/google-cloud-sdk/bin/gcloud"),
]

def _get_token() -> str:
    # 1. Try google-auth library (fastest)
    try:
        import google.auth
        import google.auth.transport.requests
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        if creds.token:
            return creds.token
    except Exception:
        pass
    # 2. Fallback: gcloud CLI
    for gcloud in _GCLOUD_PATHS:
        try:
            r = subprocess.run(
                [gcloud, "auth", "application-default", "print-access-token"],
                capture_output=True, text=True, timeout=10,
            )
            tok = r.stdout.strip()
            if tok:
                return tok
        except Exception:
            continue
    raise RuntimeError("Cannot get ADC token. Run: gcloud auth application-default login")


def _post(model: str, payload: dict, token: str, timeout: int = 300) -> dict:
    url = VERTEX_URL.format(project=GCP_PROJECT, model=model)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    for attempt in range(4):
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if resp.status_code in (429, 500, 502, 503, 504):
            wait = 2 ** (attempt + 2)
            print(f"  HTTP {resp.status_code} → retry in {wait}s…")
            time.sleep(wait)
            token = _get_token()
            headers["Authorization"] = f"Bearer {token}"
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("Max retries exceeded")


def _extract_text(response: dict) -> str:
    parts = response["candidates"][0]["content"].get("parts", [])
    return "".join(p.get("text", "") for p in parts if "text" in p).strip()


# ── Step 1: OCR ───────────────────────────────────────────────────────────────
OCR_PROMPT = (
    "You are an OCR engine. This is a scanned page from a Russian/Uzbek mathematics "
    "methodology document. Extract ALL text exactly as written. Preserve:\n"
    "- Section/chapter/topic numbers and titles (§1, Глава 1, Тема 1.1, etc.)\n"
    "- Paragraph numbers and sub-paragraph letters\n"
    "- Learning objectives and skill descriptions\n"
    "- Table structure (use | markdown tables)\n"
    "Output ONLY the extracted text, nothing else."
)

def ocr_pdf(pdf_path: Path) -> str:
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]
    cache = CACHE_DIR / f"ocr_{digest}.txt"
    if cache.exists():
        print(f"  OCR cache hit → {cache}")
        return cache.read_text(encoding="utf-8")

    doc = fitz.open(str(pdf_path))
    total = doc.page_count
    mat = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)

    print(f"  Rendering {total} pages at {RENDER_DPI} DPI…")
    pages_b64 = []
    for i in range(total):
        pix = doc[i].get_pixmap(matrix=mat)
        pages_b64.append(base64.b64encode(pix.tobytes("png")).decode())
        print(f"    Page {i+1}/{total}", end="\r")
    print()

    token = _get_token()
    chunks = []
    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)
        print(f"  OCR pages {start+1}–{end}/{total}…")
        image_parts = [
            {"inlineData": {"mimeType": "image/png", "data": b64}}
            for b64 in pages_b64[start:end]
        ]
        payload = {
            "contents": [{"role": "user", "parts": image_parts + [{"text": OCR_PROMPT}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8192},
        }
        data = _post(MODEL_OCR, payload, token)
        chunks.append(f"[pages {start+1}–{end}]\n{_extract_text(data)}")
        time.sleep(REQUEST_DELAY)

    text = "\n\n".join(chunks)
    cache.write_text(text, encoding="utf-8")
    print(f"  OCR done: {len(text):,} chars → {cache}")
    return text


# ── Step 2: Generate SQL ──────────────────────────────────────────────────────
def _sql_prompt(grade: int, ocr_text: str) -> str:
    prefix = f"G{grade}"
    example = EXAMPLE_SQL.read_text(encoding="utf-8")
    # Trim OCR text to fit context (keep first 35k chars)
    ocr_trimmed = ocr_text[:35000]
    if len(ocr_text) > 35000:
        ocr_trimmed += f"\n\n[... {len(ocr_text)-35000:,} chars truncated ...]"

    return f"""You are an expert Uzbek school mathematics curriculum analyst.

Generate a complete SQL file for grade {grade} in EXACTLY the same format as the example below.

RULES:
1. ID prefix = "{prefix}_" (e.g. {prefix}_ALG, {prefix}_T01, {prefix}_P01, {prefix}_S01_01)
2. Hierarchy: L1=разделы → L2=темы → L3=пункты → L4=атомарные навыки
3. class_level_start = class_level_end = {grade}
4. L4 skills MUST have: cognitive_type (recall/apply/analyze/create), example_task (concrete math problem), assessed_ability, difficulty_level (Low/Medium/High with Level A/B/C), formula (NULL if none)
5. Every L3 paragraph must have AT LEAST 2-3 L4 skills covering different cognitive levels
6. name = English, name_ru = Russian original from the PDF
7. Start with DELETE statements for cleanup
8. Output ONLY valid PostgreSQL — no markdown fences, no explanations
9. Follow the grade 5 example structure exactly

=== GRADE 5 EXAMPLE FORMAT ===
{example[:9000]}

=== OCR TEXT FROM GRADE {grade} METHODOLOGY PDF ===
{ocr_trimmed}

Generate the complete grade_{grade:02d}_clean.sql now:"""


def generate_sql(grade: int, ocr_text: str) -> str:
    token = _get_token()
    print(f"  Calling Gemini {MODEL_SQL} with thinking…")
    payload = {
        "contents": [{"role": "user", "parts": [{"text": _sql_prompt(grade, ocr_text)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 32768,
            "thinkingConfig": {"thinkingBudget": 10000},
        },
    }
    data = _post(MODEL_SQL, payload, token, timeout=600)
    sql = _extract_text(data)

    # Strip markdown fences if model added them
    lines = sql.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 3:
        print("Usage: python3 extract_curriculum.py <grade> <pdf_path>")
        sys.exit(1)

    grade = int(sys.argv[1])
    pdf_path = Path(sys.argv[2])

    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        sys.exit(1)
    if not EXAMPLE_SQL.exists():
        print(f"ERROR: Example SQL not found: {EXAMPLE_SQL}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Grade {grade} curriculum extractor")
    print(f"  PDF:    {pdf_path.name}")
    print(f"  Output: {OUT_DIR}/grade_{grade:02d}_clean.sql")
    print(f"{'='*60}\n")

    # 1. OCR
    print("[1/2] OCR via Gemini Vision…")
    ocr_text = ocr_pdf(pdf_path)
    ocr_out = CACHE_DIR / f"grade{grade}_ocr.txt"
    ocr_out.write_text(ocr_text, encoding="utf-8")
    print(f"  OCR text saved → {ocr_out}\n")

    # 2. Generate SQL
    print("[2/2] Generating SQL…")
    sql = generate_sql(grade, ocr_text)

    out_path = OUT_DIR / f"grade_{grade:02d}_clean.sql"
    out_path.write_text(sql, encoding="utf-8")

    inserts = sql.count("INSERT INTO")
    deletes = sql.count("DELETE FROM")
    print(f"\n{'='*60}")
    print(f"  ✓ Written: {out_path}")
    print(f"  Stats: {inserts} INSERTs, {deletes} DELETEs, {len(sql):,} chars")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
