"""Unsafe or inconsistent source/CI identity must fail before Docker runs."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_git_images import read_inputs


class BuildInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sha = 'a' * 40
        data = b'educational Git archive fixture'
        name = f'diagnostic-service-{self.sha}.tar'
        (self.root / name).write_bytes(data)
        self.manifest = {
            'target': {'domain': 'stage.algolab.me', 'compose_project': 'algo-preview'},
            'status': 'prepared_git_sources_only', 'deployment_performed': False,
            'secrets_included': False, 'sources': {'diagnostic-service': {
                'commit_sha': self.sha, 'source_ref': 'CEO', 'pushed_commit_verified': True,
                'archive': name, 'archive_bytes': len(data),
                'archive_sha256': hashlib.sha256(data).hexdigest(),
            }},
        }
        self.gates = {'diagnostic-service': {'head_sha': self.sha, 'status': 'completed',
                                            'conclusion': 'success'}}

    def save(self):
        raw = json.dumps(self.manifest).encode()
        (self.root / 'source-manifest.json').write_bytes(raw)
        (self.root / 'source-manifest.sha256').write_text(hashlib.sha256(raw).hexdigest())
        (self.root / 'ci-gates.json').write_text(json.dumps(self.gates))

    def test_exact_prepared_stage_inputs_accepted(self):
        self.save()
        self.assertEqual(read_inputs(self.root, ['diagnostic-service']), self.manifest)

    def test_production_target_rejected(self):
        self.manifest['target']['compose_project'] = 'algo-staging'
        self.save()
        with self.assertRaises(ValueError): read_inputs(self.root, ['diagnostic-service'])

    def test_wrong_or_failed_ci_rejected(self):
        for key, value in [('head_sha', 'b' * 40), ('conclusion', 'failure'), ('status', 'in_progress')]:
            with self.subTest(key=key):
                gate = self.gates['diagnostic-service']
                previous = gate[key]; gate[key] = value
                self.save()
                with self.assertRaises(ValueError): read_inputs(self.root, ['diagnostic-service'])
                gate[key] = previous

    def test_changed_archive_rejected(self):
        self.save()
        (self.root / self.manifest['sources']['diagnostic-service']['archive']).write_bytes(b'changed')
        with self.assertRaises(ValueError): read_inputs(self.root, ['diagnostic-service'])

    def test_archive_cannot_escape_input_directory(self):
        self.manifest['sources']['diagnostic-service']['archive'] = '../other.tar'
        self.save()
        with self.assertRaises(ValueError): read_inputs(self.root, ['diagnostic-service'])

    def test_manifest_checksum_and_target_scope_required(self):
        self.save()
        (self.root / 'source-manifest.json').write_text('{}')
        with self.assertRaises(ValueError): read_inputs(self.root, ['diagnostic-service'])
        for services in [[], ['auth-service'], ['diagnostic-service', 'diagnostic-service']]:
            with self.subTest(services=services):
                with self.assertRaises(ValueError): read_inputs(self.root, services)
