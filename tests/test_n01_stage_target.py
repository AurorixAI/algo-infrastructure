"""A wrong stage identity must fail before any bank mutation is possible."""
import copy
import contextlib
import io
import json
import sys
import types
import unittest
from unittest.mock import patch
from scripts.n01_stage_bank import stage_database_url, exam_snapshot_summary, active_diagnostic_summary, SCOPES


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

    def test_wave_five_scope_is_bounded_and_disjoint_without_historical_answer_ids(self):
        wave5 = SCOPES['data/content_repairs/n01-2026-10-05-w5.json']
        self.assertEqual(len(wave5), 22)
        self.assertEqual(len(set(wave5)), 22)
        previous = set(v for key, values in SCOPES.items() if not key.endswith('w5.json') for v in values)
        self.assertFalse(previous.intersection(wave5))
        self.assertNotIn('G11_TB_§9_3_6', wave5)
        self.assertNotIn('ds_llm_7c36694c8cba', wave5)

    def test_active_issued_task_guard_reads_only_and_returns_aggregates(self):
        states = {
            'diag:session:a': {'phase':'warmup','current_task_id':'target','used_task_ids':[]},
            'diag:session:b': {'phase':'navigation','current_task_id':'other','used_task_ids':['target']},
            'diag:session:c': {'phase':'completed','current_task_id':'target','used_task_ids':['target']},
            'diag:session:a:answer-lock': 'non-json lock token',
            'diag:session:expired': None,
        }
        class ReadOnlyRedis:
            def scan_iter(self, **kwargs):
                self.kwargs = kwargs
                return iter(states)
            def get(self, key):
                value = states[key]
                return None if value is None else json.dumps(value)
        fake = ReadOnlyRedis()
        module = types.ModuleType('src.core.redis_client')
        module.get_redis_client = lambda:fake
        def run(argv, *, input):
            self.assertEqual(argv,['docker','exec','-i','algo-preview-diagnostic','python','-'])
            stdout = io.StringIO()
            with patch.dict(sys.modules, {'src.core.redis_client':module}), contextlib.redirect_stdout(stdout):
                exec(input,{})
            return stdout.getvalue()
        with patch('scripts.n01_stage_bank.command',side_effect=run):
            result = active_diagnostic_summary(['target'])
        self.assertEqual(result,{'active_sessions':2,'matched_current_tasks':1,'matched_used_tasks':1})
        self.assertEqual(fake.kwargs,{'match':'diag:session:*','count':100})


if __name__ == '__main__': unittest.main()
