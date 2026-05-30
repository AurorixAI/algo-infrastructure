#!/usr/bin/env python3
"""
parse_curriculum.py — Pure Python: OCR text → grade_XX_clean.sql

NO LLM для генерации SQL. Только:
  1. OCR через Gemini Vision (если кэша нет)
  2. Regex-парсер OCR текста → иерархия объектов
  3. SQL-генератор на Python → точный формат grade_05–09_clean.sql

Формат PDF (Sardor Bozorov):
  Раздел N. <название>
    Тема N. <название>
      N. <параграф>
        Навык N. <навык>
        Задача: <текст задачи>
        Проверяемое умение: <что проверяется>
        Сложность: Low (Level A) | Medium (Level B) | High (Level C)
        Формула: <формула>   (опционально)

Использование:
  python3 scripts/parse_curriculum.py 10           # из кэша grade10_ocr.txt
  python3 scripts/parse_curriculum.py 11           # из кэша grade11_ocr.txt
  python3 scripts/parse_curriculum.py 10 "Темы 10 класса.pdf"   # OCR + parse
"""

import re
import sys
import hashlib
import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ── Пути ──────────────────────────────────────────────────────────────────────
CACHE_DIR = Path("/tmp/curriculum_ocr_cache")
CACHE_DIR.mkdir(exist_ok=True)
OUT_DIR = (
    Path(__file__).resolve().parent.parent
    / "diagnostic-service" / "data" / "curriculum"
)

# ── OCR (только если нет кэша) ────────────────────────────────────────────────
GCP_PROJECT = "algo-495713"
MODEL_OCR   = "gemini-2.5-flash"
VERTEX_URL  = (
    "https://aiplatform.googleapis.com/v1/projects/{project}/"
    "locations/global/publishers/google/models/{model}:generateContent"
)
RENDER_DPI  = 200
BATCH_SIZE  = 2
DELAY       = 6.0

OCR_PROMPT = (
    "OCR this Russian mathematics methodology page (Sardor Bozorov). "
    "Extract ALL text exactly as written. Preserve structure:\n"
    "- Раздел N. / Тема N. / N. (paragraph) headings\n"
    "- Навык N. skill names\n"
    "- Задача: / Проверяемое умение: / Сложность: / Формула: fields\n"
    "Output ONLY the extracted text, nothing else."
)


def _get_token() -> str:
    import warnings
    warnings.filterwarnings("ignore")
    import google.auth
    import google.auth.transport.requests
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _post(model: str, payload: dict, token: str, timeout: int = 120) -> dict:
    import requests as req
    url = VERTEX_URL.format(project=GCP_PROJECT, model=model)
    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    for attempt in range(5):
        r = req.post(url, headers=hdrs, json=payload, timeout=timeout)
        if r.status_code == 429 or r.status_code >= 500:
            wait = 4 * (2 ** attempt)
            print(f"  HTTP {r.status_code} → retry {wait}s…")
            time.sleep(wait)
            token = _get_token()
            hdrs["Authorization"] = f"Bearer {token}"
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Max retries exceeded")


def _ocr_extract(response: dict) -> str:
    parts = response["candidates"][0]["content"].get("parts", [])
    return "\n".join(p.get("text", "") for p in parts if "text" in p)


def ocr_pdf(pdf_path: Path) -> str:
    import fitz
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]
    cache = CACHE_DIR / f"ocr_{digest}.txt"
    if cache.exists():
        print(f"  OCR cache hit → {cache}")
        return cache.read_text("utf-8")

    doc = fitz.open(str(pdf_path))
    total = doc.page_count
    mat = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
    print(f"  Rendering {total} pages at {RENDER_DPI} DPI…")
    pages_b64 = []
    for i in range(total):
        pix = doc[i].get_pixmap(matrix=mat)
        pages_b64.append(base64.b64encode(pix.tobytes("png")).decode())
        print(f"    {i+1}/{total}", end="\r")
    print()

    token = _get_token()
    chunks = []
    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)
        print(f"  OCR pages {start+1}–{end}/{total}…")
        imgs = [
            {"inlineData": {"mimeType": "image/png", "data": b}}
            for b in pages_b64[start:end]
        ]
        payload = {
            "contents": [{"role": "user", "parts": imgs + [{"text": OCR_PROMPT}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8192},
        }
        data = _post(MODEL_OCR, payload, token)
        chunks.append(f"[pages {start+1}–{end}]\n{_ocr_extract(data)}")
        time.sleep(DELAY)

    text = "\n\n".join(chunks)
    cache.write_text(text, "utf-8")
    print(f"  OCR done: {len(text):,} chars → {cache}")
    return text


# ── Словарь перевода (Ru → En) ────────────────────────────────────────────────
# Используется для поля name (English). Перевод пословный по ключевым словам.
_DICT: dict = {
    # Разделы / sections
    "функции": "Functions", "функция": "Function", "функций": "Functions",
    "уравнения": "Equations", "уравнение": "Equation", "уравнений": "Equations",
    "неравенства": "Inequalities", "неравенство": "Inequality", "неравенств": "Inequalities",
    "показательные": "Exponential", "показательная": "Exponential", "показательных": "Exponential",
    "логарифмические": "Logarithmic", "логарифмическая": "Logarithmic", "логарифм": "Logarithm",
    "логарифмических": "Logarithmic", "логарифмов": "Logarithms",
    "тригонометрия": "Trigonometry", "тригонометрические": "Trigonometric",
    "тригонометрических": "Trigonometric", "тригонометрическая": "Trigonometric",
    "вероятность": "Probability", "вероятности": "Probability", "вероятностей": "Probability",
    "статистика": "Statistics", "статистики": "Statistics",
    "прогрессии": "Progressions", "прогрессия": "Progression", "прогрессий": "Progressions",
    "интеграл": "Integral", "интегралы": "Integrals", "интегралов": "Integrals",
    "производная": "Derivative", "производной": "Derivative", "производные": "Derivatives",
    "предел": "Limit", "пределы": "Limits", "пределов": "Limits",
    "системы": "Systems", "система": "System", "систем": "Systems",
    "алгебра": "Algebra", "геометрия": "Geometry",
    "стереометрия": "Solid Geometry", "многогранники": "Polyhedra", "многогранник": "Polyhedron",
    "векторы": "Vectors", "вектор": "Vector",
    "комбинаторика": "Combinatorics",
    "матрицы": "Matrices",
    "начала": "Introduction to",
    "матанализа": "Calculus",
    "анализ": "Analysis",
    "данных": "Data",
    "данные": "Data",
    # Глаголы / verbs
    "классификация": "Classification", "классификации": "Classification",
    "определение": "Definition", "определения": "Definition",
    "вычисление": "Computing", "вычисления": "Computing",
    "нахождение": "Finding", "нахождения": "Finding",
    "распознавание": "Recognition",
    "построение": "Construction", "построения": "Construction",
    "проверка": "Checking",
    "решение": "Solving", "решения": "Solving",
    "исследование": "Investigation",
    "доказательство": "Proof",
    "сравнение": "Comparison",
    "применение": "Application",
    "использование": "Using",
    "преобразование": "Transformation", "преобразования": "Transformations",
    "упрощение": "Simplification",
    "разложение": "Factorization",
    "замена": "Substitution",
    # Существительные / nouns
    "понятие": "Concept",
    "область": "Domain",
    "множество": "Set", "значений": "of Values",
    "операции": "Operations",
    "свойства": "Properties", "свойство": "Property",
    "элементарные": "Elementary", "элементарных": "Elementary",
    "основы": "Basics", "основа": "Basis",
    "основные": "Basic", "основной": "Basic",
    "рациональные": "Rational", "рациональная": "Rational", "рациональных": "Rational",
    "иррациональные": "Irrational", "иррациональная": "Irrational",
    "квадратные": "Quadratic", "квадратная": "Quadratic",
    "линейные": "Linear", "линейная": "Linear",
    "непрерывность": "Continuity", "непрерывная": "Continuous",
    "разрывные": "Discontinuous", "разрывная": "Discontinuous",
    "сложная": "Composite", "сложных": "Composite",
    "обратная": "Inverse", "обратные": "Inverse", "обратных": "Inverse",
    "периодическая": "Periodic", "периодические": "Periodic",
    "первообразная": "Antiderivative", "первообразной": "Antiderivative",
    "тождественные": "Identity", "тождественных": "Identity",
    "тангенс": "Tangent", "синус": "Sine", "косинус": "Cosine",
    "производные": "Derivatives",
    "переменной": "of Variable", "переменную": "Variable",
    "по": "by", "частям": "Parts",
    "площадь": "Area",
    "криволинейной": "Curvilinear", "трапеции": "Trapezoid",
    "определённый": "Definite",
    "формула": "Formula", "формулы": "Formulas",
    "ньютона": "Newton", "лейбница": "Leibniz",
    "дифференциальные": "Differential", "дифференциальное": "Differential",
    "дифференциал": "Differential",
    "задачи": "Problems", "задача": "Problem",
    "максимум": "Maximum", "минимум": "Minimum",
    "экстремум": "Extremum",
    "возрастание": "Increase", "убывание": "Decrease",
    "монотонность": "Monotonicity",
    "приближённые": "Approximate", "вычисления": "Calculations",
    "теоремы": "Theorems", "теорема": "Theorem",
    "выпуклость": "Convexity",
    "асимптоты": "Asymptotes",
    "тейлора": "Taylor",
    "ряд": "Series", "ряды": "Series",
    "единственной": "Single", "критической": "Critical", "точкой": "Point",
    "касательной": "Tangent Line",
    "высших": "Higher", "порядков": "Order",
    "случайные": "Random", "события": "Events", "событий": "Events",
    "числовые": "Numerical",
    "характеристики": "Characteristics",
    "нули": "Zeros", "знакопостоянства": "Constant Sign",
    "промежутки": "Intervals",
    "чётность": "Evenness", "нечётность": "Oddness",
    "периодичность": "Periodicity",
    "ограниченность": "Boundedness",
    "односторонние": "One-sided",
    "взаимно": "Mutually",
    "суммы": "Sum", "разности": "Difference",
    "произведения": "Product", "частного": "Quotient",
    "последовательности": "Sequences",
    "геометрической": "Geometric", "геометрическая": "Geometric",
    "арифметической": "Arithmetic", "арифметическая": "Arithmetic",
    "бесконечно": "Infinitely", "убывающая": "Decreasing",
    "относительная": "Relative", "частота": "Frequency",
    "величин": "Variables", "величина": "Variable",
    "комбинаций": "Combinations", "перестановки": "Permutations",
    "степень": "Power", "степени": "Power",
    "корень": "Root",
    "натуральный": "Natural",
    "способы": "Ways", "задания": "of Defining",
    "теория": "Theory",
    "тела": "Solids", "вращения": "of Revolution",
    "примеры": "Examples", "использования": "of Using",
    "пределов": "of Limits",
    "непрерывности": "Continuity",
    "функций": "Functions",
    "графика": "of Graph", "графиков": "of Graphs", "графики": "Graphs",
    "модуля": "Absolute Value", "модулями": "Absolute Values",
    "арифметические": "Arithmetic",
}

# Коды для разделов (L1) — порядок важен: более специфичные ключи первыми
_SEC_CODES = {
    "показательн": "EXP",
    "логарифм": "LOG",
    "тригонометри": "TRIG",
    "уравнени": "EQ",
    "неравенств": "INEQ",
    "функци": "FUNC",
    "тригонометри": "TRIG",
    "вероятност": "PROB",
    "статистик": "STAT",
    "прогресси": "PROG",
    "геометри": "GEOM",
    "алгебр": "ALG",
    "стереометри": "STEREO",
    "многогранник": "POLY",
    "тела": "SOLIDS",
    "вектор": "VEC",
    "комбинаторик": "COMB",
    "интеграл": "INTEG",
    "производн": "DERIV",
    "предел": "LIM",
    "дифференциал": "DIFF",
    "матриц": "MAT",
    "данн": "DATA",
    "анализ": "ANAL",
}


def _make_code(name_ru: str) -> str:
    low = name_ru.lower()
    for key, code in _SEC_CODES.items():
        if key in low:
            return code
    words = re.findall(r"[а-яА-ЯёЁ]{3,}", name_ru)
    return words[0][:6].upper() if words else "SECT"


def _translate(text: str) -> str:
    """Word-by-word Russian→English translation using built-in dictionary."""
    result_parts = []
    # Split on spaces but keep punctuation attached to words
    for word in re.split(r"(\s+)", text):
        if not word.strip():
            result_parts.append(word)
            continue
        # Strip trailing punctuation for lookup
        clean = word.strip().lower().rstrip(".,;:!?)(")
        if clean in _DICT:
            result_parts.append(_DICT[clean])
        else:
            result_parts.append(word)
    result = "".join(result_parts)
    return re.sub(r"\s+", " ", result).strip()


# ── Модель данных ─────────────────────────────────────────────────────────────
@dataclass
class Skill:
    num: int
    name_ru: str
    example_task: str = ""
    assessed_ability: str = ""
    difficulty: str = "Medium (Level B)"
    formula: Optional[str] = None

    @property
    def name_en(self) -> str:
        return _translate(self.name_ru)

    @property
    def cognitive_type(self) -> str:
        mapping = {
            "Low (Level A)": "recall",
            "Medium (Level B)": "apply",
            "High (Level C)": "analyze",
            "High (Level C+)": "analyze",
            "High (Level B-C)": "analyze",
        }
        cog = mapping.get(self.difficulty, "apply")
        task_low = self.example_task.lower()
        if any(w in task_low for w in ("постройте", "составьте", "докажите", "создайте")):
            cog = "create"
        return cog


@dataclass
class Paragraph:
    local_num: int
    global_num: int
    name_ru: str
    skills: List[Skill] = field(default_factory=list)

    @property
    def name_en(self) -> str:
        return _translate(self.name_ru)


@dataclass
class Topic:
    num: int
    name_ru: str
    paragraphs: List[Paragraph] = field(default_factory=list)

    @property
    def name_en(self) -> str:
        return _translate(self.name_ru)


@dataclass
class Section:
    num: int
    name_ru: str
    topics: List[Topic] = field(default_factory=list)

    @property
    def name_en(self) -> str:
        return _translate(self.name_ru)

    @property
    def code(self) -> str:
        return _make_code(self.name_ru)


# ── Парсер ────────────────────────────────────────────────────────────────────
_ROMAN = {s: i for i, s in enumerate(
    ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"], 1
)}

# Регулярные выражения
RE_SEC   = re.compile(r"^Раздел\s+([IVXivx]+|\d+)\.\s+(.+)", re.IGNORECASE)
RE_TOPIC = re.compile(r"^Тема\s+(\d+)\.\s+(.+)", re.IGNORECASE)
RE_SKILL = re.compile(r"^Навык\s+(\d+)\.\s+(.+)", re.IGNORECASE)
RE_TASK  = re.compile(r"^Задача\s*:\s*(.*)", re.IGNORECASE)
RE_ABIL  = re.compile(r"^Проверяемое\s+умение\s*:\s*(.*)", re.IGNORECASE)
RE_DIFF  = re.compile(r"^Сложность\s*:\s*(.+)", re.IGNORECASE)
RE_FORM  = re.compile(r"^Формула\s*:\s*(.+)", re.IGNORECASE)
# Пункт: начинается с числа и точки, минимум 8 символов в названии
# Исключаем строки с → ≠ ≤ ≥ (правила-списки), строки без кириллицы
RE_PARA  = re.compile(r"^(\d+)\.\s+([А-ЯЁA-Z].{7,})", re.UNICODE)
RE_LIST  = re.compile(r"[→≠≤≥⇒]|^\d+\.\s+\d")   # признак list-item
RE_SKIP  = re.compile(r"^\[pages\s+|\bSardor\s+Bozorov\b", re.IGNORECASE)

NONE, TASK, ABIL = 0, 1, 2


def parse_ocr(text: str) -> List[Section]:
    sections: List[Section] = []
    cur_sec: Optional[Section] = None
    cur_topic: Optional[Topic] = None
    cur_para: Optional[Paragraph] = None
    cur_skill: Optional[Skill] = None
    global_para = 0      # количество найденных параграфов
    expected_num = 1     # ожидаемый ГЛОБАЛЬНЫЙ номер следующего параграфа
    state = NONE
    task_buf: List[str] = []
    abil_buf: List[str] = []

    def flush_skill():
        nonlocal cur_skill, task_buf, abil_buf, state
        if cur_skill is not None and cur_para is not None:
            if task_buf:
                cur_skill.example_task = " ".join(task_buf).strip()
            if abil_buf:
                cur_skill.assessed_ability = " ".join(abil_buf).strip()
            cur_para.skills.append(cur_skill)
        cur_skill = None
        task_buf.clear()
        abil_buf.clear()
        state = NONE

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            state = NONE
            continue
        if RE_SKIP.match(line):
            continue

        # ── Раздел ────────────────────────────────────────────────────────────
        m = RE_SEC.match(line)
        if m:
            flush_skill()
            n_str, name = m.group(1), m.group(2).strip()
            n = _ROMAN.get(n_str.upper(), 0) or int(n_str)
            sec = Section(num=n, name_ru=name)
            sections.append(sec)
            cur_sec = sec
            cur_topic = None
            cur_para = None
            state = NONE
            continue

        # ── Тема ──────────────────────────────────────────────────────────────
        m = RE_TOPIC.match(line)
        if m and cur_sec:
            flush_skill()
            topic = Topic(num=int(m.group(1)), name_ru=m.group(2).strip())
            cur_sec.topics.append(topic)
            cur_topic = topic
            cur_para = None
            state = NONE
            continue

        # ── Навык ─────────────────────────────────────────────────────────────
        m = RE_SKILL.match(line)
        if m and cur_topic:
            flush_skill()
            # Если не было явного пункта — создаём неявный
            if cur_para is None:
                global_para += 1
                cur_para = Paragraph(
                    local_num=1, global_num=global_para,
                    name_ru="General"
                )
                cur_topic.paragraphs.append(cur_para)
            cur_skill = Skill(num=int(m.group(1)), name_ru=m.group(2).strip())
            state = NONE
            continue

        # ── Задача ────────────────────────────────────────────────────────────
        m = RE_TASK.match(line)
        if m and cur_skill is not None:
            state = TASK
            first = m.group(1).strip()
            task_buf = [first] if first else []
            continue

        # ── Проверяемое умение ────────────────────────────────────────────────
        m = RE_ABIL.match(line)
        if m and cur_skill is not None:
            state = ABIL
            first = m.group(1).strip()
            abil_buf = [first] if first else []
            continue

        # ── Сложность ─────────────────────────────────────────────────────────
        m = RE_DIFF.match(line)
        if m and cur_skill is not None:
            cur_skill.difficulty = m.group(1).strip()
            state = NONE
            continue

        # ── Формула ───────────────────────────────────────────────────────────
        m = RE_FORM.match(line)
        if m and cur_skill is not None:
            cur_skill.formula = m.group(1).strip()
            state = NONE
            continue

        # ── Пункт (только когда не читаем многострочное поле) ────────────────
        m = RE_PARA.match(line)
        if m and cur_topic and state == NONE:
            num = int(m.group(1))
            name = m.group(2).strip()
            # Принимаем как параграф если:
            # 1. Номер >= ожидаемого (допускаем пробелы из-за OCR-пропусков)
            # 2. Малые числа (< expected) отклоняются — это шаги-методы "1. Выбрать..."
            # 3. Нет символов списка (→ ≠ ≤ ≥)
            if num >= expected_num and not RE_LIST.search(name):
                flush_skill()   # сохраняем текущий навык если есть
                global_para += 1
                para = Paragraph(
                    local_num=num,
                    global_num=global_para,
                    name_ru=name
                )
                cur_topic.paragraphs.append(para)
                cur_para = para
                expected_num = num + 1
                continue

        # ── Продолжение многострочных полей ───────────────────────────────────
        if state == TASK and cur_skill is not None:
            task_buf.append(line)
        elif state == ABIL and cur_skill is not None:
            abil_buf.append(line)

    flush_skill()
    return sections


# ── SQL-генератор ─────────────────────────────────────────────────────────────
def _q(s: Optional[str]) -> str:
    """Обернуть в SQL строку или вернуть NULL."""
    if s is None:
        return "NULL"
    return "'" + s.replace("'", "''") + "'"


def generate_sql(grade: int, sections: List[Section]) -> str:
    g = f"G{grade}"
    total_secs   = len(sections)
    total_topics = sum(len(s.topics) for s in sections)
    total_paras  = sum(len(t.paragraphs) for s in sections for t in s.topics)
    total_skills = sum(
        len(p.skills)
        for s in sections for t in s.topics for p in t.paragraphs
    )
    SEP = "-- " + "=" * 76

    out: List[str] = []

    # ── Шапка ─────────────────────────────────────────────────────────────────
    out += [
        SEP,
        f"-- ALGO V1 — СКЕЛЕТ {grade} КЛАСС (чистый методический файл)",
        f"-- Источник: Sardor Bozorov, PDF программа {grade} класса",
        f"-- {total_secs} разделов, {total_topics} тем, {total_paras} пунктов, {total_skills} атомарных навыков",
        SEP,
        "-- ФОРМАТ: Только поля методиста. ИИ-поля (importance, typical_time_seconds,",
        "-- irt_*, difficulty_score, weight, criticality) заполняются пайплайном.",
        "-- Prerequisites — будут сгенерированы AI-пайплайном",
        SEP,
        "",
        "-- Очистка",
        f"DELETE FROM tasks_master WHERE skill_id LIKE '{g}_%';",
        f"DELETE FROM knowledge_hierarchy WHERE id LIKE '{g}_%';",
        "",
    ]

    # ── L1: РАЗДЕЛЫ ───────────────────────────────────────────────────────────
    out += [SEP, f"-- L1: РАЗДЕЛЫ ({total_secs})", SEP]
    out.append("INSERT INTO knowledge_hierarchy "
               "(id, level, parent_id, name, name_ru, class_level_start, class_level_end, sequence_order)")
    out.append("VALUES")
    l1_rows = []
    for sec in sections:
        sid = f"{g}_{sec.code}"
        l1_rows.append(
            f"    ({_q(sid)}, 'L1', NULL, {_q(sec.name_en)}, {_q(sec.name_ru)}, {grade}, {grade}, {sec.num})"
        )
    out.append(",\n".join(l1_rows) + ";")
    out.append("")

    # ── L2: ТЕМЫ ──────────────────────────────────────────────────────────────
    out += [SEP, f"-- L2: ТЕМЫ ({total_topics})", SEP]
    out.append("INSERT INTO knowledge_hierarchy "
               "(id, level, parent_id, name, name_ru, class_level_start, class_level_end, sequence_order)")
    out.append("VALUES")
    l2_rows = []
    topic_ids: dict = {}
    t_seq = 0
    prev_sec_code = None
    for sec in sections:
        sid = f"{g}_{sec.code}"
        for topic in sec.topics:
            t_seq += 1
            tid = f"{g}_T{t_seq:02d}"
            topic_ids[id(topic)] = tid
            l2_rows.append(
                f"    ({_q(tid)}, 'L2', {_q(sid)}, {_q(topic.name_en)}, {_q(topic.name_ru)}, {grade}, {grade}, {t_seq})"
            )
    out.append(",\n".join(l2_rows) + ";")
    out.append("")

    # ── L3: ПУНКТЫ ────────────────────────────────────────────────────────────
    out += [SEP, f"-- L3: ПУНКТЫ ({total_paras})", SEP]
    out.append("INSERT INTO knowledge_hierarchy "
               "(id, level, parent_id, name, name_ru, class_level_start, class_level_end, sequence_order)")
    out.append("VALUES")
    l3_rows = []
    para_ids: dict = {}
    p_seq = 0
    prev_tid = None
    for sec in sections:
        for topic in sec.topics:
            tid = topic_ids[id(topic)]
            for para in topic.paragraphs:
                p_seq += 1
                pid = f"{g}_P{p_seq:02d}"
                para_ids[id(para)] = pid
                comment = ""
                if tid != prev_tid:
                    prev_tid = tid
                l3_rows.append(
                    f"    ({_q(pid)}, 'L3', {_q(tid)}, {_q(para.name_en)}, {_q(para.name_ru)}, {grade}, {grade}, {p_seq})"
                )
    out.append(",\n".join(l3_rows) + ";")
    out.append("")

    # ── L4: АТОМАРНЫЕ НАВЫКИ ─────────────────────────────────────────────────
    out += [
        SEP,
        f"-- L4: АТОМАРНЫЕ НАВЫКИ ({total_skills})",
        "-- Каждый навык содержит: example_task, assessed_ability, difficulty_level, formula из PDF",
        SEP,
    ]
    p_display = 0
    for sec in sections:
        for topic in sec.topics:
            for para in topic.paragraphs:
                p_display += 1
                if not para.skills:
                    continue
                pid = para_ids[id(para)]
                n = len(para.skills)
                out.append(f"\n-- ─── П.{p_display}: {para.name_ru} ({n} навыков) ───")
                out.append(
                    "INSERT INTO knowledge_hierarchy "
                    "(id, level, parent_id, name, name_ru, description, sequence_order, "
                    "cognitive_type, class_level_start, class_level_end, "
                    "example_task, assessed_ability, difficulty_level, formula)"
                )
                out.append("VALUES")
                skill_rows = []
                for idx, skill in enumerate(para.skills, 1):
                    sid = f"{g}_S{p_display:02d}_{idx:02d}"
                    desc = skill.example_task[:100] if skill.example_task else skill.name_ru
                    skill_rows.append(
                        f"({_q(sid)},'L4',{_q(pid)},"
                        f"{_q(skill.name_en)},{_q(skill.name_ru)},{_q(desc)},"
                        f"{idx},'{skill.cognitive_type}',{grade},{grade},\n"
                        f" {_q(skill.example_task)},{_q(skill.assessed_ability)},"
                        f"{_q(skill.difficulty)},{_q(skill.formula)})"
                    )
                out.append(",\n".join(skill_rows) + ";")

    out.append("")
    return "\n".join(out)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Usage: python3 parse_curriculum.py <grade> [pdf_path]")
        sys.exit(1)

    grade = int(sys.argv[1])
    named_cache = CACHE_DIR / f"grade{grade}_ocr.txt"
    out_path = OUT_DIR / f"grade_{grade:02d}_clean.sql"

    print(f"\n{'='*60}")
    print(f"  Grade {grade} — чистый Python парсер (без LLM для SQL)")
    print(f"  Output: {out_path}")
    print(f"{'='*60}\n")

    # 1. Получить OCR текст
    if named_cache.exists():
        print(f"[1/3] OCR из кэша: {named_cache}")
        ocr_text = named_cache.read_text("utf-8")
        print(f"  {len(ocr_text):,} символов\n")
    elif len(sys.argv) >= 3:
        pdf_path = Path(sys.argv[2])
        if not pdf_path.is_absolute():
            pdf_path = Path.cwd() / pdf_path
        if not pdf_path.exists():
            print(f"ERROR: PDF not found: {pdf_path}")
            sys.exit(1)
        print(f"[1/3] OCR через Gemini Vision: {pdf_path.name}")
        ocr_text = ocr_pdf(pdf_path)
        named_cache.write_text(ocr_text, "utf-8")
        print(f"  {len(ocr_text):,} символов\n")
    else:
        print(f"ERROR: Нет кэша для grade {grade}.")
        print(f"       Запустите: python3 parse_curriculum.py {grade} \"<PDF файл>\"")
        sys.exit(1)

    # 2. Парсинг
    print("[2/3] Парсинг структуры…")
    sections = parse_ocr(ocr_text)
    total_secs   = len(sections)
    total_topics = sum(len(s.topics) for s in sections)
    total_paras  = sum(len(t.paragraphs) for s in sections for t in s.topics)
    total_skills = sum(
        len(p.skills)
        for s in sections for t in s.topics for p in t.paragraphs
    )
    print(f"  Найдено: {total_secs} разделов, {total_topics} тем, "
          f"{total_paras} пунктов, {total_skills} навыков\n")

    # Показать структуру
    for sec in sections:
        print(f"  [{sec.code}] {sec.name_ru}")
        for topic in sec.topics:
            paras = len(topic.paragraphs)
            skills = sum(len(p.skills) for p in topic.paragraphs)
            print(f"      Тема {topic.num}: {topic.name_ru}  ({paras} пунктов, {skills} навыков)")

    if total_secs == 0:
        print("\nERROR: Разделы не найдены. Проверьте формат OCR текста.")
        sys.exit(1)

    print()

    # 3. Генерация SQL
    print("[3/3] Генерация SQL…")
    sql = generate_sql(grade, sections)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(sql, "utf-8")

    inserts = sql.count("INSERT INTO")
    print(f"\n{'='*60}")
    print(f"  ✓ Written: {out_path}")
    print(f"  {inserts} INSERTs  {len(sql):,} символов")
    print(f"  {total_secs} L1 → {total_topics} L2 → {total_paras} L3 → {total_skills} L4")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
