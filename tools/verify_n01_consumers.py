"""Exercise authored bank repairs through the real diagnostic/report consumers.

Offline only: the content transport is replaced with educational candidate
rows. No pupil data, network, paid LLM calls or database writes are involved.
"""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch


def verify(workspace: Path, manifest_path: Path, source_path: Path) -> dict:
    sys.path.insert(0, str(workspace / 'diagnostic-service'))
    from src.domain.answer_evaluator import AnswerEvaluator
    from src.domain.task_display import build_diag_answer_options, diag_answer_type_for_display
    from src.domain.report_generator import _build_error_patterns
    from src.domain.session_service import SessionService
    from src.domain.session_state import SessionState
    from src.clients import content_client

    manifest = json.loads(manifest_path.read_text())
    originals = {r['id']: r for r in json.loads(source_path.read_text())['content']['tasks']}
    evaluator = AnswerEvaluator()
    counts = {'tasks': 0, 'graded_choices': 0, 'display_runs': 0, 'report_errors': 0}
    for entry in manifest['repairs']:
        row = {**originals[entry['id']], **entry['changes']}
        if not row.get('is_active', True):
            continue
        task = SimpleNamespace(**row)
        for seed in range(12):
            values, displays = build_diag_answer_options(task, f'n01:{seed}:{task.id}')
            assert len(values) == len(displays) == 4, (task.id, values)
            assert dict(zip(values, displays)) == dict(zip(row['answer_options'], row['answer_options_latex']))
            assert diag_answer_type_for_display(task, values) == 'mcq'
            # Exercise the real outgoing schema; key / dmeta cannot leak into it.
            state = SessionState(session_id=f'n01:{seed}', student_id='offline-n01', grade_level=10)
            outgoing = SessionService._task_to_out(None, task, state).model_dump()
            assert outgoing['question_latex'] == row['question_latex']
            assert len(outgoing['answer_options']) == 4
            assert 'correct_answer' not in outgoing and 'distractor_meta' not in outgoing
            counts['display_runs'] += 1
        for answer_type in (row['answer_type'], 'mcq'):
            task.answer_type = answer_type
            assert evaluator.evaluate(task, row['correct_answer']) == (1., 'correct')
            counts['graded_choices'] += 1
            for distractor in row['distractor_meta']:
                assert evaluator.evaluate(task, distractor['value']) == (0., 'distractor'), (task.id, distractor['value'])
                counts['graded_choices'] += 1
        response = SimpleNamespace(status_code=200, json=lambda: row)
        answers = [SimpleNamespace(id=index, task_id=task.id, skill_id=row['skill_id'],
                                   outcome=0., student_answer=d['value'], eval_category='distractor')
                   for index, d in enumerate(row['distractor_meta'])]
        with patch.object(content_client, 'get', return_value=response):
            errors = _build_error_patterns(answers, {})
        assert len(errors) == 3
        for error, distractor in zip(errors, row['distractor_meta']):
            assert error['question_latex'] == row['question_latex']
            assert error['correct_answer_latex'] == row['correct_answer_latex']
            assert error['student_answer_latex'] == distractor['value_latex']
            assert error['distractor_explanation'] == distractor['error_logic']
            assert error['distractor_explanation_latex'] == distractor['error_logic_latex']
            counts['report_errors'] += 1
        counts['tasks'] += 1
    return {'batch': manifest['batch'], 'offline': True, 'student_data_included': False, **counts}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.workspace, args.manifest, args.source)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered)
    print(rendered)
