#!/usr/bin/env python3
"""Assess the scope of the published reject/private domain rules against a fixed PSL."""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys

import idna
import requests
from requests_file import FileAdapter
import tldextract

from build_rules import DOMAIN, LOCAL_PRIVATE_LABELS
from rule_catalog import RESOURCE_BY_ID


SNAPSHOT = Path(__file__).resolve().parents[1] / 'validation/psl/public_suffix_list.dat'
SNAPSHOT_SHA256 = '017501d3fa7911c60ac7e0f68df4122b07216c585c15dc30e0f0c74b8d13a2b9'
LOCAL_PRIVATE_SCOPES = LOCAL_PRIVATE_LABELS | {'home.arpa'}


def rule_ancestors(rules):
    """Index names whose whole subtree contains an explicitly listed PSL boundary."""
    ancestors = set()
    for rule in rules:
        if rule.startswith('!'):
            continue
        # The '*' label matters: for '*.kawasaki.jp', 'kawasaki.jp' is an ancestor.
        labels = rule.split('.')
        for start in range(1, len(labels)):
            name = '.'.join(labels[start:])
            if not name.isascii():
                name = idna.encode(name, uts46=True).decode('ascii')
            ancestors.add(name)
    return ancestors


class PublicSuffixes:
    def __init__(self, snapshot=SNAPSHOT):
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != SNAPSHOT_SHA256:
            raise ValueError('PSL snapshot SHA-256 mismatch')
        options = dict(suffix_list_urls=(snapshot.resolve().as_uri(),), cache_dir=None,
                       fallback_to_snapshot=False)
        self.extract = tldextract.TLDExtract(include_psl_private_domains=True, **options)
        icann = tldextract.TLDExtract(**options)
        with requests.Session() as files, ExitStack() as responses:
            # Permit only local file requests and close both file responses after parsing.
            files.adapters.clear()
            files.mount('file://', FileAdapter())
            files.hooks['response'].append(lambda response, **_: responses.enter_context(response))
            icann.update(fetch_now=True, session=files)
            self.extract.update(fetch_now=True, session=files)
        icann_rules = set(icann.tlds)
        self.icann_parents = rule_ancestors(icann_rules)
        self.private_parents = rule_ancestors(set(self.extract.tlds) - icann_rules)

    def classify(self, dataset, kind, name):
        if dataset == 'private' and name in LOCAL_PRIVATE_SCOPES:
            return 'local_exceptions', 'local_scope'
        match = self.extract(name)
        subtree = kind == 'DOMAIN-SUFFIX'
        if match.suffix and not match.domain and not match.is_private:
            return ('blocked' if subtree else 'review'), 'ICANN'
        if subtree and name in self.icann_parents:
            return 'blocked', 'ICANN_descendant'
        if match.is_private and not match.domain:
            return 'review', 'PRIVATE'
        if subtree and name in self.private_parents:
            return 'review', 'PRIVATE_descendant'
        return None


def assess(generated, psl):
    result = {'psl_sha256': SNAPSHOT_SHA256, 'counts': {}, 'blocked': [], 'review': [], 'local_exceptions': []}
    for dataset in ('reject', 'private'):
        counts = {'DOMAIN': 0, 'DOMAIN-SUFFIX': 0}
        result['counts'][dataset] = counts
        path = generated / RESOURCE_BY_ID[dataset].path('surge')
        with path.open(encoding='utf-8') as rules:
            for line_number, line in enumerate(rules, start=1):
                kind, _, name = line.rstrip('\n').partition(',')
                if kind not in counts or not DOMAIN.fullmatch(name):
                    raise ValueError(f'{path}:{line_number}: expected a published domain rule')
                counts[kind] += 1
                finding = psl.classify(dataset, kind, name.lower())
                if finding:
                    disposition, boundary = finding
                    result[disposition].append({'dataset': dataset, 'type': kind, 'name': name, 'boundary': boundary})
        if not any(counts.values()):
            raise ValueError(f'{path}: empty ruleset')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated', type=Path, required=True, help='release directory verified by check_contracts.py')
    args = parser.parse_args()
    try:
        report = assess(args.generated, PublicSuffixes())
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(bool(report['blocked']))


if __name__ == '__main__':
    sys.exit(main())
