"""Common probe coverage, precedence and compatibility; not device leak tests."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import yaml

from build_rules import build
from public_formats import BASE_URL, export_webrtc_guard
from test_build_rules import SourceGenerationTests
from test_examples import FULL, rules_of


def text_match(lines, host, port):
    for line in lines:
        kind, value = line.split(',')
        if kind == 'DST-PORT' and port == int(value):
            return True
        if kind == 'DOMAIN-KEYWORD' and value in host:
            return True
        if kind not in ('DST-PORT', 'DOMAIN-KEYWORD'):
            raise ValueError('unexpected guard condition')
    return False


def source_match(rules, host, port):
    # sing-box uses AND between different fields, OR between separate rules.
    return any(all((port in values if key == 'port' else any(v in host for v in values))
                   for key, values in rule.items()) for rule in rules)


class WebRTCGuardTests(unittest.TestCase):
    def test_three_formats_have_same_positive_and_negative_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files, entry = export_webrtc_guard(root)
            mihomo = yaml.safe_load((root / 'mihomo/webrtc-guard.yaml').read_text())['payload']
            surge = (root / 'surge/webrtc-guard.list').read_text().splitlines()
            source = json.loads((root / 'sing-box/webrtc-guard.json').read_text())['rules']
            self.assertEqual(mihomo, surge)
            self.assertTrue(all(set(r) <= {'port', 'domain_keyword'} for r in source))
            cases = [(host, port, True) for host in ('unlisted.example', '203.0.113.8', '2001:db8::8')
                     for port in (3478, 5349, 19302, 19303, 19304, 19305, 19306, 19307, 19308, 19309)]
            cases += [('stun.custom.example', 45678, True), ('api.anthropic.com', 443, False),
                      ('www.baidu.com', 443, False), ('unlisted.example', 19301, False),
                      ('203.0.113.8', 19310, False), ('2001:db8::8', 45678, False)]
            for host, port, expected in cases:
                with self.subTest(host=host, port=port):
                    self.assertEqual(text_match(surge, host, port), expected)
                    self.assertEqual(source_match(source, host, port), expected)
            for resource in entry['resources'].values():
                self.assertEqual(resource['sha256'], files[resource['path']])
                self.assertEqual(resource['sha256'], hashlib.sha256((root / resource['path']).read_bytes()).hexdigest())

    def test_guard_is_separate_from_existing_domain_datasets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = build(SourceGenerationTests().fixture(), root)
            index = json.loads((root / 'index.json').read_text())
            self.assertEqual([d['id'] for d in index['datasets']], ['private', 'reject', 'proxy', 'direct', 'cn-ip'])
            guard, = index['protections']
            self.assertEqual((guard['id'], guard['action'], guard['mihomo_behavior']), ('webrtc-guard', 'REJECT', 'classical'))
            for r in guard['resources'].values():
                self.assertEqual(r['sha256'], manifest['files'][r['path']])
            self.assertLess(index['order'].index('webrtc-guard'), index['order'].index('dns-server-paths'))
            self.assertLess(index['order'].index('webrtc-guard'), index['order'].index('private'))
            for name in ('private', 'reject', 'proxy', 'direct'):
                self.assertNotIn('DST-PORT', (root / f'mihomo/{name}.yaml').read_text())

    def test_templates_reject_before_public_ip_and_business_exceptions(self):
        for name in ('mihomo.yaml', 'surge.conf', 'shadowrocket.conf'):
            with self.subTest(template=name):
                rules = rules_of(name)
                guard = next(i for i, r in enumerate(rules) if 'webrtc-guard' in r)
                self.assertIn(',REJECT', rules[guard])
                # Public resolver exemptions must not allow their STUN ports through.
                public = next(i for i, r in enumerate(rules) if '223.5.5.5/32' in r)
                private = next(i for i, r in enumerate(rules) if 'RULE-SET' in r and 'private' in r)
                self.assertLess(guard, public)
                self.assertLess(guard, private)
                # Approved real LAN traffic retains its route; this is not all-device UDP blocking.
                self.assertLess(next(i for i, r in enumerate(rules) if '192.168.0.0/16' in r), guard)
        c = json.loads((FULL / 'sing-box.json').read_text())
        rules = c['route']['rules']
        guards = [i for i, r in enumerate(rules) if r.get('rule_set') == ['sr-webrtc-guard']]
        self.assertEqual(len(guards), 2)
        self.assertTrue(all(rules[i]['action'] == 'reject' for i in guards))
        self.assertLess(guards[0], next(i for i, r in enumerate(rules) if '223.5.5.5/32' in r.get('ip_cidr', [])))
        # Recheck after sniffing reveals a previously unknown hostname.
        sniff_end = max(i for i, r in enumerate(rules) if r['action'] == 'sniff')
        self.assertEqual(guards[1], sniff_end + 1)
        provider = next(p for p in c['route']['rule_set'] if p['tag'] == 'sr-webrtc-guard')
        self.assertEqual(provider['url'], BASE_URL + 'sing-box/webrtc-guard.json')


if __name__ == '__main__':
    unittest.main()
