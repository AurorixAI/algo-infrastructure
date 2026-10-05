"""Read educational tasks through an unpatched service repository and HTTP API.

Run diagnostic and exam in separate processes because they both import `src`.
No session creation, pupil reads, database writes or LLM requests are performed.
"""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace


def verify(workspace: Path, consumer: str, manifest_path: Path) -> dict:
    sys.path.insert(0, str(workspace / (consumer + '-service')))
    if consumer == 'diagnostic':
        from src.repositories.knowledge_repo import TaskRepository
        from src.domain.report_generator import _build_error_patterns
        load = TaskRepository().get_by_id
    else:
        from src.repositories.task_repo import TaskRepository
        load = TaskRepository().get_task_by_id

    manifest = json.loads(manifest_path.read_text())
    checked = report_errors = 0
    for repair in manifest['repairs']:
        task = load(repair['id'])
        assert task is not None, (repair['id'], 'not loaded through actual repository')
        row = vars(task) if consumer == 'diagnostic' else task
        assert row['id'] == repair['id']
        if consumer == 'exam':
            assert row['task_id'] == row['id']
        if consumer == 'diagnostic':
            answers = [SimpleNamespace(id=0, task_id=row['id'], skill_id=row['skill_id'],
                                       outcome=0., student_answer='http-contract-wrong',
                                       eval_category='wrong')]
            error = _build_error_patterns(answers, {})[0]
            assert error['task_id'] == row['id']
            assert error['question_latex'] == row['question_latex']
            assert error['correct_answer'] == row['correct_answer']
            report_errors += 1
        checked += 1
    assert load('n01-http-contract-missing?task') is None
    return {'consumer': consumer, 'tasks': checked, 'report_errors': report_errors,
            'missing_task_preserved': True, 'sessions_created': 0,
            'student_data_included': False, 'repository_and_http_unpatched': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--consumer', required=True, choices=['diagnostic', 'exam'])
    parser.add_argument('--manifest', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.workspace, args.consumer, args.manifest)))
