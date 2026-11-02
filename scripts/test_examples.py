"""Offline invariants of the published templates. Native loading lives in validate_native.py."""
import json
import os
from pathlib import Path
import unittest

import yaml

from public_formats import BASE_URL, DATASETS

ROOT = Path(__file__).resolve().parents[1]
FULL = ROOT / 'examples/full'
TEXT_SUFFIXES = {'.md', '.py', '.json', '.yaml', '.yml', '.conf', '.txt'}


def published_text():
    """Every text file this repository publishes, except upstream licences and this file."""
    top = [path for path in ROOT.iterdir() if path.is_file()]
    nested = [path for folder in ('.github', 'docs', 'examples', 'schemas', 'scripts')
              for path in (ROOT / folder).rglob('*') if path.is_file()]
    for path in sorted(top + nested):
        if path.suffix in TEXT_SUFFIXES and path != Path(__file__).resolve():
            yield path.relative_to(ROOT).as_posix(), path.read_text(encoding='utf-8')


def rules_of(name):
    lines = [line.strip() for line in (FULL / name).read_text(encoding='utf-8').splitlines()]
    begin, end = lines.index('# >>> AgentRoute managed begin'), lines.index('# <<< AgentRoute managed end')
    return [line.removeprefix('- ') for line in lines[begin + 1:end] if line and not line.startswith('#')]


def position(rules, needle):
    return next(i for i, rule in enumerate(rules) if needle in rule)


class TemplateTests(unittest.TestCase):
    def assert_order(self, rules, marker):
        positions = [position(rules, marker(dataset)) for dataset in DATASETS]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(position(rules, '198.18.0.0/15'), position(rules, 'fc00::/7'))
        self.assertLess(position(rules, 'fc00::/18'), position(rules, 'fc00::/7'))
        self.assertLess(position(rules, 'fc00::/7'), positions[0])

    def test_ini_templates_order_and_resolver_routes(self):
        for name in ('surge.conf', 'shadowrocket.conf'):
            with self.subTest(name=name):
                rules = rules_of(name)
                self.assert_order(rules, lambda d: 'RULE-SET,' + BASE_URL + 'surge/' + d + '.list,')
                self.assertRegex(rules[position(rules, '223.5.5.5/32')], ',DIRECT,no-resolve$')
                self.assertRegex(rules[position(rules, '1.1.1.1/32')], ',PROXY,no-resolve$')
                self.assertNotIn('no-resolve', rules[position(rules, 'surge/cn-ip.list')])
                self.assertTrue(rules[-1].startswith('FINAL,PROXY'))
                self.assertEqual(sum(rule.startswith('FINAL') for rule in rules), 1)

    def test_shadowrocket_has_no_nested_extended_matching(self):
        self.assertFalse(any('extended-matching' in rule for rule in rules_of('shadowrocket.conf')))

    def test_shadowrocket_dns_paths(self):
        text = (FULL / 'shadowrocket.conf').read_text(encoding='utf-8')
        general = dict(line.split(' = ', 1) for line in text[text.index('[General]'):text.index('[Rule]')].splitlines()
                       if ' = ' in line and not line.startswith('#'))
        for key in ('dns-server', 'fallback-dns-server'):
            self.assertTrue(all(url.endswith('#proxy') for url in general[key].split(', ')), key)
        for key in ('direct-dns-server', 'proxy-dns-server'):
            self.assertNotIn('#proxy', general[key], key)
            self.assertIn('223.5.5.5', general[key], key)
        self.assertNotIn('bypass-system', general)
        host = text[text.index('[Host]'):]
        for name in ('*.lan', '*.local', '*.home.arpa'):
            self.assertIn(name + ' = server:system', host)

    def test_mihomo_template(self):
        config = yaml.safe_load((FULL / 'mihomo.yaml').read_text(encoding='utf-8'))
        rules = config['rules']
        self.assert_order(rules, lambda d: 'RULE-SET,sr-' + d + ',')
        self.assertEqual(rules[-1], 'MATCH,PROXY')
        self.assertNotIn('no-resolve', rules[position(rules, 'sr-cn-ip')])
        self.assertEqual(rules, rules_of('mihomo.yaml'))
        for provider, dataset in zip(('sr-' + d for d in DATASETS), DATASETS):
            self.assertEqual(config['rule-providers'][provider]['url'], BASE_URL + 'mihomo/' + dataset + '.yaml')
            self.assertEqual(config['rule-providers'][provider]['interval'], 86400)
        dns = config['dns']
        self.assertTrue(dns['respect-rules'])
        self.assertTrue(dns['proxy-server-nameserver'])
        self.assertTrue(all(url.endswith('#PROXY') for url in dns['nameserver']))
        self.assertTrue(all(url.endswith('#DIRECT') for url in dns['proxy-server-nameserver']))
        self.assertEqual(dns['nameserver-policy']['rule-set:sr-private'], ['system'])
        self.assertIn('rule-set:sr-private', dns['fake-ip-filter'])
        self.assertNotIn('fc00::/7', config['sniffer']['skip-dst-address'])

    def test_sing_box_template(self):
        config = json.loads((FULL / 'sing-box.json').read_text(encoding='utf-8'))
        rules = config['route']['rules']
        tags = {item['tag'] for item in config['route']['rule_set']}
        self.assertEqual(tags, {'sr-' + d for d in DATASETS} | {'sr-non-cn-ip'})
        self.assertEqual(rules[0], {'port': 53, 'action': 'hijack-dns'})
        sniff = [i for i, rule in enumerate(rules) if rule.get('action') == 'sniff']
        self.assertEqual(len(sniff), 2)
        final_domain_rules = [rule['rule_set'][0] for rule in rules[sniff[-1] + 1:]]
        self.assertEqual(final_domain_rules, ['sr-' + d for d in DATASETS])
        first_cn = next(i for i, rule in enumerate(rules) if rule.get('rule_set') == ['sr-cn-ip'])
        self.assertGreater(first_cn, sniff[-1])
        dns_rules = config['dns']['rules']
        evaluate = next(i for i, rule in enumerate(dns_rules) if rule.get('action') == 'evaluate')
        self.assertEqual(dns_rules[evaluate + 1]['rule_set'], ['sr-non-cn-ip'])
        self.assertEqual(dns_rules[evaluate + 2]['action'], 'respond')
        self.assertEqual(dns_rules[evaluate + 3]['server'], 'dns-fake')
        self.assertEqual(config['dns']['rules'][1], {'rule_set': ['sr-private'], 'server': 'dns-local'})


class PublishedTextTests(unittest.TestCase):
    def test_published_text_has_no_internal_wording(self):
        names = dict(published_text())
        for expected in ('README.md', 'NOTICE.md', 'sources.json', 'docs/SYNC.md', 'examples/full/surge.conf',
                         'schemas/index.schema.json', 'scripts/public_formats.py', '.github/workflows/run.yml'):
            self.assertIn(expected, names)
        for name, text in names.items():
            with self.subTest(name=name):
                self.assertNotRegex(text, '按用户(要求|指定)')
                # A released GitHub name can be registered by anyone, so it must never be read from again.
                self.assertNotIn('heibai0502', text.lower())

    def test_published_text_has_no_private_words(self):
        # The maintainer supplies the word list; it never belongs in this public repository.
        source = os.environ.get('AGENTROUTE_PRIVATE_WORDS_FILE')
        if not source:
            self.skipTest('no private word list supplied')
        words = [line.strip().lower() for line in Path(source).read_text(encoding='utf-8').splitlines() if line.strip()]
        self.assertTrue(words)
        # File names only: test output can end up in public logs.
        self.assertEqual([name for name, text in published_text() if any(word in text.lower() for word in words)], [])


if __name__ == '__main__':
    unittest.main()
