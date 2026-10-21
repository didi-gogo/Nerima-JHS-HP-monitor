import contextlib
import io
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertEqual(monitor.SCHOOLS[0], (1, "練馬区立みらい青空学園", "miraiaozora"))
        self.assertEqual(monitor.CMS_ID_OVERRIDES[1], 166)
        self.assertEqual(monitor.CMS_ID_OVERRIDES[31], 159)

    def test_failed_school_keeps_previous_snapshot_and_diagnostics(self):
        previous = {"currentHash": "last-good-hash", "lastChangedAt": "2026-10-20T00:00:00Z", "latest": {"title": "前回の記事"}}
        with patch.object(monitor, "fetch", side_effect=RuntimeError("HTTP Error 503: Service Unavailable")):
            result = monitor.monitor_school(monitor.SCHOOLS[0], previous, "2026-10-22T00:00:00Z")
        for key, value in previous.items():
            self.assertEqual(result[key], value)
        self.assertIn("503", result["error"])
        self.assertIn("503", result["warning"])

    def test_all_failures_write_diagnostics_log_errors_and_exit_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "status.json"
            capture = io.StringIO()
            with patch.object(monitor, "SCHOOLS", monitor.SCHOOLS[:2]), patch.object(monitor, "fetch", side_effect=RuntimeError("HTTP Error 503: Service Unavailable")), patch("sys.argv", ["monitor.py", "--output", str(output)]), contextlib.redirect_stdout(capture):
                exit_code = monitor.main()
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertEqual(result["successCount"], 0)
        self.assertEqual(result["errorCount"], 2)
        self.assertIn("checked=2 success=0 errors=2", capture.getvalue())
        for school in result["schools"]:
            self.assertIn(f"School {school['id']} ({school['name']}):", capture.getvalue())
            self.assertIn(school["error"], capture.getvalue())


if __name__ == "__main__":
    unittest.main()
