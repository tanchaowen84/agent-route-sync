"""Metadata, domain projection and template tests. The CI native job decodes real binaries."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import ValidationError

from build_rules import ROOT, build
from check_contracts import validate_generated
from rule_catalog import BASE_URL, RESOURCE_BY_ID, format_variants
from rule_fixtures import source_inputs
from validate_native import candidate_replacements, localized_mihomo, localized_sing_box, to_local_rule_sets


class VariantContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'release'
        self.manifest = build(source_inputs(), self.root)
        self.index = json.loads((self.root / 'index.json').read_bytes())

    def add_variants(self):
        counts = {item['id']: item['resources']['surge']['entries']
                  for item in self.index['datasets'] + self.index['protections']}
        counts.update({item['id']: item['entries'] for item in self.index['helpers']})
        variants = []
        for identity, fmt, path in format_variants():
            output = self.root / path
            if fmt == 'domain-set' and not output.exists():
                lines = (self.root / RESOURCE_BY_ID[identity].path('surge')).read_text().splitlines()
                output.write_bytes(('\n'.join(row.replace('DOMAIN-SUFFIX,', '.').removeprefix('DOMAIN,')
                                              for row in lines) + '\n').encode())
            elif fmt != 'domain-set':
                output.write_bytes(path.encode())  # Opaque bytes for the manifest/metadata layer only.
            digest = hashlib.sha256(output.read_bytes()).hexdigest()
            self.manifest['files'][path] = digest
            variants.append({'id': identity, 'format': fmt, 'path': path, 'url': BASE_URL + path,
                             'sha256': digest, 'entries': counts[identity]})
        self.index['format_variants'] = variants
        self.save()

    def save(self):
        data = json.dumps(self.index).encode()
        (self.root / 'index.json').write_bytes(data)
        self.manifest['files']['index.json'] = hashlib.sha256(data).hexdigest()
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def replace_content(self, path, data):
        (self.root / path).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        self.manifest['files'][path] = digest
        next(r for r in self.index['format_variants'] if r['path'] == path)['sha256'] = digest
        self.save()

    def test_complete_variants_order_independent_reuse_three_files(self):
        originals = {p.name: p.read_bytes() for p in self.root.glob('*.domains')}
        self.assertEqual(set(originals), {'private.domains', 'direct.domains', 'reject.domains'})
        self.add_variants()
        self.index['format_variants'].reverse()
        self.save()
        _, result = validate_generated(self.root, require_variants=True)
        self.assertEqual(result['format_variants'], 16)
        self.assertEqual(result['verified_files'], 51)
        for path, original in originals.items():
            self.assertEqual((self.root / path).read_bytes(), original)

    def test_legacy_and_unindexed_variants(self):
        self.assertEqual(validate_generated(self.root, historical=True)[1]['format_variants'], 0)
        with self.assertRaisesRegex(ValueError, 'Missing format_variants'):
            validate_generated(self.root, require_variants=True)
        self.add_variants()
        self.index.pop('format_variants')
        self.save()
        with self.assertRaisesRegex(ValueError, 'Missing format_variants'):
            validate_generated(self.root, historical=True)

    def test_partial_missing_and_duplicate_identities(self):
        self.add_variants()
        records = self.index['format_variants']
        for replacement in ([], records[:-1], [*records[:-1], dict(records[0], entries=records[0]['entries'] + 1)],
                            [*records[:-1], dict(records[-1], id='cn-ip')]):
            with self.subTest(size=len(replacement)):
                self.index['format_variants'] = replacement
                self.save()
                with self.assertRaises((ValidationError, ValueError)):
                    validate_generated(self.root)

    def test_wrong_format_path_url_digest_and_count(self):
        self.add_variants()
        first, second, *_ = self.index['format_variants']
        for key, value in (('format', 'yaml'), ('id', 'unexpected'), ('path', second['path']),
                           ('url', second['url']), ('sha256', second['sha256']), ('entries', first['entries'] + 1)):
            with self.subTest(field=key):
                original = first[key]
                first[key] = value
                self.save()
                with self.assertRaises((ValidationError, ValueError)):
                    validate_generated(self.root)
                first[key] = original

    def test_unowned_variant_and_empty_binary(self):
        self.add_variants()
        path = 'mihomo/webrtc-guard.mrs'
        (self.root / path).write_bytes(b'extra')
        self.manifest['files'][path] = hashlib.sha256(b'extra').hexdigest()
        self.save()
        with self.assertRaisesRegex(ValueError, 'Unrecognized public files'):
            validate_generated(self.root)
        (self.root / path).unlink()
        self.manifest['files'].pop(path)
        self.replace_content('mihomo/private.mrs', b'')
        with self.assertRaisesRegex(ValueError, 'Empty variant'):
            validate_generated(self.root)

    def test_exact_suffix_and_duplicate_domain_set_rules(self):
        self.add_variants()
        for rows in (['router.asus.com', 'ts.net', '.lan'], ['.router.asus.com', '.ts.net', '.lan'],
                     ['router.asus.com', '.lan', '.lan'], ['router.asus.com', '.lan']):
            with self.subTest(rows=rows):
                self.replace_content('private.domains', '\n'.join(rows).encode())
                with self.assertRaisesRegex(ValueError, 'DOMAIN-SET'):
                    validate_generated(self.root)
        self.replace_content('private.domains', b'// comment\n.TS.NET\nROUTER.ASUS.COM\n\n.lan\n')
        validate_generated(self.root, require_variants=True)

    def test_full_templates_use_selected_binary_files_and_classical_guard(self):
        self.add_variants()
        replacements = candidate_replacements(self.root)
        examples = ROOT / 'examples/full'
        temp = Path(self.temp.name)
        mihomo = localized_mihomo(examples / 'mihomo.yaml', self.root, temp, replacements)
        providers = mihomo['rule-providers']
        self.assertEqual(providers['sr-webrtc-guard']['format'], 'yaml')
        actual_paths = set()
        for provider in providers.values():
            if provider['format'] == 'mrs':
                actual_paths.add((temp / provider['path']).read_bytes().decode())
        self.assertEqual(actual_paths, {r['path'] for r in self.index['format_variants'] if r['format'] == 'mrs'})
        config = localized_sing_box(examples / 'sing-box.json', self.root, temp)
        original_rules = copy.deepcopy(config['route']['rules'])
        binary_sets = to_local_rule_sets(config, self.root, replacements)['route']['rule_set']
        self.assertEqual(config['route']['rules'], original_rules)
        self.assertTrue(all(r['type'] == 'local' and r['format'] == 'binary' for r in binary_sets))
        self.assertEqual({Path(r['path']).relative_to(self.root).as_posix() for r in binary_sets},
                         {r['path'] for r in self.index['format_variants'] if r['format'] == 'srs'})
