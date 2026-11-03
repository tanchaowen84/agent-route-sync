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
def anchors(p):
    text=p.read_text(encoding='utf-8')
    return set(re.findall(r'<a id="([^"]+)"',text))|{re.sub(r'[^\w\- ]','',h).strip().lower().replace(' ','-') for h in re.findall(r'^#+\s+(.+)$',text,re.M)}
for p in [root/'README.md',root/'AGENTS.md',*list((root/'docs').glob('*.md')),root/'examples/README.md']:
    for link in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf-8')):
        if '://' in link:continue
        path,_,anchor=link.partition('#')
        target=p.parent/path if path else p
        if not target.exists():raise ValueError('missing_doc_link:'+link)
        if anchor and anchor not in anchors(target):raise ValueError('missing_doc_anchor:'+link)
print(json.dumps({'schemas':2,'sources':len(REGISTRY['projects']),'documentation_links':'passed'}))
