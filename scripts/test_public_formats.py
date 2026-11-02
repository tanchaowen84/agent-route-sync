"""Contract tests for cross-client semantics, safe IP fallback and coherent updates."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from build_rules import build
from public_formats import DATASETS, outside_networks, public_china_networks
import test_build_rules


class PublicFormatTests(unittest.TestCase):
    def test_exact_suffix_order_and_native_payloads(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = build(test_build_rules.SourceGenerationTests().fixture(), root)
            index = json.loads((root / 'index.json').read_text())
            self.assertEqual(index['order'][2:-1], list(DATASETS))
            self.assertEqual(index['generated_at_utc'], manifest['generated_at_utc'])
            for entry in index['datasets']:
                for resource in entry['resources'].values():
                    self.assertEqual(resource['sha256'], manifest['files'][resource['path']])
                    self.assertEqual(resource['sha256'], hashlib.sha256((root / resource['path']).read_bytes()).hexdigest())
            self.assertEqual((root / 'surge/private.list').read_text().splitlines(),
                             ['DOMAIN,router.asus.com', 'DOMAIN-SUFFIX,lan', 'DOMAIN-SUFFIX,ts.net'])
            payload = [json.loads(line.strip()[2:]) for line in (root / 'mihomo/private.yaml').read_text().splitlines()[1:]]
            self.assertEqual(payload, ['router.asus.com', '+.lan', '+.ts.net'])
            source = json.loads((root / 'sing-box/private.json').read_text())
            self.assertEqual(source['rules'], [{'domain': ['router.asus.com']}, {'domain_suffix': ['lan', 'ts.net']}])
            self.assertNotIn('IP-CIDR', (root / 'surge/direct.list').read_text())
            self.assertIn('IP-CIDR,', (root / 'direct.list').read_text())
            self.assertNotIn('192.168.', (root / 'surge/cn-ip.list').read_text())
            self.assertIn('DOMAIN-SUFFIX,asus.com', (root / 'surge/proxy.list').read_text())
            self.assertFalse(index['contains_nodes'])

    def test_outside_networks_is_the_exact_complement(self):
        inside = public_china_networks(['1.0.0.0/24', '2400::/32'], minimum=1)
        outside = outside_networks(inside)
        for version, total in ((4, 2 ** 32), (6, 2 ** 128)):
            size = sum(n.num_addresses for n in inside + outside if n.version == version)
            self.assertEqual(size, total)
        self.assertFalse(any(a.overlaps(b) for a in inside for b in outside if a.version == b.version))

    def test_helper_is_published_and_indexed_outside_the_datasets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = build(test_build_rules.SourceGenerationTests().fixture(), root)
            index = json.loads((root / 'index.json').read_text())
            self.assertEqual(index['helpers'][0]['sha256'], manifest['files']['sing-box/non-cn-ip.json'])
            self.assertEqual(len(index['datasets']), len(DATASETS))
            self.assertFalse((root / 'docs').exists())

    def test_no_empty_sing_box_conditions(self):
        with tempfile.TemporaryDirectory() as folder:
            build(test_build_rules.SourceGenerationTests().fixture(), Path(folder))
            for path in (Path(folder) / 'sing-box').glob('*.json'):
                for rule in json.loads(path.read_text())['rules']:
                    self.assertTrue(rule)
                    self.assertTrue(all(rule.values()))

    def test_cn_ip_rejects_missing_family_and_broad_fake_routes(self):
        for values in (['1.0.0.0/24'], ['1.0.0.0/24', '::/0'],
                       ['1.0.0.0/24', '198.18.0.1/32', '2400::/32'],
                       ['1.0.0.0/24', '192.168.1.0/24', '2400::/32']):
            with self.subTest(values=values), self.assertRaises(ValueError):
                public_china_networks(values, minimum=1)
        values = public_china_networks(['1.0.0.0/24', '2400::/32', '10.0.0.0/8', 'fc00::/7'], minimum=1)
        self.assertEqual(list(map(str, values)), ['1.0.0.0/24', '2400::/32'])

    def test_cn_ip_rejects_a_prefix_wider_than_any_real_allocation(self):
        for values in (['32.0.0.0/3', '2400::/32'], ['1.0.0.0/24', '2000::/3'],
                       ['4.0.0.0/7', '2400::/32'], ['1.0.0.0/24', '2400::/15']):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, 'china_ip_prefix_too_broad'):
                public_china_networks(values, minimum=1)
        widest = public_china_networks(['36.0.0.0/8', '2400::/16'], minimum=1)
        self.assertEqual(list(map(str, widest)), ['36.0.0.0/8', '2400::/16'])


if __name__ == '__main__':
    unittest.main()
