#!/usr/bin/env python3
"""
enrich_curriculum.py — AI-пайплайн обогащения учебного плана

Фазы:
  A. importance (1-10)   — педагогический вес каждого L3 параграфа
  B. cognitive_type      — преобладающий тип по таксономии Блума для L3
  C. prerequisites       — зависимости между L3 параграфами
                           (внутриклассные + межклассные)

Использует Gemini 3.1 Pro Preview через Vertex AI.

Использование:
  python3 scripts/enrich_curriculum.py --grade 10
  python3 scripts/enrich_curriculum.py --grade 11
  python3 scripts/enrich_curriculum.py --cross-grade 9 10
  python3 scripts/enrich_curriculum.py --cross-grade 10 11
  python3 scripts/enrich_curriculum.py --dry-run --grade 10
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

# ── Конфигурация ──────────────────────────────────────────────────────────────
GCP_PROJECT = "algo-495713"
MODEL       = "gemini-2.5-pro"
VERTEX_URL  = (
    "https://us-central1-aiplatform.googleapis.com/v1/projects/{project}/"
    "locations/us-central1/publishers/google/models/{model}:generateContent"
)
DB_CONTAINER = "content-postgres"
DB_USER      = "algo"
DB_NAME      = "algo_content"
DELAY        = 5.0   # секунд между API вызовами
MAX_RETRIES  = 4


# ── DB helpers ────────────────────────────────────────────────────────────────
def db_query(sql: str) -> list[dict]:
    """Выполняет SELECT через psql, возвращает list of dicts."""
    cmd = [
        "docker", "exec", DB_CONTAINER,
        "psql", "-U", DB_USER, "-d", DB_NAME,
        "--csv", "-c", sql
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"psql error: {result.stderr}")
    lines = [l for l in result.stdout.strip().splitlines() if l]
    if not lines:
        return []
    import csv
    reader = csv.DictReader(lines)
    return list(reader)


def db_exec(sql: str) -> str:
    """Выполняет DML через psql, возвращает вывод."""
    cmd = [
        "docker", "exec", "-i", DB_CONTAINER,
        "psql", "-U", DB_USER, "-d", DB_NAME, "-c", sql
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    out = result.stdout + result.stderr
    if "ERROR" in out:
        raise RuntimeError(f"psql DML error:\n{out}")
    return out


def db_exec_file(sql_content: str) -> str:
    """Выполняет SQL из stdin через psql."""
    cmd = [
        "docker", "exec", "-i", DB_CONTAINER,
        "psql", "-U", DB_USER, "-d", DB_NAME
    ]
    result = subprocess.run(
        cmd, input=sql_content, capture_output=True, text=True, timeout=60
    )
    out = result.stdout + result.stderr
    return out


# ── Vertex AI helpers ─────────────────────────────────────────────────────────
_token_cache: dict = {"token": None, "expires": 0}


def _get_token() -> str:
    import time as t
    if _token_cache["token"] and t.time() < _token_cache["expires"]:
        return _token_cache["token"]
    import warnings
    warnings.filterwarnings("ignore")
    import google.auth
    import google.auth.transport.requests
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    _token_cache["token"] = creds.token
    _token_cache["expires"] = t.time() + 3300  # 55 минут
    return creds.token


def gemini(prompt: str, temperature: float = 0.15) -> str:
    """Вызывает Gemini Flash, возвращает текст ответа."""
    import requests as req
    url = VERTEX_URL.format(project=GCP_PROJECT, model=MODEL)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }
    for attempt in range(MAX_RETRIES):
        token = _get_token()
        hdrs = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            r = req.post(url, headers=hdrs, json=payload, timeout=240)
            if r.status_code in (429, 500, 503):
                wait = 8 * (2 ** attempt)
                print(f"    HTTP {r.status_code} → retry {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            parts = data["candidates"][0]["content"].get("parts", [])
            return "".join(p.get("text", "") for p in parts if "text" in p)
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            print(f"    Error: {e} → retry")
            time.sleep(8 * (2 ** attempt))
    raise RuntimeError("Max retries exceeded")


def parse_json(text: str) -> Any:
    """Парсит JSON из ответа Gemini (снимает ```json``` обёртку если есть)."""
    text = text.strip()
    # Снимаем markdown-блок если есть
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    # Ищем первый JSON объект
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    return json.loads(text)


# ── Загрузка данных из БД ────────────────────────────────────────────────────
def load_skills(grade: int) -> list[dict]:
    """Загружает все L4 навыки класса с их L3/L2 контекстом."""
    sql = f"""
SELECT
  l4.id, l4.name_ru, l4.example_task, l4.assessed_ability,
  l4.difficulty_level, l4.cognitive_type, l4.importance, l4.sequence_order,
  l3.id as para_id, l3.name_ru as para_name, l3.sequence_order as para_seq,
  l2.id as topic_id, l2.name_ru as topic_name
FROM knowledge_hierarchy l4
JOIN knowledge_hierarchy l3 ON l3.id = l4.parent_id
JOIN knowledge_hierarchy l2 ON l2.id = l3.parent_id
WHERE l4.level = 'L4' AND l4.id LIKE 'G{grade}_%'
ORDER BY l2.sequence_order, l3.sequence_order, l4.sequence_order
"""
    return db_query(sql.strip())


def load_paragraphs(grade: int) -> list[dict]:
    """Загружает все L3 параграфы класса с контекстом."""
    sql = f"""
SELECT
  l3.id, l3.name_ru, l3.sequence_order,
  l2.id as topic_id, l2.name_ru as topic_name,
  l1.id as section_id, l1.name_ru as section_name,
  (SELECT count(*) FROM knowledge_hierarchy
   WHERE parent_id=l3.id AND level='L4') as skill_count
FROM knowledge_hierarchy l3
JOIN knowledge_hierarchy l2 ON l2.id = l3.parent_id
JOIN knowledge_hierarchy l1 ON l1.id = l2.parent_id
WHERE l3.level = 'L3' AND l3.id LIKE 'G{grade}_%'
ORDER BY l3.sequence_order
"""
    return db_query(sql.strip())


def load_existing_prereqs(skill_id: str) -> set[str]:
    """Возвращает множество уже существующих prerequisite_id для skill_id."""
    rows = db_query(
        f"SELECT prerequisite_id FROM skill_prerequisites WHERE skill_id='{skill_id}'"
    )
    return {r["prerequisite_id"] for r in rows}


def load_all_existing_prereq_pairs() -> set[tuple[str, str]]:
    """Возвращает все существующие (skill_id, prerequisite_id) пары."""
    rows = db_query("SELECT skill_id, prerequisite_id FROM skill_prerequisites")
    return {(r["skill_id"], r["prerequisite_id"]) for r in rows}


# ── Фаза A+B: importance + cognitive_type для L3 параграфов ──────────────────
IMPORTANCE_PROMPT = """
Ты эксперт по казахстанской учебной программе математики (5-11 класс, учебники Sardor Bozorov).

Проанализируй параграфы (L3) одной ТЕМЫ и для каждого параграфа определи:

1. importance (integer 1-10) — педагогический вес параграфа:
   - 9-10: Фундаментальный раздел. Без него невозможно дальнейшее обучение.
           Часто в ЕНТ/СОЧ. На нём строятся следующие темы.
   - 7-8:  Ключевой раздел. Важен для последующего материала и экзаменов.
   - 5-6:  Стандартный раздел учебной программы.
   - 3-4:  Вспомогательный или углублённый материал.
   - 1-2:  Периферийный, редко проверяется на экзаменах.

2. cognitive_type — преобладающий тип задач параграфа (строго одно из):
   "recall"  — определения, формулы, факты (воспроизведение)
   "apply"   — применение алгоритмов к типовым задачам
   "analyze" — сравнение, интерпретация, многошаговые рассуждения
   "create"  — доказательства, нестандартные задачи, моделирование

Правила:
- Первые параграфы темы обычно более фундаментальны (+1 к importance)
- Тема "Функции", "Уравнения", "Тригонометрия" — высокий приоритет ЕНТ
- cognitive_type — для ВСЕГО параграфа в целом, не отдельных навыков

Класс: {grade}
Тема: {topic_name}

Параграфы:
{paras_text}

Верни ТОЛЬКО JSON:
{{
  "paragraphs": {{
    "<para_id>": {{"importance": <int 1-10>, "cognitive_type": "<recall|apply|analyze|create>"}},
    ...
  }}
}}
""".strip()


def enrich_importance_cogtype(grade: int, dry_run: bool = False) -> None:
    """Фаза A+B: заполняет importance и cognitive_type для L3 параграфов."""
    print(f"\n{'='*60}")
    print(f"  Фаза A+B: importance + cognitive_type L3  [Grade {grade}]")
    print(f"{'='*60}")

    paras = load_paragraphs(grade)
    if not paras:
        print(f"  ERROR: Нет L3 параграфов для класса {grade}")
        return

    # Группируем по темам (L2)
    from collections import OrderedDict
    by_topic: dict = OrderedDict()
    for p in paras:
        tid = p["topic_id"]
        if tid not in by_topic:
            by_topic[tid] = {"name": p["topic_name"], "paras": []}
        by_topic[tid]["paras"].append(p)

    all_updates: list[str] = []

    for tid, tdata in by_topic.items():
        tname = tdata["name"]
        tparas = tdata["paras"]
        n = len(tparas)
        print(f"\n  Тема: {tname}  ({n} параграфов)")

        paras_text = build_paras_text(tparas)
        prompt = IMPORTANCE_PROMPT.format(
            grade=grade,
            topic_name=tname,
            paras_text=paras_text,
        )

        for attempt in range(3):
            try:
                raw = gemini(prompt)
                data = parse_json(raw)
                break
            except Exception as e:
                print(f"    Parse error attempt {attempt+1}: {e}")
                if attempt == 2:
                    print(f"    SKIP topic {tid}")
                    data = {}
                time.sleep(4)
        else:
            data = {}

        para_updates = data.get("paragraphs", {})
        ok = 0
        for pid, vals in para_updates.items():
            imp = vals.get("importance")
            cog = vals.get("cognitive_type")
            if not isinstance(imp, int) or not (1 <= imp <= 10):
                print(f"    WARN: invalid importance {imp} for {pid}")
                imp = 5
            if cog not in ("recall", "apply", "analyze", "create"):
                print(f"    WARN: invalid cognitive_type '{cog}' for {pid}")
                cog = None
            sql = (
                f"UPDATE knowledge_hierarchy SET importance={imp}"
                + (f", cognitive_type='{cog}'" if cog else "")
                + f" WHERE id='{pid}' AND level='L3';"
            )
            all_updates.append(sql)
            ok += 1
        print(f"    → {ok}/{n} параграфов обработано")
        time.sleep(DELAY)

    if not all_updates:
        print("  Нет обновлений для применения")
        return

    sql_block = "\n".join(all_updates)
    print(f"\n  Итого UPDATE: {len(all_updates)} строк")

    if dry_run:
        print("  [dry-run] SQL НЕ применяется. Пример:")
        print("\n".join(all_updates[:5]))
        return

    out = db_exec_file(sql_block)
    errors = [l for l in out.splitlines() if "ERROR" in l]
    if errors:
        print(f"  ERRORS: {errors}")
    else:
        print(f"  ✓ Применено успешно")


# ── Фаза C: Prerequisites ─────────────────────────────────────────────────────
PREREQ_PROMPT = """
Ты эксперт по казахстанской учебной программе математики.

Определи зависимости между параграфами (L3) учебного плана.
Формат соответствует уже существующим зависимостям для 5-9 классов.

Правила:
- dependency_type "hard": навык физически невозможно выполнить без знания пред. параграфа
- dependency_type "soft": без пред. параграфа сложнее, но возможно
- criticality 9-10: абсолютно необходимо
- criticality 7-8: очень важно
- criticality 5-6: полезно но не обязательно
- Не создавай зависимости между несвязанными темами
- Не создавай обратные зависимости (A→B, B→A)
- Каждый параграф может иметь 0-4 зависимости
- relationship_description: ОДНО конкретное предложение на РУССКОМ, почему зависимость существует

Класс: {grade}
Параграфы (в порядке последовательности):
{paras_text}

Верни ТОЛЬКО JSON:
{{
  "prerequisites": [
    {{
      "skill_id": "<para_id который ЗАВИСИТ>",
      "prerequisite_id": "<para_id который НУЖЕН ПЕРВЫМ>",
      "dependency_type": "hard|soft",
      "criticality": <int 7-10>,
      "relationship_description": "<одно предложение на русском>"
    }},
    ...
  ]
}}
""".strip()


CROSS_GRADE_PREREQ_PROMPT = """
Ты эксперт по казахстанской учебной программе математики.

Определи МЕЖКЛАССНЫЕ зависимости: какие параграфы класса {grade_hi}
напрямую зависят от параграфов класса {grade_lo}.

Только самые важные связи (criticality >= 8).
relationship_description: на русском, конкретно.

Параграфы {grade_lo} класса:
{paras_lo}

Параграфы {grade_hi} класса:
{paras_hi}

Верни ТОЛЬКО JSON:
{{
  "prerequisites": [
    {{
      "skill_id": "<G{grade_hi}_Pxx>",
      "prerequisite_id": "<G{grade_lo}_Pxx>",
      "dependency_type": "hard|soft",
      "criticality": <int 8-10>,
      "is_cross_grade": true,
      "relationship_description": "<одно предложение на русском>"
    }},
    ...
  ]
}}
""".strip()


def build_paras_text(paras: list[dict]) -> str:
    lines = []
    for p in paras:
        lines.append(
            f"- {p['id']}: \"{p['name_ru']}\" "
            f"[Тема: {p['topic_name']}, {p['skill_count']} навыков]"
        )
    return "\n".join(lines)


def _insert_prereqs(prereqs: list[dict], existing_pairs: set, dry_run: bool) -> int:
    """Вставляет пары пред. условий в БД. Возвращает кол-во вставленных."""
    inserts = []
    for pr in prereqs:
        sid  = pr.get("skill_id", "").strip()
        pid  = pr.get("prerequisite_id", "").strip()
        dtype = pr.get("dependency_type", "hard")
        crit  = pr.get("criticality", 8)
        desc  = pr.get("relationship_description", "").replace("'", "''")[:300]
        cross = pr.get("is_cross_grade", False)

        # Валидация
        if not sid or not pid or sid == pid:
            continue
        if dtype not in ("hard", "soft"):
            dtype = "hard"
        if not isinstance(crit, int) or not (1 <= crit <= 10):
            crit = 8
        if (sid, pid) in existing_pairs:
            continue  # уже существует

        existing_pairs.add((sid, pid))
        inserts.append(
            f"INSERT INTO skill_prerequisites "
            f"(skill_id, prerequisite_id, dependency_type, criticality, "
            f"is_cross_grade, relationship_description, discovery_source) VALUES "
            f"('{sid}','{pid}','{dtype}',{crit},"
            f"{'true' if cross else 'false'},"
            f"'{desc}','ai_gemini') "
            f"ON CONFLICT (skill_id, prerequisite_id) DO NOTHING;"
        )

    if not inserts:
        return 0

    if dry_run:
        print(f"    [dry-run] {len(inserts)} INSERTs (не применяется)")
        for s in inserts[:3]:
            print(f"      {s[:100]}…")
        return len(inserts)

    out = db_exec_file("\n".join(inserts))
    errors = [l for l in out.splitlines() if "ERROR" in l]
    if errors:
        print(f"    ERRORS: {errors[:3]}")
    return len(inserts)


def gen_prerequisites(grade: int, dry_run: bool = False) -> None:
    """Фаза C: генерирует внутриклассные пред. условия для класса."""
    print(f"\n{'='*60}")
    print(f"  Фаза C: prerequisites внутри Grade {grade}")
    print(f"{'='*60}")

    paras = load_paragraphs(grade)
    if not paras:
        print(f"  ERROR: Нет L3 параграфов для класса {grade}")
        return

    existing_pairs = load_all_existing_prereq_pairs()
    print(f"  Параграфов: {len(paras)}  |  Существующих пар: {len(existing_pairs)}")

    # Обрабатываем по темам для лучшего контекста
    from collections import defaultdict, OrderedDict
    by_topic: dict = OrderedDict()
    for p in paras:
        tid = p["topic_id"]
        if tid not in by_topic:
            by_topic[tid] = {"name": p["topic_name"], "paras": []}
        by_topic[tid]["paras"].append(p)

    total_inserted = 0

    for tid, tdata in by_topic.items():
        tname = tdata["name"]
        tparas = tdata["paras"]
        if len(tparas) < 2:
            print(f"\n  Тема {tname}: пропуск (только 1 параграф)")
            continue

        # Добавляем пару соседних параграфов из других тем для контекста
        print(f"\n  Тема: {tname}  ({len(tparas)} параграфов)")

        paras_text = build_paras_text(tparas)
        prompt = PREREQ_PROMPT.format(
            grade=grade,
            paras_text=paras_text
        )

        for attempt in range(3):
            try:
                raw = gemini(prompt)
                data = parse_json(raw)
                break
            except Exception as e:
                print(f"    Parse error attempt {attempt+1}: {e}")
                if attempt == 2:
                    data = {"prerequisites": []}
                time.sleep(4)

        prereqs = data.get("prerequisites", [])
        inserted = _insert_prereqs(prereqs, existing_pairs, dry_run)
        print(f"    → {inserted} новых пар добавлено")
        total_inserted += inserted
        time.sleep(DELAY)

    print(f"\n  ✓ Итого вставлено: {total_inserted} пар prerequisite")


def gen_cross_grade_prereqs(grade_lo: int, grade_hi: int, dry_run: bool = False) -> None:
    """Фаза C (cross): межклассные зависимости grade_lo → grade_hi."""
    print(f"\n{'='*60}")
    print(f"  Фаза C (cross): G{grade_lo} → G{grade_hi} prerequisites")
    print(f"{'='*60}")

    paras_lo = load_paragraphs(grade_lo)
    paras_hi = load_paragraphs(grade_hi)
    existing_pairs = load_all_existing_prereq_pairs()

    print(f"  G{grade_lo}: {len(paras_lo)} параграфов | G{grade_hi}: {len(paras_hi)} параграфов")

    # Разбиваем на батчи: 15 параграфов lo × 15 параграфов hi
    # Берём последние N из grade_lo и первые N из grade_hi
    BATCH = 18

    # Для перекрёстных связей берём срезы: конец lo + начало hi,
    # потом по разделам
    from collections import defaultdict
    hi_by_section: dict = defaultdict(list)
    for p in paras_hi:
        hi_by_section[p["section_id"]].append(p)

    lo_by_section: dict = defaultdict(list)
    for p in paras_lo:
        lo_by_section[p["section_id"]].append(p)

    total_inserted = 0

    # Вызов 1: последние параграфы lo + все параграфы hi
    paras_lo_tail = paras_lo[-BATCH:]
    paras_hi_head = paras_hi[:BATCH]

    prompt = CROSS_GRADE_PREREQ_PROMPT.format(
        grade_lo=grade_lo,
        grade_hi=grade_hi,
        paras_lo=build_paras_text(paras_lo_tail),
        paras_hi=build_paras_text(paras_hi_head)
    )

    print(f"\n  Батч 1: {len(paras_lo_tail)} lo-параграфов × {len(paras_hi_head)} hi-параграфов")
    for attempt in range(3):
        try:
            raw = gemini(prompt, temperature=0.1)
            data = parse_json(raw)
            break
        except Exception as e:
            print(f"    Parse error attempt {attempt+1}: {e}")
            if attempt == 2:
                data = {"prerequisites": []}
            time.sleep(4)

    prereqs = data.get("prerequisites", [])
    # Принудительно ставим is_cross_grade=True
    for pr in prereqs:
        pr["is_cross_grade"] = True
    inserted = _insert_prereqs(prereqs, existing_pairs, dry_run)
    print(f"  → {inserted} новых межклассных пар (батч 1)")
    total_inserted += inserted
    time.sleep(DELAY)

    # Вызов 2: все lo + оставшиеся hi
    if len(paras_hi) > BATCH:
        paras_hi_rest = paras_hi[BATCH:]
        paras_lo_all  = paras_lo[-BATCH:]

        prompt2 = CROSS_GRADE_PREREQ_PROMPT.format(
            grade_lo=grade_lo,
            grade_hi=grade_hi,
            paras_lo=build_paras_text(paras_lo_all),
            paras_hi=build_paras_text(paras_hi_rest)
        )

        print(f"\n  Батч 2: {len(paras_lo_all)} lo × {len(paras_hi_rest)} hi")
        for attempt in range(3):
            try:
                raw = gemini(prompt2, temperature=0.1)
                data = parse_json(raw)
                break
            except Exception as e:
                print(f"    Parse error attempt {attempt+1}: {e}")
                if attempt == 2:
                    data = {"prerequisites": []}
                time.sleep(4)

        prereqs2 = data.get("prerequisites", [])
        for pr in prereqs2:
            pr["is_cross_grade"] = True
        inserted2 = _insert_prereqs(prereqs2, existing_pairs, dry_run)
        print(f"  → {inserted2} новых межклассных пар (батч 2)")
        total_inserted += inserted2
        time.sleep(DELAY)

    print(f"\n  ✓ Итого вставлено cross-grade: {total_inserted} пар")


# ── Верификация ───────────────────────────────────────────────────────────────
def verify(grade: Optional[int] = None) -> None:
    """Выводит финальную сводку после всех фаз."""
    grade_sql = f"AND class_level_start={grade}" if grade else ""

    print(f"\n{'='*60}")
    print("  ФИНАЛЬНАЯ СВОДКА")
    print(f"{'='*60}")

    print("\n  L3 параграфы по классу:")
    for r in db_query(f"""
SELECT class_level_start as grade,
  count(*) as paragraphs,
  round(avg(importance),1) as avg_imp,
  min(importance) as min_imp, max(importance) as max_imp,
  sum(CASE WHEN importance=5 THEN 1 ELSE 0 END) as still_default,
  string_agg(DISTINCT cognitive_type, ', ' ORDER BY cognitive_type) as cog_types
FROM knowledge_hierarchy
WHERE level='L3' AND id LIKE 'G%' {grade_sql}
GROUP BY class_level_start ORDER BY class_level_start
"""):
        default_warn = f"  ⚠ {r['still_default']} с default!" if int(r['still_default']) > 0 else ""
        print(f"    G{r['grade']}: {r['paragraphs']} параграфов | "
              f"importance avg={r['avg_imp']} [{r['min_imp']}-{r['max_imp']}]{default_warn} | "
              f"cog: {r['cog_types']}")

    print("\n  Prerequisites по классу:")
    for r in db_query("""
SELECT
  substring(skill_id,1,3) as grd,
  count(*) as prereqs,
  sum(CASE WHEN is_cross_grade THEN 1 ELSE 0 END) as cross_grade,
  sum(CASE WHEN discovery_source='ai_gemini' THEN 1 ELSE 0 END) as ai_generated
FROM skill_prerequisites
GROUP BY substring(skill_id,1,3)
ORDER BY grd
"""):
        print(f"    {r['grd']}: {r['prereqs']} пар "
              f"({r['cross_grade']} cross-grade, "
              f"{r['ai_generated']} AI-generated)")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Enrich curriculum: importance, cognitive_type, prerequisites"
    )
    parser.add_argument("--grade", type=int, help="Grade to process (10 or 11)")
    parser.add_argument("--cross-grade", type=int, nargs=2, metavar=("FROM", "TO"),
                        help="Generate cross-grade prerequisites (e.g. 9 10)")
    parser.add_argument("--phase", choices=["ab", "c", "all"], default="all",
                        help="ab=importance+cogtype, c=prerequisites, all=both")
    parser.add_argument("--dry-run", action="store_true",
                        help="Показать SQL без применения к БД")
    parser.add_argument("--verify", action="store_true",
                        help="Только вывести сводку, ничего не менять")
    args = parser.parse_args()

    if args.verify:
        verify(args.grade)
        return

    if args.cross_grade:
        grade_lo, grade_hi = args.cross_grade
        gen_cross_grade_prereqs(grade_lo, grade_hi, dry_run=args.dry_run)
        verify(grade_hi)
        return

    if args.grade is None:
        parser.error("Укажи --grade или --cross-grade")

    grade = args.grade
    phase = args.phase
    dry   = args.dry_run

    if phase in ("ab", "all"):
        enrich_importance_cogtype(grade, dry_run=dry)

    if phase in ("c", "all"):
        gen_prerequisites(grade, dry_run=dry)

    verify(grade)


if __name__ == "__main__":
    main()
