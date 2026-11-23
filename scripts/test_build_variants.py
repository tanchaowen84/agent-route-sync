"""Verify generation boundaries and domain semantics without installing native clients."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from build_rules import build
from build_variants import build_variants
from rule_fixtures import source_inputs


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compile_fixture(command):
    # Native parsing and compatibility are tested independently with the pinned binaries in CI.
    output = command[-1] if command[1] == 'convert-ruleset' else command[-2]
    output.write_bytes(b'compiled fixture ' + output.name.encode('ascii'))


class FormatGenerationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.output = self.root / 'text', self.root / 'published'
        self.manifest = build(source_inputs(), self.source)
        self.index = json.loads((self.source / 'index.json').read_bytes())

    def run_build(self):
        return build_variants(self.source, self.output, 'mihomo', 'sing-box')

    def replace_source_file(self, name, data):
        (self.source / name).write_bytes(data)
        self.manifest['files'][name] = digest(data)
        (self.source / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_one_generation_preserves_original_files_and_uses_all_supported_sources(self):
        # An older DOMAIN-SET can have different casing, comments and order with the same semantics.
        lines = (self.source / 'private.domains').read_text(encoding='utf-8').upper().splitlines()
        self.replace_source_file('private.domains', ('# private\n' + '\n'.join(reversed(lines)) + '\n').encode())
        for name in ('manifest.json', 'index.json'):
            path = self.source / name
            self.addCleanup(path.chmod, path.stat().st_mode)
            path.chmod(0o444)
        original = {path.relative_to(self.source): digest(path.read_bytes())
                    for path in self.source.rglob('*') if path.is_file()}
        with patch('build_variants.checked', side_effect=compile_fixture) as compiled:
            self.assertEqual(self.run_build(), 16)
        self.assertEqual(compiled.call_count, 12)
        index = json.loads((self.output / 'index.json').read_bytes())
        rows = index.pop('format_variants')
        self.assertEqual(index, self.index)
        names = ['private', 'reject', 'proxy', 'direct', 'cn-ip']
        expected = [(name, 'mrs', f'mihomo/{name}.mrs') for name in names]
        expected += [(name, 'srs', f'sing-box/{name}.srs') for name in names + ['webrtc-guard', 'non-cn-ip']]
        expected += [(name, 'domain-set', f'{name}.domains') for name in names[:4]]
        self.assertEqual([(row['id'], row['format'], row['path']) for row in rows], expected)
        counts = {group['id']: group['resources']['surge']['entries'] for group in index['datasets'] + index['protections']}
        counts['non-cn-ip'] = index['helpers'][0]['entries']
        manifest = json.loads((self.output / 'manifest.json').read_bytes())
        self.assertEqual({key: value for key, value in manifest.items() if key != 'files'},
                         {key: value for key, value in self.manifest.items() if key != 'files'})
        for row in rows:
            self.assertEqual(set(row), {'id', 'format', 'path', 'url', 'sha256', 'entries'})
            self.assertEqual(row['entries'], counts[row['id']])
            self.assertEqual(row['url'], index['base_url'] + row['path'])
            self.assertEqual(row['sha256'], manifest['files'][row['path']])
        for path, before in original.items():
            self.assertEqual(digest((self.source / path).read_bytes()), before)
            if path.as_posix() not in ('index.json', 'manifest.json'):
                self.assertEqual(digest((self.output / path).read_bytes()), before)
        for path, value in manifest['files'].items():
            self.assertEqual(digest((self.output / path).read_bytes()), value)
        proxy = (self.output / 'proxy.domains').read_text(encoding='utf-8').splitlines()
        self.assertIn('foreign0.example', proxy)
        self.assertIn('.google.com', proxy)
        self.assertNotIn('.foreign0.example', proxy)

    def test_rejects_a_legacy_domain_with_the_same_count_but_different_matching(self):
        data = (self.source / 'private.domains').read_bytes().replace(b'.lan\n', b'lan\n')
        self.replace_source_file('private.domains', data)
        with patch('build_variants.checked', side_effect=compile_fixture), \
                self.assertRaisesRegex(ValueError, 'Existing DOMAIN-SET differs'):
            self.run_build()
        self.assertEqual(set(self.root.iterdir()), {self.source})

    def test_failing_compiler_and_damaged_input_leave_no_candidate(self):
        def partial(command):
            compile_fixture(command)
            raise RuntimeError('compiler interrupted')

        with patch('build_variants.checked', side_effect=partial), self.assertRaisesRegex(RuntimeError, 'interrupted'):
            self.run_build()
        self.assertEqual(set(self.root.iterdir()), {self.source})
        (self.source / 'surge/private.list').write_bytes(b'tampered')
        with patch('build_variants.checked') as compiled, self.assertRaisesRegex(ValueError, 'digest'):
            self.run_build()
        compiled.assert_not_called()
        self.assertEqual(set(self.root.iterdir()), {self.source})

    def test_never_writes_into_source_or_overwrites_an_existing_destination(self):
        self.output = self.source / 'nested' / 'candidate'
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.run_build()
        self.assertFalse(self.output.parent.exists())
        self.output = self.root / 'existing'
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            self.run_build()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_rejects_compiler_side_effects_outside_indexed_outputs(self):
        def stray_file(command):
            compile_fixture(command)
            output = command[-1] if command[1] == 'convert-ruleset' else command[-2]
            (output.parent / 'unexpected').write_bytes(b'extra')

        with patch('build_variants.checked', side_effect=stray_file), self.assertRaisesRegex(ValueError, 'inventory'):
            self.run_build()
        self.assertEqual(set(self.root.iterdir()), {self.source})
