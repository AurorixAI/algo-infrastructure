#!/usr/bin/env python3
"""
run_chain.py — Запускает полную цепочку обогащения G5→G11.

Порядок:
  1. phase c (внутренние prerequisites) для G5, G6, G7, G8, G9
  2. cross-grade  G5→G6, G6→G7, G7→G8, G8→G9, G9→G10, G10→G11
  3. phase c для G10, G11 (добавит пропущенные, ON CONFLICT DO NOTHING)
  4. Финальная сводка

Использование:
  python3 scripts/run_chain.py
  python3 scripts/run_chain.py --dry-run
  python3 scripts/run_chain.py --skip-internal   # только cross-grade
"""

import argparse
import sys
import os

# Добавляем директорию scripts в path чтобы импортировать enrich_curriculum
sys.path.insert(0, os.path.dirname(__file__))
import enrich_curriculum as ec

def run_chain(dry_run: bool = False, skip_internal: bool = False, skip_cross: bool = False):
    print("\n" + "=" * 60)
    print("  ПОЛНАЯ ЦЕПОЧКА ОБОГАЩЕНИЯ G5 → G11")
    print("=" * 60)

    # ── 1. Внутренние prerequisites G5-G9 (supplement expert data) ──
    if not skip_internal:
        for grade in [5, 6, 7, 8, 9]:
            print(f"\n{'─'*60}")
            print(f"  [INTERNAL] Grade {grade}")
            print(f"{'─'*60}")
            ec.gen_prerequisites(grade, dry_run=dry_run)

    # ── 2. Cross-grade цепочка ──
    if not skip_cross:
        pairs = [(5, 6), (6, 7), (7, 8), (8, 9), (9, 10), (10, 11)]
        for lo, hi in pairs:
            print(f"\n{'─'*60}")
            print(f"  [CROSS] G{lo} → G{hi}")
            print(f"{'─'*60}")
            ec.gen_cross_grade_prereqs(lo, hi, dry_run=dry_run)

    # ── 3. Внутренние prerequisites G10-G11 (добрать пропущенное) ──
    if not skip_internal:
        for grade in [10, 11]:
            print(f"\n{'─'*60}")
            print(f"  [INTERNAL] Grade {grade}")
            print(f"{'─'*60}")
            ec.gen_prerequisites(grade, dry_run=dry_run)

    # ── 4. Финальная сводка ──
    print("\n" + "=" * 60)
    print("  ФИНАЛЬНАЯ СВОДКА")
    print("=" * 60)
    ec.verify()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-internal", action="store_true",
                        help="Пропустить внутриклассные prerequisites, только cross-grade")
    parser.add_argument("--skip-cross", action="store_true",
                        help="Пропустить cross-grade, только внутриклассные prerequisites")
    args = parser.parse_args()
    run_chain(dry_run=args.dry_run, skip_internal=args.skip_internal, skip_cross=args.skip_cross)
