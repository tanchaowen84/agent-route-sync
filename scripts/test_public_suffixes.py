import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from build_rules import advertising_domains, private_domains
from check_public_suffixes import PublicSuffixes, assess, main


class PublicSuffixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # requests-file handles the local snapshot. Any HTTP(S) fallback fails this test.
        with mock.patch('requests.adapters.HTTPAdapter.send', side_effect=AssertionError('HTTP request')):
            cls.psl = PublicSuffixes()

    def test_icann_scope_and_exact_names(self):
        for dataset in ('reject', 'private'):
            for name in ('co.nz', 'com.br', 'xn--p1ai'):
                with self.subTest(dataset=dataset, name=name):
                    self.assertEqual(self.psl.classify(dataset, 'DOMAIN-SUFFIX', name), ('blocked', 'ICANN'))
                    self.assertEqual(self.psl.classify(dataset, 'DOMAIN', name), ('review', 'ICANN'))
            self.assertIsNone(self.psl.classify(dataset, 'DOMAIN-SUFFIX', 'example.co.nz'))

    def test_wildcard_and_exception(self):
        self.assertEqual(self.psl.classify('reject', 'DOMAIN-SUFFIX', 'example.ck'), ('blocked', 'ICANN'))
        self.assertEqual(self.psl.classify('reject', 'DOMAIN-SUFFIX', 'kawasaki.jp'), ('blocked', 'ICANN_descendant'))
        for name in ('www.ck', 'city.kawasaki.jp', 'host.city.kawasaki.jp'):
            self.assertIsNone(self.psl.classify('reject', 'DOMAIN-SUFFIX', name))
        self.assertIsNone(self.psl.classify('private', 'DOMAIN', 'kawasaki.jp'))

    def test_private_boundary_ancestor_and_tenant(self):
        for kind in ('DOMAIN', 'DOMAIN-SUFFIX'):
            self.assertEqual(self.psl.classify('private', kind, 'github.io'), ('review', 'PRIVATE'))
            self.assertIsNone(self.psl.classify('reject', kind, 'tenant.github.io'))
        self.assertEqual(self.psl.classify('reject', 'DOMAIN-SUFFIX', '0emm.com'), ('review', 'PRIVATE_descendant'))
        self.assertIsNone(self.psl.classify('reject', 'DOMAIN', '0emm.com'))

    def test_local_scopes(self):
        for name in ('lan', 'localhost', 'home.arpa'):
            self.assertEqual(self.psl.classify('private', 'DOMAIN-SUFFIX', name), ('local_exceptions', 'local_scope'))
        self.assertEqual(self.psl.classify('reject', 'DOMAIN-SUFFIX', 'home.arpa'), ('blocked', 'ICANN'))
        self.assertIsNone(self.psl.classify('private', 'DOMAIN-SUFFIX', '10.in-addr.arpa'))
        self.assertEqual(private_domains('domain:lan'), (set(), {'lan'}))
        fillers = ''.join(f'domain:sample{i}.example.org\n' for i in range(1000))
        with self.assertRaisesRegex(ValueError, 'advertising_domain_too_broad'):
            advertising_domains(fillers + 'domain:lan')

    def test_shared_builder_baseline_still_rejects_exact_and_suffix(self):
        fillers = ''.join(f'domain:sample{i}.example.org\n' for i in range(1000))
        for name in ('com.cn', 'net.cn', 'org.cn', 'co.uk', 'com.au', 'co.jp'):
            for prefix in ('domain:', 'full:'):
                with self.subTest(name=name, prefix=prefix):
                    with self.assertRaisesRegex(ValueError, 'advertising_domain_too_broad'):
                        advertising_domains(fillers + prefix + name)
                    with self.assertRaisesRegex(ValueError, 'private_domain_too_broad'):
                        private_domains(prefix + name)

    def test_snapshot_must_match_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public_suffix_list.dat'
            path.write_text('co.nz\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                PublicSuffixes(path)

    def test_cli_verdict_reads_both_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'surge').mkdir()
            reject = root / 'surge/reject.list'
            private = root / 'surge/private.list'
            reject.write_text('DOMAIN,co.nz\nDOMAIN-SUFFIX,tenant.github.io\n', encoding='utf-8')
            private.write_text('DOMAIN-SUFFIX,lan\n', encoding='utf-8')
            with mock.patch.object(sys, 'argv', ['check_public_suffixes.py', '--generated', str(root)]):
                for status in (0, 1):
                    with self.subTest(status=status), contextlib.redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(main(), status)
                        report = json.loads(output.getvalue())
                        self.assertEqual(report['counts']['reject'], {'DOMAIN': 1, 'DOMAIN-SUFFIX': 1})
                        self.assertEqual([item['name'] for item in report['blocked']], ['co.nz'] if status else [])
                    private.write_text('DOMAIN-SUFFIX,co.nz\n', encoding='utf-8')
            private.write_text('DOMAIN-KEYWORD,co.nz\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'expected a published domain rule'):
                assess(root, self.psl)
