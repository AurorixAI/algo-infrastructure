# Git-first: сохранить текущий stage и выпускать следующие версии

Актуально: 4 октября 2026, Asia/Tashkent. `CEO` — согласованная рабочая ветка.
Этот runbook касается только `stage.algolab.me`, project `algo-preview`, контейнеров
`algo-preview-*`. `algo-staging-*` обслуживают **production** `algolab.me`.

## Что действует в GitHub Actions

В пяти приложениях push `CEO` запускает существующие проверки, **без deploy**.
Push `develop` запускает проверки и затем автоматически публикует stage; push
`main` — production. Поэтому сохранение сегодняшних изменений делаем в `CEO`,
без merge/push `develop` или `main`. Infrastructure CI также проверяет `CEO`.

Будущие deploy jobs выбирают точный проверенный `github.sha`, проверяют, что
commit доступен на соответствующей origin-ветке, и строят отдельный контекст из
`git archive`. При dirty tracked/untracked checkout job прекращается, ничего не
удаляет. Игнорированные env/cache файлы остаются на сервере и не попадают в
архив. `source.compose.json` указывает только этот контекст; runtime-секреты
читаются из server-only `.env.preview` / `.env.staging` за его пределами.

`RELEASE_SHA` сам по себе не доказывает происхождение исходников. Вместе с ним
сохраняются commit/tree, архивный SHA-256, OCI revision label, running image ID,
предыдущий image ID и его отдельный rollback tag. Deploy не выполняет prune.
Concurrency не отменяет выполняющийся релиз. Health/version checks не заменяют
проверку миграций, банка и приёмку в браузере.

## Подтверждённый CEO checkpoint 4 октября

Пять application workflow и infrastructure прошли GitHub CI baseline на pushed
CEO SHA; deploy приложениям пропущен по условию ветки. Content прошёл полную
suite: 375 passed без skipped/deselected; прежние пять исключений сняты.
[Checkpoint с точными SHA](2026-10-04-git-checkpoint.md) и
[CI evidence](evidence/git-ci-2026-10-04.json) фиксируют этот объём отдельно от
исторической P03/P06 приёмки. Для следующего commit дождаться его собственного CI.

Текущие legacy stage images и committed source hashes связаны в
[release record](2026-10-04-stage-git-binding.json). Новую Git-сборку, promotion
проверенного immutable image и combined rollback этот checkpoint не подтверждает.

## Зафиксировать уже работающий кандидат без перезапусков

1. Сверить текущие source files/политику с manifest P03/P04/P06/P06R/P06F/P06UI,
   running preview images и конфигурацией. Выделить наложения, которые были
   опубликованы поверх base image; текущий HEAD до commit не приписывать им.
2. Просмотреть diff и исключить ключи, env, персональные отчёты, дампы, логи и
   бинарные резервные копии. Сохранить все принятые кодовые изменения, тесты,
   документы и skills в соответствующих независимых репозиториях.
3. Commit и push каждого репозитория в `CEO`, без force. Убедиться, что удалённая
   ветка содержит точные SHA, и дождаться CI. Реальные ошибки и deselected тесты
   записать как открытые gates, а не объявлять всё зелёным.
4. В version-controlled release record связать эти Git SHA с действующими
   runtime image IDs и хешами проверенных файлов. Для legacy overlay явно
   записать `legacy_overlay_matched_to_committed_source`: это проверка совпадения
   source files, **не утверждение**, что старый image был построен этим commit.
   Frontend compiled bundle сверять с исходным build manifest/архивом: TSX
   нельзя непосредственно сравнивать с JavaScript через один file hash.
5. Записать migration heads, shape follow-ups, безопасную конфигурацию CAT,
   банк/фигуры и rollback points. Секреты и дампы остаются приватно вне Git.
   На этом этапе stage работает в прежних контейнерах; перезапуск не требуется.

## Подготовить следующий stage из pushed CEO

Из корня infrastructure repository запустить offline-build-input preparation
(проверка remote выполняется read-only через `git ls-remote`; заранее fetch CEO):

```bash
python3 scripts/prepare_git_release.py \
  --workspace /absolute/path/to/ALGO \
  --output /absolute/path/to/new-release-directory \
  --commit algo-front=<FULL_40_CHARACTER_SHA> \
  --commit auth-service=<FULL_40_CHARACTER_SHA> \
  --commit diagnostic-service=<FULL_40_CHARACTER_SHA> \
  --commit exam-service=<FULL_40_CHARACTER_SHA> \
  --commit content-service=<FULL_40_CHARACTER_SHA> \
  --commit algo-infrastructure=<FULL_40_CHARACTER_SHA>
```

Заменить все placeholders реальными SHA; команды с `<...>` дословно не запускать.
Инструмент требует clean `CEO`, проверяет каждый commit на **текущем** origin/CEO,
не принимает stale tracking ref, экспортирует только tracked Git tree. Получаем
шесть `.tar`, их hashes, `source-manifest.json` и его checksum. Никаких сборок,
SSH-записей, рестартов или изменений БД инструмент не делает. Уже существующий
output directory отклоняется; частично неудачный output не использовать.

Подготовленный source manifest — **ещё не release manifest и не готовый deploy**.
Для diagnostic/exam/frontend доступен `scripts/build_git_images.py --inputs <prepared-directory> --service <name>`: он сверяет архивы и успешный exact-SHA `ci-gates.json`, строит Linux/amd64 images с revision/archive labels и сохраняет immutable image IDs. Он не переключает контейнеры; статус результата остаётся `images_built_acceptance_pending`. Перед запуском на сервере копируются именно подготовленные Git-архивы и checksum; оператор выполняет собственную приёмку этих images и следующие gates.
До переключения:

1. Проверить архивные hashes; распаковать в новый пустой build directory. Собирать
   Linux images только из этих архивов, с OCI `org.opencontainers.image.revision`
   и архивным digest. Frontend `NEXT_PUBLIC_*` передать для `stage.algolab.me`
   при сборке; секреты не передавать в build args и не помещать в контекст.
2. Закрепить image IDs или registry digests и версии зависимостей. Для unchanged
   services закрепить существующие immutable images; не пересобирать всё ради
   одного изменения. Проверки должны использовать точные продвигаемые images.
3. Выполнить необходимый набор unit/integration/lifecycle/браузерных/PDF проверок,
   включая изолированные PostgreSQL/Redis и migration drill на копии. Успешный
   CEO CI baseline фиксируется отдельно; новый image проверяется в точном
   продвигаемом составе. Незакрытые пункты expanded acceptance видимы в release gate.
4. Diagnostic/content запускают `migration_runner` при старте image. Проверить
   Alembic history **и реальную shape**, совместимость с прошлым кодом, подготовить
   приватные stage backups и checkpoint. Code rollback не откатывает БД.
5. Записать before-state: production container IDs/config hash (контроль
   неизменности), target stage IDs/images/schema, content/figure fingerprint,
   non-secret CAT policy, config hash, rollback tags и путь приватного backup.
6. Создать target-only image override: `services` содержит только выбранные
   preview приложения, exact image refs и их индивидуальные RELEASE_SHA/REF/AT.
   Не менять DB/Redis/volumes/production. Для ручного stage override использовать
   проверенный Git-архив compose и сохранённую server-only env-конфигурацию.

Пример переключения **после выполнения gate и разрешения релиза**:

```bash
cd /home/algo/algo
docker compose \
  -f algo-infrastructure/compose/docker-compose.preview.yml \
  -f /absolute/path/to/release/verified-images.compose.json \
  -p algo-preview --env-file .env.preview \
  up -d --no-build --no-deps diagnostic-service
```

Пример применим только к уже подготовленному `verified-images.compose.json`.
Для каждого выбранного приложения сначала сверить container image ID, readiness,
version и source provenance, затем выполнить приёмку. Записать фактический release
manifest в Git отдельным commit/push CEO. Сохранение манифеста не даёт оснований
считать неуспешный релиз успешным. Новые изменения не копировать поверх runtime.

## Откат

Сохранённый previous image получает отдельный tag до build. При ошибке остановить
продвижение и вернуть выбранное приложение через exact previous image override
с `--no-build --no-deps`; проверить readiness, schema compatibility и поведение.
Не использовать `compose down`, wildcard restart/remove или удаление volumes.

После пользовательских действий restore старой БД теряет новые записи. Сначала
сохранить новое состояние и проверить восстановление на копии. Destructive DB
restore/downgrade требует отдельного конкретного разрешения; production здесь
не разрешён. Code/schema/data rollback — разные процедуры.

## Открытые gates

- Полный combined rollback drill и все migration checkpoint paths.
- Автоматическая сборка/публикация immutable images в registry и единый ручной
  multi-repository stage promotion job из manifest (подготовка здесь не выдаётся
  за уже работающий такой deploy).
- Приёмочный manifest следующего релиза с точными проверенными images,
  schema/data checkpoints и совместимостью предыдущего кода для rollback.
- Банк, исправления отчёта и расширенная приёмка согласно engineering roadmap.
- Расширенная PostgreSQL/RBAC/конкурентная, browser/load/visual матрица продукта.

Правило: Git commit → push CEO → exact-source build → проверка immutable images
и данных → stage → приёмка → release record. Следующие этапы не заменяют предыдущие.

## Подключить проектные навыки на другом workspace

После клонирования независимых репозиториев в одну папку выполнить `python3 algo-infrastructure/scripts/setup_workspace_skills.py` из её корня. Инструмент создаёт относительные ссылки `AGENTS.md` и `.agents/skills/` на канонические инструкции в infrastructure. Повтор безопасен; существующие чужие инструкции не заменяются. Основной план и навыки обновляются через Git, без отдельных локальных копий.
