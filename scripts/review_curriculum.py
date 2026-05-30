#!/usr/bin/env python3
"""
review_curriculum.py — комплексная AI-оценка базы знаний (G5-G11)

Загружает из БД:
  - importance, cognitive_type для всех L3 параграфов (используются алгоритмом)
  - все skill_prerequisites (внутриклассные + межклассные)

Отправляет в Gemini 3.1 Pro Preview и получает:
  - оценку качества importance L3 (1-10)
  - оценку полноты/точности prerequisites
  - конкретные проблемы и рекомендации
  - итоговый score с комментарием

Использование:
  python3 scripts/review_curriculum.py
  python3 scripts/review_curriculum.py --grade 10
"""

import argparse
import json
import re
import subprocess
import sys
import time
from typing import Optional
import csv as _csv

# ── Конфиг ───────────────────────────────────────────────────────────────────
GCP_PROJECT  = "algo-495713"
MODEL        = "gemini-2.5-pro"
VERTEX_URL   = (
    "https://us-central1-aiplatform.googleapis.com/v1/projects/{project}/"
    "locations/us-central1/publishers/google/models/{model}:generateContent"
)
DB_CONTAINER = "content-postgres"
DB_USER      = "algo"
DB_NAME      = "algo_content"

# ── DB ───────────────────────────────────────────────────────────────────────
def db_query(sql: str) -> list[dict]:
    cmd = [
        "docker", "exec", DB_CONTAINER,
        "psql", "-U", DB_USER, "-d", DB_NAME,
        "--csv", "-c", sql
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    lines = [l for l in r.stdout.strip().splitlines() if l]
    if not lines:
        return []
    return list(_csv.DictReader(lines))


# ── Vertex AI ─────────────────────────────────────────────────────────────────
_tok: dict = {"v": None, "exp": 0}

def _token() -> str:
    import time as t
    if _tok["v"] and t.time() < _tok["exp"]:
        return _tok["v"]
    import warnings; warnings.filterwarnings("ignore")
    import google.auth, google.auth.transport.requests
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    _tok["v"] = creds.token
    _tok["exp"] = t.time() + 3300
    return creds.token

def gemini_pro(prompt: str) -> str:
    import requests as req
    url = VERTEX_URL.format(project=GCP_PROJECT, model=MODEL)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 16384,
            "responseMimeType": "application/json",
        },
    }
    for attempt in range(4):
        hdrs = {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}
        try:
            r = req.post(url, headers=hdrs, json=payload, timeout=240)
            if r.status_code in (429, 500, 503):
                wait = 15 * (2 ** attempt)
                print(f"  HTTP {r.status_code} → retry {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"].get("parts", [])
            return "".join(p.get("text", "") for p in parts)
        except Exception as e:
            print(f"  Error attempt {attempt+1}: {e}")
            if attempt == 3:
                raise
            time.sleep(15)
    raise RuntimeError("max retries")

def parse_json(text: str) -> dict:
    text = text.strip()
    # strip markdown code fences
    m = re.search(r"```(?:json)?\s*(\{.*)", text, re.DOTALL)
    if m:
        text = m.group(1)
        text = re.sub(r"```\s*$", "", text).strip()
    # find start of first JSON object
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found")
    text = text[start:]
    # use raw_decode to parse only the first valid JSON object (ignores trailing data)
    obj, _ = json.JSONDecoder().raw_decode(text)
    return obj


# ── Загрузка данных ───────────────────────────────────────────────────────────
def load_curriculum_summary(grade_filter: str = "") -> str:
    """Строит текстовую сводку curriculum для передачи в модель."""
    where = f"AND class_level_start={grade_filter}" if grade_filter else ""

    # L3 paragraphs: importance + cognitive_type (используются диагностическим алгоритмом)
    paras = db_query(f"""
SELECT l3.id, l3.name_ru, l3.importance, l3.cognitive_type,
  l2.id as topic_id, l2.name_ru as topic_name,
  l1.id as section_id
FROM knowledge_hierarchy l3
JOIN knowledge_hierarchy l2 ON l2.id=l3.parent_id
JOIN knowledge_hierarchy l1 ON l1.id=l2.parent_id
WHERE l3.level='L3' AND l3.id LIKE 'G%' {where.replace("class_level_start", "l3.class_level_start")}
ORDER BY l3.class_level_start, l2.sequence_order, l3.sequence_order
""")

    # Prerequisites (skill_id и prerequisite_id — это L3 идентификаторы)
    prereqs = db_query(f"""
SELECT sp.skill_id, sp.prerequisite_id, sp.dependency_type,
  sp.criticality, sp.is_cross_grade, sp.relationship_description
FROM skill_prerequisites sp
JOIN knowledge_hierarchy kh ON kh.id=sp.skill_id
WHERE kh.id LIKE 'G%' {where.replace("class_level_start", "kh.class_level_start")}
ORDER BY sp.skill_id, sp.prerequisite_id
""")

    # Строим текст
    lines = ["# Учебный план по математике G5-G11 (Kazakhstan) — L3 параграфы\n"]
    lines.append("ВАЖНО: importance и cognitive_type заданы на уровне L3 параграфов.")
    lines.append("Importance L3 используется алгоритмом: если failing paragraph importance >= threshold → deep scan.\n")

    from collections import defaultdict, OrderedDict, Counter

    by_para_grade: dict = defaultdict(list)
    for p in paras:
        grade_num = int(re.search(r"G(\d+)_", p["id"]).group(1))
        by_para_grade[grade_num].append(p)

    by_prereq_grade: dict = defaultdict(list)
    for pr in prereqs:
        grade_num = int(re.search(r"G(\d+)_", pr["skill_id"]).group(1))
        by_prereq_grade[grade_num].append(pr)

    for grade_num in sorted(by_para_grade.keys()):
        g_paras = by_para_grade[grade_num]
        g_prereqs = by_prereq_grade[grade_num]

        imp_vals = [int(p["importance"]) for p in g_paras]
        avg_imp = sum(imp_vals) / len(imp_vals) if imp_vals else 0
        enriched_count = sum(1 for v in imp_vals if v != 5)
        imp_dist = Counter(str(v) for v in imp_vals)
        cog_dist = Counter(p["cognitive_type"] for p in g_paras)

        lines.append(f"\n## Класс {grade_num}")
        lines.append(f"L3 параграфов: {len(g_paras)} | avg importance={avg_imp:.1f} | обогащено: {enriched_count}/{len(g_paras)}")
        lines.append("Importance распределение: " + ", ".join(f"{k}→{v}" for k,v in sorted(imp_dist.items())))
        lines.append("Cognitive types: " + ", ".join(f"{k}={v}" for k,v in sorted(cog_dist.items(), key=lambda x: -x[1])))

        # Все параграфы с importance + cogtype
        lines.append("Параграфы (id | importance | cogtype | название):")
        for p in g_paras:
            lines.append(f"  {p['id']} | imp={p['importance']} | {p['cognitive_type']} | {p['name_ru'][:60]}")

        # Prerequisites
        internal = [p for p in g_prereqs if p["is_cross_grade"] not in ("t","true","True","1")]
        cross = [p for p in g_prereqs if p["is_cross_grade"] in ("t","true","True","1")]
        lines.append(f"\nПрерквизиты: {len(internal)} внутриклассных + {len(cross)} межклассных")
        for pr in g_prereqs[:15]:
            cross_mark = "⟳" if pr["is_cross_grade"] in ("t","true","True","1") else " "
            desc = (pr["relationship_description"] or "")[:70]
            lines.append(
                f"  {cross_mark} {pr['skill_id']} ← {pr['prerequisite_id']} "
                f"[{pr['dependency_type']}, c={pr['criticality']}]: {desc}"
            )
        if len(g_prereqs) > 15:
            lines.append(f"  ... ещё {len(g_prereqs)-15} пар")

    return "\n".join(lines)


REVIEW_PROMPT = """
Ты — ведущий эксперт по педагогическому дизайну и математическому образованию (уровень K-12, СНГ).
Проведи профессиональный аудит базы знаний учебного плана по математике 5-11 класс Казахстана.

{curriculum_text}

---

КОНТЕКСТ СИСТЕМЫ:
Importance L3 используется диагностическим алгоритмом для принятия решения о deep scan:
- если importance failing paragraph >= threshold (обычно 7) → запускается глубокое сканирование
- поэтому importance должен ТОЧНО отражать значимость темы для ЕНТ и математической грамотности

Оцени следующие аспекты для ВСЕХ классов G5-G11 и верни ТОЛЬКО JSON:

{{
  "grades_importance": {{
    "G5": {{
      "score": <1-10>,
      "distribution_quality": "<плохо|приемлемо|хорошо|отлично>",
      "suspicious_low": ["<id параграфа который явно занижен>: <почему>"],
      "suspicious_high": ["<id параграфа который явно завышен>: <почему>"],
      "fixes": [{{"id": "G5_Pxx", "current": <N>, "suggested": <M>, "reason": "<почему>"}}]
    }},
    "G6": {{
      "score": <1-10>,
      "distribution_quality": "<плохо|приемлемо|хорошо|отлично>",
      "suspicious_low": ["..."],
      "suspicious_high": ["..."],
      "fixes": [{{"id": "G6_Pxx", "current": <N>, "suggested": <M>, "reason": "<почему>"}}]
    }},
    "G7": {{
      "score": <1-10>,
      "distribution_quality": "<плохо|приемлемо|хорошо|отлично>",
      "suspicious_low": ["..."],
      "suspicious_high": ["..."],
      "fixes": [{{"id": "G7_Pxx", "current": <N>, "suggested": <M>, "reason": "<почему>"}}]
    }},
    "G8": {{
      "score": <1-10>,
      "distribution_quality": "<плохо|приемлемо|хорошо|отлично>",
      "suspicious_low": ["..."],
      "suspicious_high": ["..."],
      "fixes": [{{"id": "G8_Pxx", "current": <N>, "suggested": <M>, "reason": "<почему>"}}]
    }},
    "G9": {{
      "score": <1-10>,
      "distribution_quality": "<плохо|приемлемо|хорошо|отлично>",
      "suspicious_low": ["..."],
      "suspicious_high": ["..."],
      "fixes": [{{"id": "G9_Pxx", "current": <N>, "suggested": <M>, "reason": "<почему>"}}]
    }},
    "G10": {{
      "score": <1-10>,
      "distribution_quality": "<плохо|приемлемо|хорошо|отлично>",
      "suspicious_low": ["..."],
      "suspicious_high": ["..."],
      "fixes": [{{"id": "G10_Pxx", "current": <N>, "suggested": <M>, "reason": "<почему>"}}]
    }},
    "G11": {{
      "score": <1-10>,
      "distribution_quality": "<плохо|приемлемо|хорошо|отлично>",
      "suspicious_low": ["..."],
      "suspicious_high": ["..."],
      "fixes": [{{"id": "G11_Pxx", "current": <N>, "suggested": <M>, "reason": "<почему>"}}]
    }}
  }},
  "prerequisites": {{
    "G5_G9": {{
      "score": <1-10>,
      "coverage": "<полнота цепочки>",
      "issues": ["..."]
    }},
    "G10_internal": {{
      "score": <1-10>,
      "coverage": "<комментарий>",
      "missing_critical": ["<пропущенная важная связь G10_Pxx → G10_Pyy>", "..."],
      "issues": ["..."]
    }},
    "G11_internal": {{
      "score": <1-10>,
      "coverage": "<комментарий>",
      "missing_critical": ["..."],
      "issues": ["..."]
    }},
    "cross_grade_G10_G9": {{
      "score": <1-10>,
      "accuracy": "<точность межклассных связей>",
      "missing_critical": ["..."]
    }},
    "cross_grade_G11_G10": {{
      "score": <1-10>,
      "accuracy": "<точность межклассных связей>",
      "missing_critical": ["..."]
    }}
  }},
  "cognitive_types": {{
    "G5": {{"score": <1-10>, "issues": ["..."]}},
    "G6": {{"score": <1-10>, "issues": ["..."]}},
    "G7": {{"score": <1-10>, "issues": ["..."]}},
    "G8": {{"score": <1-10>, "issues": ["..."]}},
    "G9": {{"score": <1-10>, "issues": ["..."]}},
    "G10": {{"score": <1-10>, "issues": ["..."]}},
    "G11": {{"score": <1-10>, "issues": ["..."]}}
  }},
  "import_fixes_sql": "<одна строка SQL UPDATE для самых критичных исправлений или пустая строка если всё ок>",
  "overall": {{
    "score": <1-10>,
    "grade": "<A|B|C|D|F>",
    "summary": "<2-3 предложения итоговой оценки на русском>",
    "top_priorities": [
      "<самое важное что нужно сделать>",
      "<второе по приоритету>",
      "<третье>"
    ]
  }}
}}
""".strip()


def main():
    parser = argparse.ArgumentParser(description="AI-ревью базы знаний G5-G11")
    parser.add_argument("--grade", type=int, help="Только один класс (опционально)")
    args = parser.parse_args()

    grade_filter = str(args.grade) if args.grade else ""

    print("=" * 60)
    print(f"  AI-РЕВЬЮ УЧЕБНОГО ПЛАНА  |  Gemini 3.1 Pro Preview")
    print("=" * 60)
    print("\n  Загружаем данные из БД...")

    curriculum_text = load_curriculum_summary(grade_filter)

    total_lines = curriculum_text.count("\n")
    total_chars = len(curriculum_text)
    print(f"  Данные загружены: {total_lines} строк, {total_chars:,} символов")

    prompt = REVIEW_PROMPT.format(curriculum_text=curriculum_text)
    print(f"\n  Отправляем в {MODEL}... (может занять 1-2 мин)")

    raw = gemini_pro(prompt)

    try:
        data = parse_json(raw)
    except Exception as e:
        raw_path = "/tmp/curriculum_review_raw.txt"
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(raw)
        print(f"\n  PARSE ERROR: {e}")
        print(f"  Сырой ответ сохранён: {raw_path}")
        print("  Первые 2000 символов:")
        print(raw[:2000])
        sys.exit(1)

    # ── Вывод результатов ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  РЕЗУЛЬТАТЫ РЕВЬЮ")
    print("=" * 60)

    # Overall
    ov = data.get("overall", {})
    score = ov.get("score", "?")
    grade = ov.get("grade", "?")
    print(f"\n  ИТОГОВАЯ ОЦЕНКА: {score}/10  [{grade}]")
    print(f"  {ov.get('summary', '')}")
    print("\n  Приоритеты:")
    for i, p in enumerate(ov.get("top_priorities", []), 1):
        print(f"    {i}. {p}")

    # Importance
    print("\n" + "-" * 50)
    print("  IMPORTANCE L3 (используется алгоритмом deep scan)")
    imp = data.get("grades_importance", {})

    for key in ["G5", "G6", "G7", "G8", "G9", "G10", "G11"]:
        gi = imp.get(key, {})
        if gi:
            print(f"\n  {key}: score={gi.get('score','?')}/10  [{gi.get('distribution_quality','?')}]")
            for low in gi.get("suspicious_low", []):
                print(f"    ↓ LOW: {low}")
            for high in gi.get("suspicious_high", []):
                print(f"    ↑ HIGH: {high}")
            fixes = gi.get("fixes", [])
            if fixes:
                print(f"    Исправления ({len(fixes)}):")
                for fix in fixes:
                    if isinstance(fix, dict):
                        print(f"      {fix.get('id','?')}: {fix.get('current','?')} → {fix.get('suggested','?')}  ({fix.get('reason','')})")
                    else:
                        print(f"      {fix}")

    sql_fix = data.get("import_fixes_sql", "")
    if sql_fix:
        print(f"\n  SQL исправления:\n  {sql_fix}")

    # Prerequisites
    print("\n" + "-" * 50)
    print("  PREREQUISITES")
    pr = data.get("prerequisites", {})
    for key, label in [
        ("G5_G9", "G5-G9 (expert)"),
        ("G10_internal", "G10 внутри"),
        ("G11_internal", "G11 внутри"),
        ("cross_grade_G10_G9", "G10→G9 cross"),
        ("cross_grade_G11_G10", "G11→G10 cross"),
    ]:
        pd = pr.get(key, {})
        if pd:
            print(f"\n  {label}: score={pd.get('score','?')}/10")
            cov = pd.get("coverage") or pd.get("accuracy", "")
            if cov:
                print(f"    {cov}")
            for m in pd.get("missing_critical", []):
                print(f"    ⚠ MISSING: {m}")
            for issue in pd.get("issues", []):
                print(f"    ⚠ {issue}")

    # Cognitive types
    print("\n" + "-" * 50)
    print("  COGNITIVE TYPES L3")
    ct = data.get("cognitive_types", {})
    for key in ["G5", "G6", "G7", "G8", "G9", "G10", "G11"]:
        cti = ct.get(key, {})
        if cti:
            print(f"\n  {key}: score={cti.get('score','?')}/10")
            for issue in cti.get("issues", []):
                print(f"    ⚠ {issue}")

    # Сохраняем JSON
    import json as _json
    out_path = "/tmp/curriculum_review.json"
    with open(out_path, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n  Полный JSON сохранён: {out_path}")


if __name__ == "__main__":
    main()
