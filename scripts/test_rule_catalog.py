"""Verify checked-in catalog views and the single-file distribution from a consumer's side."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rule_catalog import DNS_HELPER, GUARD
from update_rule_catalog import sync_catalog_files


ROOT = Path(__file__).resolve().parents[1]


class RuleCatalogTests(unittest.TestCase):
    def test_checked_in_views_and_regeneration(self):
        sync_catalog_files(ROOT)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('README.md', 'scripts/sync_rules.py', 'schemas/index.schema.json', 'schemas/manifest.schema.json'):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            shutil.copytree(ROOT / 'subscriptions', root / 'subscriptions')

            modifications = [('README.md', '内网直连 `private` | `DIRECT`', '用途错误 | `REJECT`'),
                             ('subscriptions/shadowrocket.json', '"format": "surge"', '"format": "mihomo"'),
                             ('scripts/sync_rules.py', "'mihomo/private.yaml'", "'mihomo/other.yaml'"),
                             ('schemas/index.schema.json', '"const": "ipcidr"', '"const": "classical"'),
                             ('schemas/manifest.schema.json', '"minItems": 5', '"minItems": 6')]
            for name, original, changed in modifications:
                with self.subTest(name=name):
                    path = root / name
                    before = path.read_text(encoding='utf-8')
                    self.assertIn(original, before)
                    path.write_text(before.replace(original, changed, 1), encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'differs from rule_catalog'):
                        sync_catalog_files(root)
                    sync_catalog_files(root, write=True)
                    sync_catalog_files(root)
                    after = path.read_text(encoding='utf-8')
                    if name.endswith('.json'):
                        self.assertEqual(json.loads(after), json.loads(before))
                    else:
                        self.assertEqual(after, before)
            schema_path = root / 'schemas/index.schema.json'
            schema = json.loads(schema_path.read_text(encoding='utf-8'))
            orders = schema['properties']['order']['enum'].copy()
            schema['properties']['order']['enum'].pop()
            schema_path.write_text(json.dumps(schema), encoding='utf-8')
            sync_catalog_files(root, write=True)
            self.assertEqual(json.loads(schema_path.read_text(encoding='utf-8'))['properties']['order']['enum'], orders)

    def test_copied_sync_script_can_run_alone_with_only_the_standard_library(self):
        with tempfile.TemporaryDirectory() as folder:
            standalone = Path(folder) / 'sync_rules.py'
            shutil.copyfile(ROOT / 'scripts/sync_rules.py', standalone)
            code = """
import json, runpy
s = runpy.run_path('sync_rules.py')
known = {'surge/webrtc-guard.list', 'sing-box/non-cn-ip.json'}
print(json.dumps([s['selected']('surge'), s['optional_resources']('all', known)]))
"""
            result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', code], cwd=folder,
                                    text=True, capture_output=True, check=True, timeout=10)
            required, optional = json.loads(result.stdout)
            self.assertEqual(required, ['index.json', 'surge/private.list', 'surge/reject.list',
                                        'surge/proxy.list', 'surge/direct.list', 'surge/cn-ip.list'])
            self.assertEqual(optional, ['surge/webrtc-guard.list', 'sing-box/non-cn-ip.json'])
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ['sync_rules.py'])

    def test_helper_has_its_own_scope_and_no_mihomo_or_surge_resource(self):
        self.assertEqual(DNS_HELPER.path('sing-box'), 'sing-box/non-cn-ip.json')
        for fmt in ('surge', 'mihomo'):
            with self.subTest(fmt=fmt), self.assertRaises(ValueError):
                DNS_HELPER.path(fmt)
        self.assertIsNone(DNS_HELPER.action)
        self.assertEqual(GUARD.path('mihomo'), 'mihomo/webrtc-guard.yaml')
        self.assertEqual(GUARD.mihomo_behavior, 'classical')
