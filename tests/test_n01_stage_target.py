"""A wrong stage identity must fail before any bank mutation is possible."""
import copy
import unittest
from scripts.n01_stage_bank import stage_database_url


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


if __name__ == '__main__': unittest.main()
