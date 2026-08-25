import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "monitor.py"
SPEC = importlib.util.spec_from_file_location("monitor", MODULE_PATH)
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


class MonitorTests(unittest.TestCase):
    def test_discovers_rss_and_frame(self):
        source = '''<link rel="alternate" type="application/rss+xml" href="https://cms.nerima-tky.ed.jp/weblog/rss2.php?id=206">
        <frame src="https://cms.nerima-tky.ed.jp/swas/index.php?id=206">'''
        rss, cms = monitor.discover_targets(source, "https://www.nerima-tky.ed.jp/kaishin2-j/")
        self.assertEqual(rss, "https://cms.nerima-tky.ed.jp/weblog/rss2.php?id=206")
        self.assertEqual(cms, "https://cms.nerima-tky.ed.jp/swas/index.php?id=206")

    def test_normalization_removes_volatile_markup(self):
        first = '<body id="page_abcdef"><script>now=1</script><p>学校  情報</p><div class="statistics"><p>本日：1</p></div><span class="accesscount"><img alt="1"></span></body>'
        second = '<body id="page_123456"><script>now=2</script>\n<p>学校 情報</p><div class="statistics"><p>本日：9</p></div><span class="accesscount"><img alt="9"></span></body>'
        self.assertEqual(monitor.normalize_html(first), monitor.normalize_html(second))

    def test_rss_hash_changes_for_article_edit(self):
        before = '''<?xml version="1.0"?><rss><channel><item><title>行事</title><guid>1</guid><description>内容A</description></item></channel></rss>'''
        after = before.replace("内容A", "内容B")
        items_before, latest = monitor.parse_rss(before)
        items_after, _ = monitor.parse_rss(after)
        self.assertEqual(latest["title"], "行事")
        self.assertNotEqual(monitor.digest({"rss": items_before}), monitor.digest({"rss": items_after}))

    def test_integrated_school_uses_shared_cms(self):
        self.assertEqual(monitor.CMS_ID_OVERRIDES[31], 159)


if __name__ == "__main__":
    unittest.main()
