# Frontend и exam-service: проверка опубликованных изменений перед Git

04.10.2026, Asia/Tashkent. Read-only review всех изменений application source в `algo-front` и `exam-service`, связанных тестов и парных контрактов. Код, Git index, банк и stage не изменялись; платные модели не вызывались. Новая deployment pipeline проверяется отдельно.

**Вывод:** новых блокеров фиксации уже опубликованного кандидата не обнаружено. Известные P07 дефекты диагностического отчёта остаются открытыми; этот вывод не означает завершения N01–N12 или production-приёмки.

## Парные контракты

- `/d/[code]` восстанавливает конкретную попытку через diagnostic resolver. Новый старт разрешается только по явному `404 SESSION_NOT_FOUND` при confirmed-приглашении. Таймаут ответа сначала проверяет сохранённое состояние; черновик не сбрасывается при сетевом отказе. Смена кода очищает чужое локальное состояние; epoch guards игнорируют запоздавшие ответы старой проверки/ссылки. Submit ref предотвращает двойной click до React rerender.
- Завершённая попытка открывает сохранённый результат, включая callback lag/expired invite. Retry загрузки результата повторно читает тот же session_id, а не создаёт попытку. Классификация ошибок API сохраняет `code/action`; диагностические чтения используют `cache: no-store`.
- Кнопка текстового ответа вызывает `onSubmit()` без React event вместо передачи события как строкового override. Это устраняет реальный ошибочный путь отправки текстового ответа.
- `question_latex` — первый источник отображения независимо от длины/языка/наличия слов. Пустое значение допускает `question_text`. Выбор согласован между frontend, exam analytics/report и PDF. Само содержание/LaTeX не переписывается.
- Exam report task statements привязываются к точному task_id сохранённых variants; для старых отчётов разрешено только единственное точное совпадение исходного условия. Неоднозначные/выдуманные модельные условия не выдаются за канонические. Проекция делает deepcopy, не изменяет сохранённый report или банк.
- Учитель, создавший контрольную для группы, должен пройти проверку текущего владения группой. После передачи группы авторство больше не обходит guard. Непривязанный library template остаётся доступным автору; owner/admin остаются ограничены своей организацией.
- Admin/teacher layouts используют компактный mobile sidebar и уменьшенные отступы. Карточка статуса диагностики и teacher exam report имеют адаптивную раскладку. Исправленная hero-card не закрывает отдельно найденный P07 overflow остальных вкладок диагностического отчёта.

Источник: [diagnostic page](https://github.com/AurorixAI/algo-front/blob/CEO/src/app/d/%5Bcode%5D/page.tsx), [frontend selector](https://github.com/AurorixAI/algo-front/blob/CEO/src/lib/task-display.ts), [teacher report](https://github.com/AurorixAI/algo-front/blob/CEO/src/app/teacher/exams/%5Bid%5D/report/page.tsx), [exam projection](https://github.com/AurorixAI/exam-service/blob/CEO/src/domain/task_display.py), [exam access](https://github.com/AurorixAI/exam-service/blob/CEO/src/core/auth.py).

## Проверки текущего прохода

- Bundled Node: `tests/task-display-contract.test.cjs` — **9 passed, 0 skipped**; выполняется настоящий TypeScript selector с настоящей math-display зависимостью.
- Frontend: `tsc --noEmit --incremental false` — **exit 0**.
- Exam: **11 исходных pure test cases** из `test_task_display_contract.py` — pass. Загружены полный production task_display module и точный AST `_task_text` PDF selector; исходные тела тестов сохранены. HTTP/DB/PDF-render в этот ограниченный повторный прогон не входят.
- Compile **54 exam src/tests Python-файлов** — pass. Существующий docstring print_pdf выдаёт SyntaxWarning для `\p`; ошибки компиляции нет.
- `git diff --check` в обоих репозиториях — pass.
- Source comparison с опубликованным P03 source archive и P06ui overlay: **105 frontend src + 40 exam src файлов**, **145/145 SHA256 совпали**, расхождений нет. Новая live-инспекция stage этим сравнением не заявляется.

Сохранённая полная suite P03 exam: **227 passed**; текущий проход не повторял весь pytest/Chrome/PDF-render. Предыдущие P03 Chrome-проверки покрывали diagnostic request failures и teacher report при 360/768/1440, role redirects для admin/owner/anonymous. Новую browser-проверку эти исторические логи не заменяют.

Доказательства: [current probes](../EVIDENCE_INDEX.md), [source hashes](../EVIDENCE_INDEX.md), [exam suite](../EVIDENCE_INDEX.md), [browser checks](../EVIDENCE_INDEX.md), [role checks](../EVIDENCE_INDEX.md).

Решённые LaTeX-примеры, намеренно отключённые рисунки и выбор `question_latex` не переоткрывались. Необоснованные проценты/точный эквивалент класса, потеря same-grade Deep Scan, false weak topics mixed-error профилей, история ключей и no-chain баннер сохраняют статусы из [P07/P08](p07-diagnostic-report-audit-2026-10-03.md).
