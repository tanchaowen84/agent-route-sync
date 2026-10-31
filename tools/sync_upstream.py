#!/usr/bin/env python3
"""Mirror public AgentRoute data; never check out or run upstream code."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import subprocess
import tempfile

UPSTREAM = 'https://github.com/ryuu-restart/agent-route.git'


def git(*args, data=None, env=None):
    result = subprocess.run(
        ['git', '-c', 'core.hooksPath=/dev/null', *args], input=data,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace').strip())
    return result.stdout


def read_blob(commit, path):
    return git('show', f'{commit}:{path}')


def verify_release(commit):
    manifest_bytes = read_blob(commit, 'manifest.json')
    manifest = json.loads(manifest_bytes)
    index = json.loads(read_blob(commit, 'index.json'))
    if manifest.get('schema_version') != 1 or index.get('schema_version') != 1:
        raise ValueError('Unsupported manifest/index schema')
    if manifest['generated_at_utc'] != index['generated_at_utc']:
        raise ValueError('Mixed release generations')
    timestamp = dt.datetime.fromisoformat(manifest['generated_at_utc'])
    age = (dt.datetime.now(dt.timezone.utc) - timestamp).total_seconds()
    if not -600 <= age <= 48 * 3600:
        raise ValueError(f'Release outside allowed age: {age:.0f}s')
    datasets = {row['id']: row for row in index['datasets']}
    if set(datasets) != {'private', 'reject', 'proxy', 'direct', 'cn-ip'}:
        raise ValueError('Missing or unexpected routing datasets')
    files = manifest['files']
    for path, expected_hash in files.items():
        pure = PurePosixPath(path)
        if pure.is_absolute() or '..' in pure.parts or '\\' in path or not re.fullmatch(r'[0-9a-f]{64}', expected_hash):
            raise ValueError(f'Invalid manifest entry: {path}')
        data = read_blob(commit, path)
        if len(data) > 16 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected_hash:
            raise ValueError(f'Release hash/size mismatch: {path}')
    if 'index.json' not in files:
        raise ValueError('Manifest does not authenticate index.json')
    for row in datasets.values():
        if any(item['entries'] <= 0 for item in row['resources'].values()):
            raise ValueError('Empty dataset')
    resources = [item for row in datasets.values() for item in row['resources'].values()] + index.get('helpers', [])
    for item in resources:
        if files.get(item['path']) != item['sha256']:
            raise ValueError(f'Index/manifest disagree: {item["path"]}')
    return manifest, index


def filtered_source_tree(commit):
    # A private index removes only upstream automation, without checking out data.
    with tempfile.TemporaryDirectory() as directory:
        env = dict(os.environ, GIT_INDEX_FILE=directory + '/index')
        git('read-tree', commit, env=env)
        paths = git('ls-files', '-z', '--', '.github', env=env)
        if paths:
            git('update-index', '--force-remove', '-z', '--stdin', data=paths, env=env)
        return git('write-tree', env=env).decode().strip()


def commit_tree(tree, parent, message):
    args = ['-c', 'user.name=AgentRoute Sync', '-c',
            'user.email=41898282+github-actions[bot]@users.noreply.github.com',
            'commit-tree', tree]
    if parent:
        args += ['-p', parent]
    return git(*args, data=(message + '\n').encode()).decode().strip()


def synchronize(upstream=UPSTREAM, dry_run=False):
    git('fetch', '--no-tags', '--depth=1', upstream,
        '+refs/heads/master:refs/remotes/upstream/master',
        '+refs/heads/release:refs/remotes/upstream/release')
    git('fetch', '--prune', '--no-tags', 'origin',
        '+refs/heads/*:refs/remotes/origin/*')
    refs = dict(line.split(' ', 1) for line in git(
        'for-each-ref', '--format=%(refname) %(objectname)',
        'refs/remotes/origin/').decode().splitlines())
    source = git('rev-parse', 'refs/remotes/upstream/master').decode().strip()
    release = git('rev-parse', 'refs/remotes/upstream/release').decode().strip()
    manifest, _ = verify_release(release)
    paths = git('ls-tree', '-r', '--name-only', release).decode().splitlines()
    if any(path == '.github' or path.startswith('.github/') for path in paths):
        raise ValueError('Release unexpectedly contains GitHub automation')
    base = refs['refs/remotes/origin/main']
    main_paths = git('ls-tree', '--name-only', base).decode().splitlines()
    previous = json.loads(read_blob(base, 'SYNC_STATE.json')) if 'SYNC_STATE.json' in main_paths else {}
    versions = {'master': source, 'release': release}
    if previous.get('upstream_commits') == versions:
        print(json.dumps({'status': 'unchanged', 'upstream_commits': versions}))
        return
    push_refs = []
    for branch, upstream_commit, tree in [
        ('source', source, filtered_source_tree(source)),
        ('release', release, git('rev-parse', release + '^{tree}').decode().strip()),
    ]:
        parent = refs.get('refs/remotes/origin/' + branch)
        if parent and git('rev-parse', parent + '^{tree}').decode().strip() == tree:
            continue
        commit = commit_tree(tree, parent, f'Sync upstream {branch}: {upstream_commit}')
        push_refs.append(f'{commit}:refs/heads/{branch}')
    state = {
        'upstream_repository': UPSTREAM,
        'upstream_commits': versions,
        'release_generated_at_utc': manifest['generated_at_utc'],
        'synced_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'source_excludes': ['.github/'],
        'upstream_code_executed': False,
    }
    blob = git('hash-object', '-w', '--stdin', data=(json.dumps(state, indent=2) + '\n').encode()).decode().strip()
    with tempfile.TemporaryDirectory() as directory:
        env = dict(os.environ, GIT_INDEX_FILE=directory + '/index')
        git('read-tree', base, env=env)
        git('update-index', '--add', '--cacheinfo', f'100644,{blob},SYNC_STATE.json', env=env)
        tree = git('write-tree', env=env).decode().strip()
    control = commit_tree(tree, base, 'Record verified upstream snapshot')
    push_refs.append(f'{control}:refs/heads/main')
    if not dry_run:
        git('push', '--atomic', 'origin', *push_refs)
    print(json.dumps({'status': 'dry-run' if dry_run else 'synced', **state}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    synchronize(dry_run=args.dry_run)
