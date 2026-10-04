# Git checkpoint ALGO — 4 октября 2026

Принятый код и тесты сохранены в `CEO` пяти приложений; план, инфраструктура, навыки и обезличенные доказательства — в `CEO` infrastructure. `algo-landing` был чистым и изменений этой задачи не содержит. `CEO` — рабочая ветка владельца: CI без deploy. Stage обновляется через `develop`, production — через `main`.

## Зафиксированные приложения

- Frontend: [8c2e72a](https://github.com/AurorixAI/algo-front/commit/8c2e72acbee22bb81b0fe407a3ca1dafbfaa0357).
- Auth: [9675cbe](https://github.com/AurorixAI/auth-services/commit/9675cbe769e42dcad82fa05a088abf3c826d70a3).
- Diagnostic: [b93a9a9](https://github.com/AurorixAI/diagnostics-service/commit/b93a9a923fb17989f07b7dd8703196a894b29b99); код исправлений находится в родительском a80328f, последний коммит уточняет документацию политики.
- Content: [b711083](https://github.com/AurorixAI/content-service/commit/b71108365f40e8644c1864296cf21046553b2b95).
- Exam: [c0ca477](https://github.com/AurorixAI/exam-service/commit/c0ca477e53171ec0863592052c80b927ef93d380).
- Infrastructure: [ac8db0d](https://github.com/AurorixAI/algo-infrastructure/commit/ac8db0d1ab4f9087afcf585159ad47c67b8c6271) — baseline конфигурации, workflow и skills. Следующий коммит содержит эту запись и актуализацию документов. Точный SHA содержащего её коммита берётся из Git; шестирепозиторный source manifest включает полный SHA infrastructure без рекурсивного самоописания.

## Что доказано

[Запись соответствия stage и Git](2026-10-04-stage-git-binding.json) хранит 255 backend source/Alembic hashes, 106 frontend src/public hashes из frozen build source, точные Git SHA, running image IDs, старые release labels, schema heads, CAT-политику и hashes используемых compose/nginx файлов. Все проверенные application файлы совпали с committed blobs. После push все пять stage-контейнеров и 15 production-контейнеров сохранили identities; банк и schema heads не менялись.

Работающие образы stage ранее собирались из frozen archives/overlays. Их совпадение с кодом в Git не превращает эти образы в новую сборку из Git-коммитов. Новой сборки и перезапуска этой задачей не выполнено. Банк БД не хранится в Git: сохранён fingerprint 37 264 строк / 34 267 активных; приватные бэкапы остаются на сервере.

[GitHub CI baseline](evidence/git-ci-2026-10-04.json): все шесть workflow прошли; deploy в пяти application workflow пропущен по условию `CEO`. Auth 251, diagnostic 193, content 375, exam 227 тестов; frontend 9 selector tests, TypeScript и production build. Content прошёл полный набор без прежних пяти исключений. Дополнительно: 40 поведенческих проверок deploy guards и 10 infrastructure tests. Это отдельная приёмка конкретных Git SHA; её не суммируем с P03/P06.

Новые guards отклоняют остановленный контейнер с последним healthy-state, неправильный/missing OCI revision при верном runtime RELEASE_SHA; через SSH metadata передаются только три разрешённых release поля. Future build берёт exact tested SHA и отдельный `git archive`, сохраняет прежний image под rollback tag до build и не выполняет prune/reset/clean.

Auth `.env.production` снят с текущего Git-отслеживания, рабочий файл сохранён; добавлен пустой production template. Frontend demo flag хранится в `.env.demo.example`. История Git не переписана и прошлые ключи этим действием не ротированы. Приватные env, дампы и отчёты в новые коммиты не включены.

Три навыка подключены в workspace относительными ссылками на versioned canonical skills; `AGENTS.md` и основной план тоже указывают на Git-версии. Для другого клона есть `scripts/setup_workspace_skills.py`: повтор безопасен, чужие инструкции не перезаписываются. Навыки проверены независимыми сценариями SE-изменения, Git/stage выпуска и мобильного UI-дефекта.

## Что дальше

[Основной план](../engineering/ROADMAP.md): N00 закрыт в этом объёме; N01 — шесть заданий, N02 — согласование уровня/навыков/истории/Deep Scan, N03 — профессиональное содержание отчёта, N04 — вкладки и recovery, N05 — полная stage-приёмка. Решённый LaTeX и намеренные деактивации сохраняются. LLM подключается существующим механизмом после качественного fallback, при наличии ключей.

Новая immutable Git-сборка, продвижение того же image после его проверки, единый multi-repository promotion, расширенная PostgreSQL/RBAC/visual матрица и combined rollback/DB restore пока не приняты; они остаются gates N05/N07/N11. [Runbook](GIT_FIRST_STAGE.md) описывает путь до публикации. При подготовке следующего релиза сначала фиксируются точные pushed commits, затем сборка и проверка, затем продвижение через `develop` на stage. Новый файл из локальной папки на сервер как источник релиза не переносится.
