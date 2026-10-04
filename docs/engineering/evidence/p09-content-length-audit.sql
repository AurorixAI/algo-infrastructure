-- Read-only triage of display sources, not a mathematical verdict.
-- question_latex stays canonical; lengths include TeX commands.
BEGIN READ ONLY;
WITH canonical AS (
  SELECT t.id, t.is_active,
    COALESCE(NULLIF(btrim(t.question_latex), ''), t.question_text, '') AS question,
    COALESCE(o.max_len, 0) AS option_max,
    COALESCE(o.min_len, 0) AS option_min,
    COALESCE(o.option_count, 0) AS option_count,
    (COALESCE(t.question_latex, '') || COALESCE(t.question_text, '') ||
      COALESCE(t.answer_options::text, '') || COALESCE(t.answer_options_latex::text, '')) AS raw_sources
  FROM tasks_master t
  LEFT JOIN LATERAL (
    SELECT max(length(v)) AS max_len,
      min(length(v)) FILTER (WHERE length(v) > 0) AS min_len,
      count(*) AS option_count
    FROM (
      SELECT COALESCE(NULLIF(btrim(t.answer_options_latex->>i), ''), t.answer_options->>i, '') AS v
      -- UI iterates raw options; latex is a projection for the same index.
      -- Extra latex entries without raw options are not visible choice buttons.
      FROM generate_series(0,
        jsonb_array_length(COALESCE(t.answer_options::jsonb, '[]'::jsonb)) - 1) i
    ) choices
  ) o ON true
), active AS (SELECT * FROM canonical WHERE is_active), queue AS (
  SELECT id, length(question) AS question_length, option_max, option_min,
    option_count,
    (option_max > 250 AND option_min > 0 AND option_max >= 4 * option_min) AS length_cue_review
  FROM active WHERE length(question) > 500 OR option_max > 250
)
SELECT json_build_object(
  'total', (SELECT count(*) FROM canonical),
  'active', (SELECT count(*) FROM active),
  'question_gt250', (SELECT count(*) FROM active WHERE length(question)>250),
  'question_gt500', (SELECT count(*) FROM active WHERE length(question)>500),
  'question_gt1000', (SELECT count(*) FROM active WHERE length(question)>1000),
  'question_max', (SELECT max(length(question)) FROM active),
  'tasks_option_gt120', (SELECT count(*) FROM active WHERE option_max>120),
  'tasks_option_gt250', (SELECT count(*) FROM active WHERE option_max>250),
  'option_max', (SELECT max(option_max) FROM active),
  'qa_fixture_phrase_rows', (SELECT count(*) FROM canonical WHERE raw_sources LIKE '%Каноническое условие 500:%'),
  'length_cue_review_count', (SELECT count(*) FROM queue WHERE length_cue_review),
  'review_queue', (SELECT json_agg(q ORDER BY q.question_length DESC, q.option_max DESC, q.id) FROM queue q)
);
COMMIT;
