"""Run on the ALGO server from an exact committed copy of this script.

Stage-only in-place N01 data repair; no application deployment or pupil writes.
The content tool and manifest come from a pushed, CI-verified CEO Git archive.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit


TASK_IDS = ['G10_TB_3_9_9', 'G10_TB_6_2_16', 'G10_TB_§42_42_7_3',
            'G10_TB_6_1_1', 'G10_TB_1_6_7_g', 'G11_TB_6_6_6_43_c']
SCOPES = {
    'data/content_repairs/n01-2026-10-05-w1.json': TASK_IDS,
    'data/content_repairs/n01-2026-10-05-w2.json': [
        'G6_TB_124–125_1046.2','G6_TB_124–125_1047.6','G11_TB_§2_2',
        'G11_TB_8_4_4','G11_TB_8_4_5','G11_TB_8_4_6','G11_TB_10_4*_3',
        'G11_TB_10_4*_4','G9_TB_31_636_1','G9_TB_ДГ5_636_2','GEN_G6_S38_01_C_01',
    ],
}


def command(argv, **kwargs):
    return subprocess.check_output(argv, text=True, **kwargs).strip()


def state():
    names = command(['docker', 'ps', '-a', '--format', '{{.Names}}']).splitlines()
    names = sorted(n for n in names if n.startswith(('algo-preview-', 'algo-staging-')))
    rows = json.loads(command(['docker', 'inspect', *names]))
    return {r['Name'].lstrip('/'): {'id': r['Id'], 'image': r['Image'],
            'config_sha256': hashlib.sha256(json.dumps(r['Config'], sort_keys=True).encode()).hexdigest()}
            for r in rows}


def bank_summary(stack, excluded=()):
    where = 'WHERE id NOT IN (' + ','.join("'" + v.replace("'", "''") + "'" for v in excluded) + ')' if excluded else ''
    sql = f"""SELECT json_build_object('count',count(*),'active',count(*) FILTER (WHERE is_active),
        'md5',md5(string_agg(md5(row_to_json(t)::text),'' ORDER BY id))) FROM tasks_master t {where};"""
    return json.loads(command(['docker', 'exec', '-i', f'algo-{stack}-content-db',
                              'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-U', 'algo', '-d', 'algo_content'],
                             input='BEGIN READ ONLY;\n' + sql + '\nCOMMIT;\n'))


def stage_database_url(stage, db):
    if (not stage['State']['Running'] or stage['State'].get('Health', {}).get('Status') != 'healthy'
            or 'algo-preview-network' not in stage['NetworkSettings']['Networks']
            or set(db['NetworkSettings']['Networks']) != {'algo-preview-network'}):
        raise ValueError('stage container identity/network/health failed')
    env = dict(v.split('=', 1) for v in stage['Config']['Env'] if '=' in v)
    url = env['DATABASE_URL']
    parsed = urlsplit(url.replace('postgresql+psycopg2://', 'postgresql://', 1))
    if (parsed.scheme != 'postgresql' or parsed.hostname not in ('algo-preview-content-db', 'content-db')
            or parsed.path != '/algo_content' or parsed.username != 'algo'):
        raise ValueError('refusing a database outside the verified stage target')
    return url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--content-sha', required=True)
    parser.add_argument('--manifest',choices=SCOPES,default='data/content_repairs/n01-2026-10-05-w1.json')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    task_ids = SCOPES[args.manifest]
    if not re.fullmatch('[0-9a-f]{40}', args.content_sha):
        raise ValueError('expected exact content Git SHA')
    root = Path.home() / 'algo'
    repo = root / 'preview-src/content-service'
    assert (repo / '.git').exists(), 'missing managed content checkout'
    # Fetch objects only; no checkout/reset, source overlay or branch promotion.
    command(['git', '-C', str(repo), 'fetch', '--quiet', 'origin', 'CEO'])
    subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', args.content_sha, 'origin/CEO'], check=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    release = root / 'releases' / f'n01-bank-{args.content_sha[:12]}-{stamp}'
    release.mkdir(parents=True, mode=0o700)
    source = release / 'source'
    source.mkdir()
    archive = release / 'source.tar'
    with archive.open('wb') as stream:
        subprocess.run(['git', '-C', str(repo), 'archive', '--format=tar', args.content_sha], stdout=stream, check=True)
    subprocess.run(['tar', '-xf', str(archive), '-C', str(source)], check=True)
    manifest = json.loads((source / args.manifest).read_text())
    assert {e['id'] for e in manifest['repairs']} == set(task_ids), 'unexpected repair scope'
    before_state = state()
    stage = json.loads(command(['docker', 'inspect', 'algo-preview-content']))[0]
    db = json.loads(command(['docker', 'inspect', 'algo-preview-content-db']))[0]
    url = stage_database_url(stage, db)
    before_prod = bank_summary('staging')
    before_stage = bank_summary('preview')
    before_other = bank_summary('preview', task_ids)
    quoted = ','.join("'" + v.replace("'", "''") + "'" for v in task_ids if v != 'G11_TB_6_6_6_43_c')
    # T06 keeps its key; all other first-wave tasks must have no saved diagnostic
    # answers before modifying their wording/key/choice contract.
    impact_sql = f'SELECT count(*) FROM diag_answers WHERE task_id IN ({quoted});'
    assert int(command(['docker','exec','-i','algo-preview-diagnostic-db','psql','-X','-qAt',
                        '-v','ON_ERROR_STOP=1','-U','algo','-d','algo_diagnostic'],
                       input='BEGIN READ ONLY;\n'+impact_sql+'\nCOMMIT;\n')) == 0
    secret_file = release / '.repair-db.env'
    backup_folder = release / 'private'
    backup_folder.mkdir(mode=0o700)
    record = {'operation': 'in_place_owner_requested', 'target': 'stage.algolab.me',
              'content_sha': args.content_sha, 'manifest':args.manifest, 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
              'execution_image_id': stage['Image'], 'release_path': str(release),
              'student_data_included': False, 'before_stage': before_stage,
              'before_other_tasks': before_other, 'before_production': before_prod,
              'before_containers': before_state}
    (release / 'preflight.json').write_text(json.dumps(record, indent=2) + '\n')
    fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write('CONTENT_REPAIR_DATABASE_URL=' + url + '\n')
    base = ['docker','run','--rm','--network','algo-preview-network','--read-only',
            '--cap-drop=ALL','--security-opt','no-new-privileges','--pids-limit','128',
            '--memory','512m','--user',f'{os.getuid()}:{os.getgid()}',
            '--env-file',str(secret_file),'-e','PYTHONDONTWRITEBYTECODE=1','-e','PYTHONPATH=/repair',
            '--mount',f'type=bind,source={source},target=/repair,readonly',
            '--mount',f'type=bind,source={backup_folder},target=/backup',
            '-w','/repair','--entrypoint','python',stage['Image'],
            '-m','tools.content_review.guarded_repair','--manifest',args.manifest]
    try:
        record['dry_run'] = json.loads(command(base))
        if args.execute:
            record['apply'] = json.loads(command(base + ['--execute','--backup','/backup/bank-before.json']))
            record['repeat'] = json.loads(command(base + ['--execute','--backup','/backup/unused-repeat.json']))
            assert not (backup_folder / 'unused-repeat.json').exists()
    finally:
        secret_file.unlink()
    record.update(after_stage=bank_summary('preview'), after_other_tasks=bank_summary('preview', task_ids),
                  after_production=bank_summary('staging'), after_containers=state())
    (release / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    assert record['after_other_tasks'] == before_other, 'unrelated stage bank writes observed'
    assert record['after_production'] == before_prod, 'production bank changed'
    assert record['after_containers'] == before_state, 'runtime identity/config changed'
    assert record['after_stage']['count'] == before_stage['count']
    assert record['after_stage']['active'] == before_stage['active']
    record['checks_passed'] = True
    (release / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
