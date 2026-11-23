"""Regression cases for offline documentation checks and unittest discovery."""
from collections import Counter
from pathlib import Path
import tempfile
import unittest

from check_contracts import check_local_links


class MaintenanceTests(unittest.TestCase):
    def test_local_links_cover_picture_sources_and_github_fragments(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = root / 'README.md'
            content = '''# 规则说明

## 规则说明

<a id="入口"></a>

[首页](#规则说明) · [第二处](#规则说明-1) · [固定入口](#入口)

<picture>
  <source srcset="mobile.svg">
  <img src="desktop.svg">
</picture>

```md
[This is a sample](missing.md)
```
'''
            document.write_text(content, encoding='utf-8')
            images = [root / 'mobile.svg', root / 'desktop.svg']
            for image in images:
                image.touch()
            check_local_links([document])
            for image in images:
                with self.subTest(image=image.name):
                    image.unlink()
                    with self.assertRaisesRegex(ValueError, image.name):
                        check_local_links([document])
                    image.touch()
            document.write_text(content.replace('## 规则说明', '## 另一标题'), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'fragment'):
                check_local_links([document])

    def test_discovery_contains_no_duplicate_ids(self):
        suite = unittest.TestLoader().discover(str(Path(__file__).resolve().parent))
        pending = [suite]
        counts = Counter()
        while pending:
            item = pending.pop()
            if isinstance(item, unittest.TestSuite):
                pending.extend(item)
            else:
                counts[item.id()] += 1
        self.assertEqual([name for name, count in counts.items() if count > 1], [])
