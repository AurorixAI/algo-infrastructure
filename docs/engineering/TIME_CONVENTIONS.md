# Время в ALGO: правила хранения и сравнения

Источник: аудит №49 (17.10.2026) по auth-service, exam-service, diagnostic-service и фронту. Документ обязателен для нового кода:
любое поле со временем должно попадать в одну из двух групп ниже, а сравнение полей разных групп — только через помощники.

## Две группы

| Группа | Что это | Поля (основные) |
|---|---|---|
| **UTC** — мгновение без пояса (`timestamp without time zone`, значение в UTC) | «когда это случилось» | оплаты и квитанции (`created_at`, `voided_at`, `carried_out_at`), зарплата, аудит, `student_groups.joined_at / left_at / transferred_at`, `student_group_periods.joined_at / left_at` (история периодов членства, №59), `monthly_fee_updated_at`, `students.archived_at`, приглашения на диагностику (в т.ч. `cancelled_at`, `revived_at`), сессии `user_sessions.*` (№101), все поля exam- и diagnostic-service, `student_payment_files.uploaded_at`, метки `updated_at` в JSON настроек |
| **Ташкент** — настенное время центра (UTC+5, без перехода) | «в какой день и час урока по расписанию» | `lesson_date`, `effective_date`, `scheduled_lesson_date` (строка `YYYY-MM-DD`), время расписания `HH:MM`, `group_attendance.started_at / completed_at`, `attendance_excuses.reason_at / reviewed_at`, `attendance_excuse_files.uploaded_at`; даты `paid_on`, `valid_from / valid_to`, `period_month`, `group_prices.valid_from`, `membership_price_overrides.valid_from` (№105) — деловые дни |

Исключения, о которых надо помнить:
* exam `generated_exams.created_at / updated_at`, `exam_sessions.started_at / submitted_at` — в базе `timestamptz` (в ORM объявлены без пояса).
  Значения приходят с поясом, код приводит их через `_to_naive_utc`; фронт понимает обе записи (`parseUtcNaive`).
* `group_attendance.created_at / updated_at` — UTC, хотя `started_at / completed_at` той же строки — Ташкент. Не вычитать одно из другого.
* Старые строки `group_attendance.completed_at` на stage заполнены миграцией `g7h8i9j0k1l2` в UTC (на проде строк нет).

## Правила

1. **Сессия базы всегда UTC.** `func.now()`, `server_default now()` и aware-значения пишутся в колонку без пояса через пояс сессии.
   Поэтому пояс закреплён на каждом соединении (`-c timezone=UTC`), а сервис не стартует, если `current_setting('TimeZone')` не UTC.
2. **Сравнивать группы только через помощники.**
   * Мгновение UTC → деловой день Ташкента: `business_date` (auth, `payments_service`).
   * Начало урока (день + `HH:MM` Ташкента) → мгновение UTC: `lesson_start_as_naive_utc`.
   * «Был ли ученик в группе в момент урока»: `membership_covers_instant` (по периодам членства).
   * Никогда: `utc_value.date()` как деловой день, `date.today()` / `datetime.now()` без явного пояса.
3. **«Сегодня» центра** — только по Ташкенту (`BUSINESS_TIMEZONE`, по умолчанию `Asia/Tashkent`); в SQL — `NOW() AT TIME ZONE 'Asia/Tashkent'`.
4. **Фронт.** Метки UTC без пояса показывать только через `formatUtcNaiveAsBusiness*` (`src/lib/business-time.ts`);
   поля группы «Ташкент» — через `formatDateTimeRu` / даты как есть. `new Date(x).toLocale…` на значениях с сервера — запрещено
   (браузер подставит свой пояс).
5. **Новая колонка со временем** — по умолчанию UTC; в комментарии модели указать группу.

## Почему не `timestamptz` везде (решение 17.10.2026)

Полный перевод — около 86 колонок в трёх сервисах, ~70 мест записи, ~55 значений по умолчанию; `ALTER … TYPE timestamptz`
переписывает таблицы под эксклюзивной блокировкой, psycopg2 начнёт отдавать значения с поясом, и каждое сравнение с
`utcnow()` / `datetime.min` упадёт с TypeError; откат тяжёлый. Он не убирает деловые даты и `HH:MM` (они местные по смыслу).
Сейчас защита — закреплённый UTC, помощники и этот документ. Вернуться к вопросу при нескольких часовых поясах или BI.
