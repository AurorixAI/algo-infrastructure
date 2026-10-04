# P09: перенос формул с отступами, прокрутка для неделимого содержимого

4 октября 2026. Проверенный локальный frontend сохранён и отправлен в `CEO`:
[`cfd80b326767bb9366ea35f9a7c0219e1819acea`](https://github.com/AurorixAI/algo-front/commit/cfd80b326767bb9366ea35f9a7c0219e1819acea).
Он заменяет [первоначальный кандидат b389ee87](2026-10-04-formula-candidate.md),
который принудительно сохранял display-формулы в одной строке.

Помещающиеся по ширине интегралы, дроби и корни получают вертикальный запас.
Длинные суммы переносятся между атомарными группами KaTeX; межстрочные отступы
предотвращают наложение дробей. Неделимая широкая матрица сохраняет структуру
и горизонтальную прокрутку. Канонические данные, parser и математическое
содержание не изменены.

Расширенная проверка обнаружила потерю режима канонического условия в preview
и диагностическом отчёте. Общий TaskStatement передаёт текст и renderMode
одной projection. Заголовки task cards переносятся, мобильный переключатель
вкладок отчёта помещается в экран. Это частичная работа N04; полный аудит
содержания и восстановления отчётов остаётся в N03/N04.

Локальная приёмка точного источника: 9 display-contract tests, 8 workflow guards,
TypeScript, production standalone build и **30 состояний Chrome** на ширинах
360/768/1280. Нет glyph clipping, наложений строк, raw TeX, parse/JS errors
и document/body overflow. Сумма переносится без горизонтального скролла;
матрица сохраняет все 48 дробей и прокручивается до конца.

[Browser result и SHA-256 проверенных файлов](../engineering/evidence/p09-hybrid-math-layout-2026-10-04.json),
[причина и объём](../engineering/evidence/p09-hybrid-rendering-2026-10-04.md),
[машиночитаемые bindings](2026-10-04-formula-hybrid-candidate.json).
Проверки используют синтетические HTTP fixtures; это не приёмка backend/RBAC
или эмпирической точности диагностики.

[GitHub CI этого SHA](https://github.com/AurorixAI/algo-front/actions/runs/37211669477)
**пройден**, включая 30 browser states на standalone build. Deploy **skipped**;
ветка CEO не публикует stage. [Точный CI result](evidence/p09-hybrid-git-ci-2026-10-04.json).

Stage и production не перезапускались, банк и схема не изменялись. Git source
archive и local bundle ещё не объявляются immutable release image. Прежний
stage release binding остаётся действующим. Для публикации нужен итог CI,
продвижение конкретного Git-коммита через `develop` по
[runbook](GIT_FIRST_STAGE.md), image/source bindings и приёмка на stage.
Предыдущий запрос публикации b389ee87 не распространяется автоматически
на этот уточнённый кандидат.
