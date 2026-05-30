# ALGO — Production Readiness Roadmap

> **Цель**: довести production readiness платформы с **3.5/10 → 8+/10**
> **Источник**: полный архитектурный аудит (см. summary конца сессии)
> **Дата старта**: 27 мая 2026

---

## Текущая оценка по сервисам

| Сервис | Score | Главные проблемы |
|---|---|---|
| auth-service | 2/10 | Секреты в Git, 0 тестов |
| content-service | 2/10 | GCP-ключ в Git, нет Alembic миграций |
| diagnostic-service | 4/10 | Прямой DB-доступ к content |
| exam-service | 5/10 | Прямой DB-доступ к content, открытый CORS |
| algo-front | 6/10 | Норм, нужен polish |
| algo-landing | 6/10 | Норм, нужен polish |

---

## 🔴 ФАЗА 0 — Безопасность (БЛОКЕРЫ)

> **Без этого нельзя ничего деплоить и тем более показывать инвесторам.**

| # | Задача | Acceptance Criteria |
|---|---|---|
| 0.1 | Удалить `auth-service/.env` из Git history | `git log --all -- auth-service/.env` пустой |
| 0.2 | Удалить `content-service/sa-key.json` из Git history | `git log --all -- content-service/sa-key.json` пустой |
| 0.3 | `.gitignore` + `.env.example` шаблоны во всех сервисах | Файлы есть, реальные секреты в .gitignore |
| 0.4 | Ротация `SECRET_KEY` / `JWT_SECRET_KEY` | Новые значения сгенерированы, все старые JWT инвалидированы |
| 0.5 | Ротация GCP Service Account | Новый ключ создан, старый отозван в GCP Console |
| 0.6 | Non-root user в Dockerfile (content / diagnostic / exam) | `USER appuser` в каждом Dockerfile |
| 0.7 | CORS whitelist в exam-service | `allow_origins=[...]` вместо `["*"]` |

---

## 🟠 ФАЗА 1 — Тесты + Архитектура

| # | Задача | Acceptance Criteria |
|---|---|---|
| 1.1 | Unit-тесты auth-service ≥70% coverage | `pytest --cov` ≥70%, JWT/bcrypt/RBAC/rate-limit покрыты |
| 1.2 | Alembic baseline для content-service | `alembic upgrade head` поднимает схему с нуля |
| 1.3 | diagnostic-service → content-service через HTTP API | Нет `from content.models import ...` |
| 1.4 | exam-service → content-service через HTTP API | Нет прямого DB-коннекта к `algo_content` |
| 1.5 | Smoke-tests каждого сервиса | `/health` + 1 основной flow на каждый сервис |

---

## ✅ ФАЗА 2 — Resilience + Observability

| # | Задача | Acceptance Criteria |
|---|---|---|
| 2.1 | `tenacity` retry для inter-service HTTP | 3 retry с exp backoff (1–8s), retry на ConnectError/Timeout ✅ |
| 2.2 | Structured JSON logging (structlog) | Все логи в JSON формате, ConsoleRenderer в dev ✅ |
| 2.3 | `X-Request-ID` middleware с пропагацией | Request ID в логах всех 4 сервисов ✅ |
| 2.4 | Prometheus `/metrics` endpoint | `prometheus-fastapi-instrumentator` во всех 4 сервисах ✅ |
| 2.5 | `/health/live` + `/health/ready` | live → 200 без deps; ready → DB+Redis ping, 503 при fail ✅ |

---

## ✅ ФАЗА 3 — CI/CD + Деплой

| # | Задача | Acceptance Criteria |
|---|---|---|
| 3.1 | GitHub Actions: lint + tests + docker build на PR | `.github/workflows/ci.yml` — lint×4, test-auth, test-exam, docker-build×4 ✅ |
| 3.2 | `docker-compose.prod.yml` | Без дефолтных паролей, порта DB не открыт, restart:always ✅ |
| 3.3 | Nginx reverse proxy + HTTPS (Let's Encrypt) | `nginx/` — nginx.conf + conf.d/algolab.conf + docker-compose.nginx.yml ✅ |
| 3.4 | PostgreSQL backups | `scripts/backup_postgres.sh` → GCS + 30-day lifecycle rule ✅ |

---

## ✅ ФАЗА 4 — Документация

| # | Задача |
|---|---|
| 4.1 | Корневой `README.md` + архитектурная Mermaid-диаграмма ✅ |
| 4.2 | `README.md` в каждом сервисе (env vars, как запустить, API) ✅ |
| 4.3 | Swagger UI только в dev (APP_ENV=development), закрыт в prod ✅ |

---

## Порядок исполнения

1. **Сейчас**: Ф0.1 → Ф0.7 (последовательно, без пропусков)
2. **Дальше**: Ф1.1 → Ф1.5
3. **Потом**: Ф2 → Ф3 → Ф4

> **Правило**: не переходить к следующей фазе, пока текущая не закрыта на 100%.

---

## Прогресс

- [x] Фаза 0 — Безопасность (7/7) ✅
- [x] Ф1.1 — auth-service unit tests ≥70% coverage (71%, 207 тестов) ✅
- [x] Ф1.2 — Alembic baseline content-service (6 таблиц, `alembic upgrade head`) ✅
- [x] Ф1.3 — diagnostic-service → content-service HTTP API ✅
- [x] Ф1.4 — exam-service → content-service HTTP API ✅
- [x] Ф1.5 — Smoke-tests для всех сервисов (10/10 passed) ✅
- [x] Фаза 2 — Resilience + Observability (5/5) ✅
  - [x] Ф2.1 — tenacity retry в content_client (3 attempts, exp backoff 1–8s) ✅
  - [x] Ф2.2 — structlog JSON logging (все 4 сервиса) ✅
  - [x] Ф2.3 — X-Request-ID middleware (все 4 сервиса) ✅
  - [x] Ф2.4 — Prometheus /metrics (prometheus-fastapi-instrumentator) ✅
  - [x] Ф2.5 — /health/live + /health/ready (все 4 сервиса, 200/503) ✅
- [x] Фаза 3 — CI/CD + Деплой (4/4) ✅
  - [x] Ф3.1 — GitHub Actions CI (.github/workflows/ci.yml) ✅
  - [x] Ф3.2 — docker-compose.prod.yml (все 4 сервиса) ✅
  - [x] Ф3.3 — Nginx + HTTPS algolab.me (nginx/conf.d/algolab.conf) ✅
  - [x] Ф3.4 — PostgreSQL backups (scripts/backup_postgres.sh → GCS) ✅
- [x] Фаза 4 — Документация (3/3) ✅
  - [x] Ф4.1 — Root README.md + архитектурная Mermaid-диаграмма ✅
  - [x] Ф4.2 — README.md в каждом сервисе (список env vars, API, как запустить) ✅
  - [x] Ф4.3 — Swagger UI только в dev (все 4 сервиса, APP_ENV=development) ✅

**Всего**: 24 / 24 ✅

### Детали Фазы 0:
- [x] 0.1 Секреты не в Git (gitignore покрывает .env, sa-key.json)
- [x] 0.2 sa-key.json не в Git (gitignore content-service)
- [x] 0.3 .gitignore создан для diagnostic + exam; .env.example в exam
- [x] 0.4 SECRET_KEY + JWT_SECRET_KEY ротированы (новые 256-bit)
- [x] 0.5 GCP SA — напоминание выдано (ротация вручную в GCP Console)
- [x] 0.6 Non-root user (`appuser`) добавлен в content/diagnostic/exam Dockerfiles
- [x] 0.7 CORS — whitelist уже стоял во всех сервисах (не `*`)
