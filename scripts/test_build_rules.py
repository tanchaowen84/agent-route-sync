"""Verify the public generation contract without network access or credentials."""
import contextlib
import datetime
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

import build_rules
from build_rules import build, fetch, private_domains, refuse_large_shrink, stale_repositories


class SourceGenerationTests(unittest.TestCase):
    def fixture(self):
        base = int(ipaddress.ip_address('1.0.0.0'))
        ipv6 = int(ipaddress.ip_address('2400::'))
        return {
            'china_domains': '\n'.join(['domain:' + name for name in
                ('baidu.com', 'qq.com', 'taobao.com', 'jd.com', 'asus.com')]
                + ['domain:domestic' + str(i) + '.example' for i in range(1001)]) + '\n',
            'foreign_domains': '\n'.join(['domain:' + name for name in
                ('google.com', 'gstatic.com', 'wikipedia.org', 'github.com', 'asus.com', 'ts.net')]
                + ['full:foreign' + str(i) + '.example' for i in range(1001)]) + '\n',
            'private_domains': 'full:router.asus.com\ndomain:ts.net\ndomain:lan\n',
            'china_ip': '\n'.join([str(ipaddress.ip_address(base + i)) + '/32' for i in range(1001)]
                                  + [str(ipaddress.ip_address(ipv6 + i)) + '/128' for i in range(1001)]) + '\n',
            'advertising_domains': '\n'.join(['domain:doubleclick.net']
                + ['domain:ad' + str(i) + '.example' for i in range(1001)]) + '\n',
        }

    def response(self, body, headers=None):
        response = MagicMock(status=200, headers=headers or {})
        response.__enter__.return_value = response
        response.read.return_value = body
        return response

    def test_token_is_sent_only_to_the_api(self):
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'token'}), patch('urllib.request.urlopen', return_value=self.response(b'data')) as opened:
            fetch('https://api.github.com/repos/a/b/commits/c')
            self.assertEqual(opened.call_args[0][0].get_header('Authorization'), 'Bearer token')
            fetch('https://raw.githubusercontent.com/a/b/c/d')
            self.assertIsNone(opened.call_args[0][0].get_header('Authorization'))

    def test_download_shorter_than_declared_is_retried_then_rejected(self):
        short = self.response(b'2400:da00::/3', {'Content-Length': '100000'})
        with patch('urllib.request.urlopen', return_value=short) as opened, patch('time.sleep'), \
             self.assertRaisesRegex(ValueError, 'download_truncated'):
            fetch('https://raw.githubusercontent.com/a/b/c/d')
        self.assertEqual(opened.call_count, 3)
        complete = self.response(b'data', {'Content-Length': '4'})
        with patch('urllib.request.urlopen', return_value=complete):
            self.assertEqual(fetch('https://raw.githubusercontent.com/a/b/c/d'), 'data')

    def test_build_refuses_a_china_prefix_cut_short(self):
        for line in ('2000::/3', '32.0.0.0/3'):
            raw = self.fixture()
            raw['china_ip'] += line + '\n'
            with self.subTest(line=line), tempfile.TemporaryDirectory() as folder, \
                 self.assertRaisesRegex(ValueError, 'china_ip_prefix_too_broad'):
                build(raw, Path(folder))

    def test_generation_preserves_foreign_input_and_private_matching_semantics(self):
        raw = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            manifest = build(raw, output)
            self.assertEqual((output / 'proxy-source.txt').read_bytes(), raw['foreign_domains'].encode())
            self.assertEqual((output / 'private.domains').read_text(), 'router.asus.com\n.lan\n.ts.net\n')
            self.assertNotIn('.asus.com', (output / 'direct.domains').read_text().splitlines())
            self.assertIn('router.asus.com', (output / 'direct.domains').read_text().splitlines())
            self.assertEqual(set(manifest['files']),
                             {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()} - {'manifest.json'})
            for name, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)
            self.assertEqual(manifest['source_sha256']['foreign_domains'], manifest['files']['proxy-source.txt'])
            self.assertEqual(manifest['counts']['private_domains'], 3)
            self.assertEqual(json.loads((output / 'manifest.json').read_text()), manifest)

    def test_private_source_cannot_empty_or_override_public_and_forced_routes(self):
        for source in ('', 'domain:com', 'domain:com.cn', 'domain:google.com',
                       'domain:apple.com', 'domain:icloud.com', 'domain:claude.ai'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                private_domains(source)

    def test_essential_sites_cannot_be_blocked_or_sent_direct(self):
        for field, line, error in (('advertising_domains', 'domain:raw.githubusercontent.com', 'advertising_blocks_protected_site'),
                                   ('advertising_domains', 'domain:chatgpt.com', 'advertising_blocks_protected_site'),
                                   ('china_domains', 'domain:chatgpt.com', 'foreign_domain_would_be_direct'),
                                   ('china_domains', 'domain:githubusercontent.com', 'foreign_domain_would_be_direct')):
            raw = self.fixture()
            raw[field] += line + '\n'
            with self.subTest(line=line, field=field), tempfile.TemporaryDirectory() as folder, \
                 self.assertRaisesRegex(ValueError, error):
                build(raw, Path(folder))
        with self.assertRaisesRegex(ValueError, 'private_overrides_public_service'):
            private_domains('domain:githubusercontent.com')

    def test_losing_core_overseas_coverage_is_refused(self):
        raw = self.fixture()
        raw['foreign_domains'] = raw['foreign_domains'].replace('domain:google.com\n', '')
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(ValueError, 'foreign_domain_coverage_lost'):
            build(raw, Path(folder))

    def index(self, **sizes):
        return {'datasets': [{'id': name, 'resources': {'surge': {'entries': count}}} for name, count in sizes.items()]}

    def test_large_shrink_is_refused_and_small_changes_pass(self):
        previous = self.index(reject=1000, proxy=1000)
        refuse_large_shrink(previous, self.index(reject=700, proxy=1200))
        with self.assertRaisesRegex(ValueError, 'dataset_shrank_too_much:reject'):
            refuse_large_shrink(previous, self.index(reject=699, proxy=1000))
        with self.assertRaisesRegex(ValueError, 'dataset_shrank_too_much:proxy'):
            refuse_large_shrink(previous, self.index(reject=1000))

    def test_only_repositories_past_the_limit_are_stale(self):
        now = datetime.datetime(2026, 11, 15, tzinfo=datetime.timezone.utc)
        versions = {'old': {'repository': 'a/old', 'committed_at': '2026-10-31T23:59:59Z'},
                    'edge': {'repository': 'a/edge', 'committed_at': '2026-11-01T00:00:00Z'},
                    'new': {'repository': 'a/new', 'committed_at': '2026-11-14T00:00:00+00:00'}}
        self.assertEqual(stale_repositories(versions, now), ['a/old'])

    def run_main(self, folder, committed_at, published, environment=None):
        raw = self.fixture()
        inputs = build_rules.REGISTRY['inputs']

        def fake_fetch(url):
            if '/commits/' in url:
                return json.dumps({'sha': 'a' * 40, 'commit': {'committer': {'date': committed_at}}})
            if url.startswith(build_rules.BASE_URL):
                if published is None:
                    raise urllib.error.HTTPError(url, 404, 'Not Found', None, None)
                return json.dumps(published)
            return next(raw[key] for key, entry in inputs.items() if url.endswith('/' + entry['path']))

        step_output = Path(folder) / 'step-output'
        step_output.write_text('', encoding='utf-8')
        env = {'GITHUB_OUTPUT': str(step_output), 'AGENTROUTE_ALLOW_SHRINK': '', **(environment or {})}
        with patch.object(build_rules, 'fetch', fake_fetch), patch.dict(os.environ, env), \
             contextlib.redirect_stdout(io.StringIO()):
            build_rules.main(Path(folder) / 'generated')
        return step_output.read_text(encoding='utf-8')

    def test_main_records_upstream_dates_and_reports_stale_sources(self):
        fresh = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(self.run_main(folder, fresh, None), '')
            manifest = json.loads((Path(folder) / 'generated/manifest.json').read_text(encoding='utf-8'))
            self.assertEqual({entry['committed_at'] for entry in manifest['source_versions'].values()}, {fresh})
        with tempfile.TemporaryDirectory() as folder:
            line = self.run_main(folder, '2020-01-01T00:00:00Z', None)
            self.assertRegex(line, r'^stale_upstreams=Loyalsoldier/')

    def test_main_refuses_a_large_drop_from_the_published_generation(self):
        fresh = datetime.datetime.now(datetime.timezone.utc).isoformat()
        published = self.index(proxy=27000)
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(ValueError, 'dataset_shrank_too_much:proxy'):
            self.run_main(folder, fresh, published)
        with tempfile.TemporaryDirectory() as folder:
            self.run_main(folder, fresh, published, {'AGENTROUTE_ALLOW_SHRINK': 'true'})


if __name__ == '__main__':
    unittest.main()
