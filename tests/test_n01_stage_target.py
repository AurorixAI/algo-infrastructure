"""A wrong stage identity must fail before any bank mutation is possible."""
import copy
import unittest
from unittest.mock import patch
from scripts.n01_stage_bank import stage_database_url, exam_snapshot_summary, SCOPES


class StageTargetTests(unittest.TestCase):
    def setUp(self):
        self.stage = {'State': {'Running': True, 'Health': {'Status': 'healthy'}},
                      'NetworkSettings': {'Networks': {'algo-preview-network': {}}},
                      'Config': {'Env': ['DATABASE_URL=postgresql://algo:test@algo-preview-content-db:5432/algo_content']}}
        self.db = {'NetworkSettings': {'Networks': {'algo-preview-network': {}}}}

    def test_accepts_only_verified_healthy_preview(self):
        self.assertEqual(stage_database_url(self.stage, self.db), self.stage['Config']['Env'][0].split('=',1)[1])

    def test_rejects_production_host_even_with_preview_network(self):
        self.stage['Config']['Env'] = ['DATABASE_URL=postgresql://algo:test@algo-staging-content-db:5432/algo_content']
        with self.assertRaises(ValueError): stage_database_url(self.stage, self.db)

    def test_shared_alias_cannot_hide_wrong_network(self):
        self.stage['Config']['Env'] = ['DATABASE_URL=postgresql://algo:test@content-db:5432/algo_content']
        self.db['NetworkSettings']['Networks'] = {'algo-staging-network': {}}
        with self.assertRaises(ValueError): stage_database_url(self.stage, self.db)

    def test_unhealthy_application_blocks_application(self):
        self.stage['State']['Health']['Status'] = 'unhealthy'
        with self.assertRaises(ValueError): stage_database_url(self.stage, self.db)

    def test_rejects_wrong_database_or_external_host(self):
        for url in ('postgresql://algo:test@algo-preview-content-db/algo_auth',
                    'postgresql://algo:test@external.invalid/algo_content'):
            with self.subTest(url=url):
                stage = copy.deepcopy(self.stage)
                stage['Config']['Env'] = ['DATABASE_URL=' + url]
                with self.assertRaises(ValueError): stage_database_url(stage, self.db)

    def test_snapshot_preflight_reads_only_aggregates_and_escapes_ids(self):
        with patch('scripts.n01_stage_bank.command', return_value='{"matched_tasks":0,"incomplete_tasks":0,"variants_md5":"x"}') as run:
            result = exam_snapshot_summary(["a'b"])
        argv = run.call_args.args[0]
        sql = run.call_args.kwargs['input']
        self.assertIn('algo-preview-exam-db', argv)
        self.assertIn("'a''b'", sql)
        self.assertTrue(sql.startswith('BEGIN READ ONLY;'))
        self.assertNotIn('exam_sessions', sql)
        self.assertEqual(result['matched_tasks'], 0)

    def test_wave_four_scope_is_bounded_and_disjoint(self):
        wave4 = SCOPES['data/content_repairs/n01-2026-10-05-w4.json']
        self.assertEqual(len(wave4), 40)
        self.assertEqual(len(set(wave4)), 40)
        previous = set(v for key, values in SCOPES.items() if not key.endswith('w4.json') for v in values)
        self.assertFalse(previous.intersection(wave4))


if __name__ == '__main__': unittest.main()
