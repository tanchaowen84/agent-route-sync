"""Cross-file contract of a built artifact, including older public v1 generations."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import FormatChecker, ValidationError

from build_rules import build
from check_contracts import format_checker, validate_generated
from rule_fixtures import source_inputs


class ArtifactContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = build(source_inputs(), self.root)
        self.index = json.loads((self.root / 'index.json').read_text(encoding='utf-8'))

    def write_metadata(self):
        index = json.dumps(self.index, ensure_ascii=False).encode()
        (self.root / 'index.json').write_bytes(index)
        self.manifest['files']['index.json'] = hashlib.sha256(index).hexdigest()
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_unknown_v1_metadata_survives(self):
        self.index['future'] = {'status': 'example'}
        self.index['datasets'][0]['resources']['mihomo']['future_setting'] = False
        self.manifest['future'] = [1]
        self.write_metadata()
        _, result = validate_generated(self.root)
        self.assertEqual(result['verified_files'], len(self.manifest['files']))

    def test_actual_format_checkers_are_required(self):
        incomplete = FormatChecker(formats=['ipv4'])
        with patch('check_contracts.FormatChecker', return_value=incomplete), self.assertRaisesRegex(ValueError, 'Missing JSON Schema formats'):
            format_checker()

    def test_malformed_schema_fields(self):
        first = self.index['datasets'][0]
        cases = [
            (self.manifest, 'generated_at_utc', 'invalid time'), (self.index, 'generated_at_utc', '2026-11-21'),
            (first['resources']['surge'], 'url', 'not a URI'),
            (first, 'id', 'reject'), (self.index['datasets'][1], 'action', 'DIRECT'),
            (self.index['datasets'][4], 'mihomo_behavior', 'domain'), (self.index, 'order', []),
        ]
        for obj, key, value in cases:
            with self.subTest(field=key, value=value):
                original = obj[key]
                obj[key] = value
                self.write_metadata()
                with self.assertRaises(ValidationError):
                    validate_generated(self.root)
                obj[key] = original

    def test_same_generation_and_resource_identity(self):
        record = self.index['datasets'][0]['resources']['surge']
        substitute = self.index['datasets'][1]['resources']['surge']
        cases = [
            (self.index, 'generated_at_utc', '2025-01-01T00:00:00Z', 'different generations'),
            (record, 'url', substitute['url'], 'URL'),
            (record, 'path', substitute['path'], 'Expected resource'),
            (record, 'sha256', 'a' * 64, 'digest'),
            (self.index['helpers'][0], 'path', substitute['path'], 'Expected resource'),
            (self.index['protections'][0], 'ports', [80], 'Protection count'),
        ]
        for obj, key, value, error in cases:
            with self.subTest(field=key, error=error):
                original = obj[key]
                obj[key] = value
                self.write_metadata()
                with self.assertRaisesRegex(ValueError, error):
                    validate_generated(self.root)
                obj[key] = original

    def test_agreeing_invented_counts_rejected_by_actual_list(self):
        for resource in self.index['datasets'][0]['resources'].values():
            resource['entries'] += 1
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, 'actual Surge LIST'):
            validate_generated(self.root)

    def test_helper_count_rejected_by_actual_source(self):
        self.index['helpers'][0]['entries'] += 1
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, 'actual prefixes'):
            validate_generated(self.root)

    def test_changed_artifact_and_missing_file(self):
        target = self.root / 'mihomo/private.yaml'
        target.write_bytes(b'other bytes')
        with self.assertRaisesRegex(ValueError, 'bytes do not match'):
            validate_generated(self.root)
        target.unlink()
        with self.assertRaisesRegex(ValueError, 'inventory'):
            validate_generated(self.root)

    def test_extra_file_without_and_with_manifest_entry(self):
        (self.root / 'accidental.txt').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            validate_generated(self.root)
        self.manifest['files']['accidental.txt'] = hashlib.sha256(b'extra').hexdigest()
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, 'Unrecognized public files'):
            validate_generated(self.root)

    def test_missing_legacy_file_even_if_manifest_also_loses_it(self):
        self.manifest['files'].pop('direct.domains')
        (self.root / 'direct.domains').unlink()
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, 'Missing public files'):
            validate_generated(self.root)

    def test_hidden_entries_are_rejected(self):
        for name in ('.gitattributes', '.git', 'surge/.private'):
            with self.subTest(name=name):
                path = self.root / name
                path.mkdir()
                with self.assertRaisesRegex(ValueError, 'Hidden artifact entry'):
                    validate_generated(self.root)
                path.rmdir()

    @unittest.skipIf(os.name == 'nt', 'creating a symlink may require privileges on Windows')
    def test_file_replaced_by_link_is_rejected(self):
        path = self.root / 'direct.list'
        path.unlink()
        path.symlink_to('direct.domains')
        with self.assertRaisesRegex(ValueError, 'Non-regular artifact entry'):
            validate_generated(self.root)

    def test_resource_presence_matches_inventory(self):
        self.index.pop('helpers')
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, 'helper and manifest disagree'):
            validate_generated(self.root, historical=True)

    def test_pre_protection_and_pre_helper_v1_historical_only(self):
        guard, = self.index.pop('protections')
        self.index['order'].remove('webrtc-guard')
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, 'protection is missing from the index'):
            validate_generated(self.root, historical=True)
        helper, = self.index.pop('helpers')
        for item in [*guard['resources'].values(), helper]:
            self.manifest['files'].pop(item['path'])
            (self.root / item['path']).unlink()
        self.index['order'].remove('dns-server-paths')
        self.write_metadata()
        _, result = validate_generated(self.root, historical=True)
        self.assertEqual((result['helpers'], result['protections']), (0, 0))
        with self.assertRaisesRegex(ValueError, 'Current publication requires'):
            validate_generated(self.root)
