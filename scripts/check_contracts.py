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
    output = Path(folder)
    build(SourceGenerationTests().fixture(), output)
    metadata = {}
    for name in ('manifest', 'index'):
        metadata[name] = json.loads((output / f'{name}.json').read_text(encoding='utf-8'))
        schema = json.loads((root / 'schemas' / f'{name}.schema.json').read_text(encoding='utf-8'))
        jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(metadata[name])

index = metadata['index']
rule_urls = [dataset['resources'][fmt]['url'] for dataset in index['datasets']
             for fmt in ('mihomo', 'surge', 'sing-box')]
readme = (root / 'README.md').read_text(encoding='utf-8')
rule_table = '\n'.join(line for line in readme.splitlines() if line.startswith('|'))
table_urls = re.findall(r'\]\(([^)]+)\)', rule_table)
if [url for url in table_urls if url.startswith(index['base_url'])] != rule_urls:
    raise ValueError('readme_rule_table_does_not_match_index')

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
print(json.dumps({'schemas': 2, 'sources': len(REGISTRY['projects']), 'readme_rule_links': len(rule_urls),
                  'documentation_links': 'passed'}))
