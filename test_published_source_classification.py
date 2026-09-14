import ast
import hashlib
import re
import unittest
from pathlib import Path
from typing import Any


class PublishedClassificationTest(unittest.TestCase):
    def setUp(self):
        names = {'published_defect_reports_for_vehicle', 'build_vin_recall_check'}
        source = ast.parse(Path(__file__).with_name('server_core.py').read_text())
        self.ns = dict(Any=Any, hashlib=hashlib,
            canonical_catalog_make=lambda s: str(s).lower(),
            normalize_catalog_text=lambda s: str(s or '').lower(),
            catalog_model_matches=lambda entry, model: entry['model'] == model,
            catalog_year_value=lambda n: int(n or 0),
            safe_public_source_url=lambda s: str(s),
            normalize_vehicle_vin=lambda s: str(s).upper(),
            mask_vehicle_vin=lambda s: s[:3]+'********'+s[-6:],
            vin_verification_source=lambda s: ('Costruttore', 'https://example.com/vin'),
            vin_make_candidates=lambda s: ('audi',),
            VIN_FORMAT=re.compile(r'^[A-HJ-NPR-Z0-9]{17}$'))
        exec(compile(ast.Module(body=[n for n in source.body
            if isinstance(n, ast.FunctionDef) and n.name in names],
            type_ignores=[]), '<classification>', 'exec'), self.ns)

    def test_source_origin_does_not_certify_recall(self):
        types = {'official_candidate': 'official_notice',
            'manufacturer_candidate': 'manufacturer_support',
            'community_candidate': 'community_source',
            'independent_candidate': 'independent_reliability'}
        for source_type, expected in types.items():
            with self.subTest(source_type=source_type):
                self.ns['_published_defect_source_rows'] = lambda: [dict(
                    make='Audi', model='A1', year=2011, engine='1.6 TDI',
                    source_type=source_type, source_url='https://example.com/source')]
                reports = self.ns['published_defect_reports_for_vehicle'](
                    'Audi', 'A1', 2011, '1.6 TDI')
                self.assertEqual(reports[0]['sourceType'], expected)
                check = self.ns['build_vin_recall_check'](
                    'WAUZZZ8X0BB000001', 'Audi', reports)
                self.assertEqual(check['possibleRecallCount'], 0)

    def test_curated_recall_remains_possible_vin_match_only(self):
        check = self.ns['build_vin_recall_check']('WAUZZZ8X0BB000001', 'Audi',
            [{'sourceType':'official_recall'}])
        self.assertEqual(check['possibleRecallCount'], 1)
        self.assertEqual(check['status'], 'possible_match')


if __name__ == '__main__':
    unittest.main()
