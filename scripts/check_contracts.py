"""Validate public metadata contracts and documentation links offline."""
import json
from pathlib import Path
import re
import tempfile
import jsonschema
from build_rules import build, REGISTRY
from test_build_rules import SourceGenerationTests

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
    output=Path(folder); build(SourceGenerationTests().fixture(),output)
    for name in ('manifest','index'):
        jsonschema.Draft202012Validator(json.loads((root/'schemas'/f'{name}.schema.json').read_text()),format_checker=jsonschema.FormatChecker()).validate(json.loads((output/f'{name}.json').read_text()))
for entry in REGISTRY['inputs'].values():
    if entry['repository'] not in {p['id'] for p in REGISTRY['projects']}:raise ValueError('source_not_attributed')
notice=(root/'NOTICE.md').read_text(encoding='utf-8')
for project in REGISTRY['projects']:
    if project['url'] not in notice:raise ValueError('notice_source_missing')
for p in [root/'README.md',root/'AGENTS.md',*list((root/'docs').glob('*.md'))]:
    for link in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf-8')):
        if '://' not in link and not link.startswith('#') and not (p.parent/link.split('#')[0]).exists():raise ValueError('missing_doc_link:'+link)
print(json.dumps({'schemas':2,'sources':len(REGISTRY['projects']),'documentation_links':'passed'}))
