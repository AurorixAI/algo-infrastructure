#!/usr/bin/env python3
"""Build selected Linux/amd64 stage candidate images; never switch containers.

Inputs are the unchanged output of prepare_git_release.py plus ci-gates.json
containing successful exact-SHA CI metadata for each selected repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile


SERVICES = {'diagnostic-service': 'diagnostic-service', 'exam-service': 'exam-service',
            'frontend': 'algo-front'}
TARGET = {'domain': 'stage.algolab.me', 'compose_project': 'algo-preview'}


def frontend_build_args() -> list[str]:
    # api.ts appends /api/v1 itself; these values must be origins.
    args = []
    for name in ('AUTH', 'EXAM', 'DIAG'):
        args += ['--build-arg', f'NEXT_PUBLIC_{name}_API_URL=https://stage.algolab.me']
    return args + ['--build-arg', 'CONTENT_API_URL=http://algo-preview-content:8004']


def read_inputs(root: Path, selected: list[str]) -> dict:
    if not selected or len(set(selected)) != len(selected) or set(selected) - SERVICES.keys():
        raise ValueError('Select unique diagnostic-service, exam-service or frontend targets')
    raw = (root / 'source-manifest.json').read_bytes()
    expected = (root / 'source-manifest.sha256').read_text().split()[0]
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Source manifest checksum differs')
    manifest = json.loads(raw)
    if (manifest.get('target') != TARGET or manifest.get('status') != 'prepared_git_sources_only'
            or manifest.get('deployment_performed') is not False
            or manifest.get('secrets_included') is not False):
        raise ValueError('Require prepared, secret-free stage Git inputs')
    gates = json.loads((root / 'ci-gates.json').read_text())
    for service in selected:
        repo = SERVICES[service]
        source = manifest['sources'][repo]
        sha = source['commit_sha']
        if (not re.fullmatch('[0-9a-f]{40}', sha)
                or source.get('source_ref') != 'CEO' or source.get('pushed_commit_verified') is not True
                or source['archive'] != f'{repo}-{sha}.tar'):
            raise ValueError(f'{repo}: invalid pushed CEO identity')
        archive = root / source['archive']
        if (archive.stat().st_size != source['archive_bytes']
                or hashlib.sha256(archive.read_bytes()).hexdigest() != source['archive_sha256']):
            raise ValueError(f'{repo}: archive differs')
        gate = gates.get(repo, {})
        if (gate.get('head_sha') != sha or gate.get('status') != 'completed'
                or gate.get('conclusion') != 'success'):
            raise ValueError(f'{repo}: successful exact-SHA CI required')
    return manifest


def build(root: Path, selected: list[str]) -> dict:
    manifest = read_inputs(root, selected)
    output = root / 'candidate-images.json'
    contexts = root / 'build-contexts'
    if output.exists() or contexts.exists():
        raise ValueError('Build output already exists; use a fresh candidate directory')
    contexts.mkdir()
    images = {}
    for service in selected:
        repo = SERVICES[service]
        source = manifest['sources'][repo]
        context = contexts / repo
        context.mkdir()
        with tarfile.open(root / source['archive']) as archive:
            archive.extractall(context, filter='data')
        if not (context / 'Dockerfile').is_file():
            raise ValueError(f'{repo}: Dockerfile absent')
        sha, digest = source['commit_sha'], source['archive_sha256']
        tag = f'algolab-git-candidate-{service}:{sha[:12]}-{digest[:12]}'
        command = ['docker', 'build', '--platform', 'linux/amd64', '--tag', tag,
                   '--label', 'org.opencontainers.image.revision=' + sha,
                   '--label', 'io.algolab.source.archive.sha256=' + digest]
        if service == 'frontend':
            command += frontend_build_args()
        command.append(str(context))
        with (root / f'build-{service}.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', tag], text=True))[0]
        labels = image['Config']['Labels']
        if (image['Os'] != 'linux' or image['Architecture'] != 'amd64'
                or labels.get('org.opencontainers.image.revision') != sha
                or labels.get('io.algolab.source.archive.sha256') != digest):
            raise ValueError(f'{repo}: built image identity differs')
        images[service] = {'image_tag': tag, 'image_id': image['Id'], 'source_sha': sha,
                           'source_archive_sha256': digest, 'platform': 'linux/amd64'}
        print(json.dumps({'built': service, **images[service]}), flush=True)
    result = {'target': TARGET, 'status': 'images_built_acceptance_pending',
              'images': images, 'deployment_performed': False}
    output.write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('--service', required=True, action='append', choices=SERVICES)
    args = parser.parse_args()
    build(args.inputs.resolve(), args.service)
