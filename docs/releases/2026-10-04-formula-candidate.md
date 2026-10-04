# P09 frontend: проверенный кандидат, stage пока прежний

4 октября 2026. Исправление сохранено в согласованной `CEO`:
[`b389ee87d824a88e502eeb81f7230334307cbeca`](https://github.com/AurorixAI/algo-front/commit/b389ee87d824a88e502eeb81f7230334307cbeca).
[Машиночитаемые bindings и проверки](2026-10-04-formula-candidate.json).

При длинных/высоких display-формулах верхние и нижние элементы могли скрываться,
а перенос частей формулы накладывал строки дробей. CSS сохраняет нативные размеры
KaTeX, вертикальный вынос glyphs и intrinsic width с горизонтальной прокруткой.
Математическое содержание, canonical question_latex, parser, backend, schema,
CAT-пороги и банк этим кандидатом не меняются.

Проверки: 9 display-contract, 8 workflow guards, TypeScript, production standalone
build и 27 состояний Chrome. Glyph clipping: 38 до → 0 после; широкая формула
прокручивается до конца при 360/768/1280. [Browser evidence](../engineering/evidence/p09-candidate-math-layout-2026-10-04.json).
Portable regression сохранена в frontend и включена в workflow после build;
GitHub использует чистый checkout, отдельный pinned Playwright и Chromium.

GitHub CI этого frontend SHA **пройден**, включая все 27 browser states;
deploy CEO **skipped**. CI infrastructure-кандидата `3290a672` также пройден.
[Точные run IDs и результаты](evidence/p09-git-ci-2026-10-04.json).

Git source archive сохранён вне репозитория, его SHA-256 и tree зафиксированы.
Хеши проверенных CSS/harness совпадают с содержимым этого коммита. Локальный
bundle ещё не объявляется immutable release image. Stage не перезапускался;
production не затрагивался. Старый release binding остаётся действующим.

Read-only preflight: preview/production frontend images совпадают с прежними
bindings, оба running. Stage Git checkout чистый (0 изменений), HEAD
`e0e8c665be0523750fafc86e840689afbbdc7d59`; файлы checkout не обновлялись.

Для публикации frontend: принять CI этого SHA, продвинуть проверенный Git commit
через stage-ветку `develop` по [runbook](GIT_FIRST_STAGE.md), получить image/source
bindings и предыдущий image для отката, повторно проверить frontend на stage.
Полный multi-repository promotion/combined rollback остаётся N07.
