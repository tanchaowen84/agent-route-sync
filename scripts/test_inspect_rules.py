"""Public CLI receipts from isolated complete v1 snapshots."""
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from build_rules import build
from inspect_rules import main
from rule_fixtures import source_inputs


def digest(data):
    return hashlib.sha256(data).hexdigest()


class InspectRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name) / 'release'
        raw = source_inputs()
        raw['advertising_domains'] += 'full:exact.ads.example\n'
        build(raw, cls.base)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.other = Path(temp.name) / 'release'
        shutil.copytree(self.base, self.other)
        self.index = json.loads((self.other / 'index.json').read_bytes())
        self.manifest = json.loads((self.other / 'manifest.json').read_bytes())

    def save_index(self):
        index = json.dumps(self.index).encode()
        (self.other / 'index.json').write_bytes(index)
        self.manifest['files']['index.json'] = digest(index)
        (self.other / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def replace(self, resource, contents):
        (self.other / resource['path']).write_bytes(contents)
        self.manifest['files'][resource['path']] = resource['sha256'] = digest(contents)
        self.save_index()

    def run_cli(self, *args, expected=0):
        out = io.StringIO()
        with redirect_stdout(out), patch('socket.create_connection', side_effect=AssertionError('network access')):
            self.assertEqual(main([str(arg) for arg in args]), expected)
        return json.loads(out.getvalue())

    def test_diff_membership_format_and_snapshot_identity(self):
        guard = self.index['protections'][0]['resources']['surge']
        content = (self.other / guard['path']).read_bytes().replace(b'DEST-PORT', b'DST-PORT')
        self.replace(guard, content)
        info = self.run_cli('diff', self.base, self.other)
        self.assertEqual(info['totals'], {'added': 0, 'removed': 0})
        self.assertEqual(info['groups']['webrtc-guard']['changed_resource_formats'], ['surge'])
        self.assertEqual(info['before']['generated_at_utc'], info['after']['generated_at_utc'])
        self.assertNotEqual(info['before']['manifest_sha256'], info['after']['manifest_sha256'])
        self.assertEqual(info['after']['manifest_sha256'], digest((self.other / 'manifest.json').read_bytes()))
        rules = self.index['datasets'][1]['resources']['sing-box']
        text = (self.other / rules['path']).read_bytes().replace(b'exact.ads.example', b'changed.ads.example')
        self.replace(rules, text)
        info = self.run_cli('diff', self.base, self.other)
        self.assertEqual(info['totals'], {'added': 1, 'removed': 1})
        self.assertEqual(info['groups']['reject']['added_records'], [{'kind': 'domain', 'value': 'changed.ads.example'}])
        self.assertEqual(info['groups']['reject']['removed_records'], [{'kind': 'domain', 'value': 'exact.ads.example'}])
        self.assertNotIn('added_records', self.run_cli('diff', self.base, self.other, '--summary-only')['groups']['reject'])

    def test_exact_suffix_boundary_precedence_and_addresses(self):
        cases = [
            (['--domain', 'ExAcT.ads.example.'], 'reject', 'domain', 'exact.ads.example', 'REJECT'),
            (['--domain', 'rt.ts.net'], 'private', 'domain_suffix', 'ts.net', 'DIRECT'),
            (['--domain', 'ts.net'], 'private', 'domain_suffix', 'ts.net', 'DIRECT'),
            (['--domain', 'www.google.com', '--ip', '1.0.0.1'], 'proxy', 'domain_suffix', 'google.com', 'PROXY'),
            (['--ip', '1.0.0.1'], 'cn-ip', 'ip_cidr', '1.0.0.1/32', 'DIRECT'),
            (['--ip', '2400::1'], 'cn-ip', 'ip_cidr', '2400::1/128', 'DIRECT'),
        ]
        for args, group, kind, value, action in cases:
            with self.subTest(args=args):
                result = self.run_cli('explain', self.base, *args, '--port', '443')
                self.assertEqual(result['match'], {'group': group, 'kind': kind, 'value': value})
                self.assertEqual((result['status'], result['action']), ('matched', action))
                self.assertEqual(result['scope']['device_action'], 'unknown')
        for domain in ('sub.exact.ads.example', 'badts.net'):
            result = self.run_cli('explain', self.base, '--domain', domain, '--port', '443', '--ip', '192.0.2.9')
            self.assertEqual((result['status'], result['action']), ('no_match', None))

    def test_guard_optional_port_and_runtime(self):
        for args, kind, value in ((['--ip', '2400::1', '--port', '3478'], 'port', 3478),
                                  (['--domain', 'stun.google.com'], 'domain_keyword', 'stun')):
            result = self.run_cli('explain', self.base, *args)
            self.assertEqual(result['match'], {'group': 'webrtc-guard', 'kind': kind, 'value': value})
            self.assertEqual(result['action'], 'REJECT')
        for args, reason in ((['--domain', 'www.google.com'], 'destination_port_needed_to_rule_out_guard'),
                             (['--domain', 'not-listed.test', '--port', '443'], 'no_domain_match_and_destination_ip_unspecified'),
                             (['--ip', '1.0.0.1', '--port', '3478', '--device'], 'device_configuration_and_runtime_not_observed')):
            result = self.run_cli('explain', self.base, *args)
            self.assertEqual((result['status'], result['reason'], result['action']), ('unknown', reason, None))

    def test_pre_guard_v1_uses_its_own_order(self):
        group, = self.index.pop('protections')
        for resource in group['resources'].values():
            self.manifest['files'].pop(resource['path'])
            (self.other / resource['path']).unlink()
        self.index['order'].remove('webrtc-guard')
        self.save_index()
        info = self.run_cli('diff', self.other, self.base)
        self.assertEqual(info['groups']['webrtc-guard']['added'], 11)
        self.assertNotIn('webrtc-guard', info['before_order'])
        result = self.run_cli('explain', self.other, '--domain', 'stun.google.com', '--port', '3478')
        self.assertEqual((result['match']['group'], result['action']), ('proxy', 'PROXY'))

    def test_client_declaration_and_separate_observation(self):
        info = self.run_cli('evidence', self.base)
        self.assertEqual(set(info['clients']), {'mihomo', 'sing-box', 'surge', 'shadowrocket'})
        small = info['clients']['shadowrocket']
        self.assertEqual((small['format'], small['current_project_scope'], small['separate_observation']['layer']),
                         ('surge', 'structure_only', 'release_notes'))
        self.assertEqual(info['clients']['sing-box']['separate_observation']['layer'], 'isolated_runtime')
        self.index['validation_scope'] = {'shadowrocket': 'device_verified'}
        self.save_index()
        info = self.run_cli('evidence', self.other, '--client', 'shadowrocket')['clients']['shadowrocket']
        self.assertFalse(info['declaration_recognized'])
        self.assertEqual(info['target_device_loading_and_route'], 'unverified')
        self.assertEqual(self.run_cli('evidence', self.other, '--client', 'surge')['clients']['surge']['snapshot_declared_scope'], 'unknown')

    def test_unknown_native_version_compound_rule_and_invalid_v1(self):
        resource = self.index['datasets'][0]['resources']['sing-box']
        source = json.loads((self.other / resource['path']).read_bytes())
        for change in ({'version': 4}, {'rules': [{'domain': ['known.example'], 'port': [443]}]}):
            self.replace(resource, json.dumps({**source, **change}).encode())
            result = self.run_cli('explain', self.other, '--domain', 'known.example', '--port', '443')
            self.assertEqual(result['status'], 'unknown')
            self.assertIn('manifest_sha256', result['snapshot'])
            self.assertEqual(self.run_cli('diff', self.base, self.other)['status'], 'unknown')
        self.index['schema_version'] = 2
        self.save_index()
        self.assertEqual(self.run_cli('evidence', self.other, expected=1)['status'], 'invalid')

    def test_corruption_and_unrelated_failures_preserve_files(self):
        untouched = {p.relative_to(self.other): p.stat().st_mtime_ns for p in self.other.rglob('*') if p.is_file()}
        self.run_cli('diff', self.other, self.other)
        self.run_cli('evidence', self.other)
        self.run_cli('explain', self.other, '--domain', 'www.google.com', '--port', '443')
        self.assertEqual(untouched, {p.relative_to(self.other): p.stat().st_mtime_ns for p in self.other.rglob('*') if p.is_file()})
        (self.other / 'direct.list').write_bytes(b'broken')
        for args in (('diff', self.base, self.other), ('evidence', self.other),
                     ('explain', self.other, '--ip', '1.0.0.1')):
            self.assertEqual(self.run_cli(*args, expected=1)['status'], 'invalid')
        for args in (['--domain', '*.test'], ['--domain', '127.0.0.1'], ['--ip', 'not-an-ip'],
                     ['--ip', '1.0.0.1', '--port', '65536'], []):
            self.assertEqual(self.run_cli('explain', self.base, *args, expected=1)['status'], 'invalid')


if __name__ == '__main__':
    unittest.main()
