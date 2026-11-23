"""Run the release workflow's own shell steps against a disposable, file-only Git remote."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/run.yml'


class WorkflowBindingTests(unittest.TestCase):
    def test_both_jobs_consume_the_build_artifact_and_only_publish_can_write(self):
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))
        jobs = workflow['jobs']
        self.assertEqual(workflow['permissions']['contents'], 'read')
        self.assertEqual([name for name, job in jobs.items() if job.get('permissions', {}).get('contents') == 'write'],
                         ['publish'])
        self.assertEqual(jobs['build']['outputs']['artifact_id'], '${{ steps.upload.outputs.artifact-id }}')
        self.assertEqual(jobs['build']['outputs']['release_baseline'], '${{ steps.dataset.outputs.release_baseline }}')
        self.assertEqual(jobs['build']['outputs']['manifest_sha256'], '${{ steps.candidate.outputs.manifest_sha256 }}')
        build_steps = {step.get('id'): step for step in jobs['build']['steps']}
        directory = build_steps['upload']['with']['path']
        self.assertIn('--output ' + directory + ' ', build_steps['candidate']['run'])
        self.assertIn('sha256sum ' + directory + '/manifest.json', build_steps['candidate']['run'])
        self.assertTrue(any('scripts/check_contracts.py --generated generated --require-variants' in step.get('run', '')
                            for step in jobs['validate']['steps']))
        for name in ('validate', 'publish'):
            steps = jobs[name]['steps']
            download = next(s for s in steps if s.get('uses', '').startswith('actions/download-artifact@'))
            self.assertIn('needs.build.outputs.artifact_id', download['with']['artifact-ids'])
            self.assertTrue(any(s.get('env', {}).get('MANIFEST_SHA256') == '${{ needs.build.outputs.manifest_sha256 }}'
                                for s in steps))
        push = next(s for s in jobs['publish']['steps'] if s.get('id') == 'push')
        self.assertEqual(push['env']['RELEASE_BASELINE'], '${{ needs.build.outputs.release_baseline }}')


@unittest.skipUnless(os.name == 'posix' and all(shutil.which(tool) for tool in ('bash', 'git', 'jq', 'sha256sum')),
                     'publish uses an Ubuntu runner with bash, git, jq and sha256sum')
class PublishWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.remote = self.root / 'remote.git'
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update({
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_ALLOW_PROTOCOL': 'file',
            'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': f'url.{self.remote.as_uri()}.insteadOf',
            'GIT_CONFIG_VALUE_0': 'https://x-access-token:fixture@github.com/test/rules.git',
            'GITHUB_TOKEN': 'fixture', 'GITHUB_REPOSITORY': 'test/rules', 'RUNNER_TEMP': str(self.root),
        })
        steps = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))['jobs']['publish']['steps']
        self.steps = {step['id']: step['run'] for step in steps if 'id' in step}
        self.git('init', '--bare', '--quiet', '--initial-branch=master', str(self.remote))
        self.master = self.advance_master('initial')

    def git(self, *args, body=None):
        return subprocess.run(['git', *args], input=body, cwd=self.root, env=self.env, capture_output=True,
                              text=True, check=True, timeout=15).stdout.strip()

    def advance_master(self, message, parent=None):
        tree = self.git('-C', str(self.remote), 'mktree', body='')
        commit = self.git('-C', str(self.remote), '-c', 'user.name=Fixture', '-c', 'user.email=test@example.org',
                          'commit-tree', tree, *(['-p', parent] if parent else []), '-m', message)
        self.git('-C', str(self.remote), 'update-ref', 'refs/heads/master', commit)
        return commit

    def step(self, name, directory, **env):
        return subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', self.steps[name]],
                              cwd=directory, env={**self.env, **env}, capture_output=True,
                              text=True, timeout=30)

    def candidate(self, content, **git_env):
        directory = Path(tempfile.mkdtemp(dir=self.root))
        (directory / 'rules.txt').write_bytes(content)
        manifest = json.dumps({'files': {'rules.txt': hashlib.sha256(content).hexdigest()}}).encode()
        (directory / 'manifest.json').write_bytes(manifest)
        check = self.step('prepare', directory, MANIFEST_SHA256=hashlib.sha256(manifest).hexdigest(), **git_env)
        return directory, check

    def prepared(self, content):
        directory, check = self.candidate(content)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        return directory

    def publish(self, directory, baseline, source):
        return self.step('push', directory, RELEASE_BASELINE=baseline, GITHUB_SHA=source)

    def release(self):
        return self.git('-C', str(self.remote), 'rev-parse', 'refs/heads/release')

    def test_first_publication_and_interleaved_builds_use_their_original_leases(self):
        older = self.prepared(b'older candidate')
        seed = self.publish(self.prepared(b'first'), 'absent', self.master)
        self.assertEqual(seed.returncode, 0, seed.stderr)
        first = self.release()
        self.assertNotEqual(self.publish(older, 'absent', self.master).returncode, 0)
        self.assertEqual(self.release(), first)
        newer = self.publish(self.prepared(b'newer'), first, self.master)
        self.assertEqual(newer.returncode, 0, newer.stderr)
        winner = self.release()
        self.assertNotEqual(self.publish(older, first, self.master).returncode, 0)
        self.assertEqual(self.release(), winner)
        self.assertEqual(self.git('-C', str(self.remote), 'show', 'release:rules.txt'), 'newer')
        self.assertEqual(self.git('-C', str(self.remote), 'rev-parse', 'master'), self.master)

    def test_rerunning_old_source_cannot_publish_even_with_a_fresh_lease(self):
        candidate = self.prepared(b'rerun')
        current = self.advance_master('new source', self.master)
        result = self.publish(candidate, 'absent', self.master)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no longer the master tip', result.stdout)
        self.assertEqual(self.git('-C', str(self.remote), 'for-each-ref', 'refs/heads/release'), '')
        self.assertEqual(self.git('-C', str(self.remote), 'rev-parse', 'master'), current)

    def test_missing_refs_invalid_leases_and_unreachable_remote_fail_closed(self):
        candidate = self.prepared(b'candidate')
        for invalid in ('', '0' * 40, 'garbled'):
            with self.subTest(baseline=invalid):
                self.assertNotEqual(self.publish(candidate, invalid, self.master).returncode, 0)
        seed = self.publish(self.prepared(b'first'), 'absent', self.master)
        self.assertEqual(seed.returncode, 0, seed.stderr)
        deleted = self.release()
        self.git('-C', str(self.remote), 'update-ref', '-d', 'refs/heads/release')
        self.assertNotEqual(self.publish(candidate, deleted, self.master).returncode, 0)
        self.git('-C', str(self.remote), 'update-ref', '-d', 'refs/heads/master')
        self.assertNotEqual(self.publish(candidate, 'absent', self.master).returncode, 0)
        self.assertEqual(self.git('-C', str(self.remote), 'for-each-ref'), '')
        self.remote.rename(self.root / 'disconnected.git')
        self.assertNotEqual(self.publish(candidate, 'absent', self.master).returncode, 0)

    def test_tree_validation_detects_git_changing_the_contents(self):
        attrs = self.root / 'attributes'
        attrs.write_text('*.txt text eol=lf\n', encoding='utf-8')
        _, check = self.candidate(b'original\r\n', GIT_CONFIG_COUNT='2', GIT_CONFIG_KEY_1='core.attributesFile',
                                  GIT_CONFIG_VALUE_1=str(attrs))
        self.assertNotEqual(check.returncode, 0)
        self.assertIn('Git blob differs from the build output: rules.txt', check.stdout)
