"""Tests for the added tooling: evidence gate, segment warning, finalize."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
EX = os.path.join(os.path.dirname(HERE), "examples")
sys.path.insert(0, SCRIPTS)

import finalize  # noqa: E402
import render_html  # noqa: E402
import validate_master as V  # noqa: E402


def _spec(**over):
    sc = {"id": "t", "title": "T", "actors": [{"id": "a", "label": "A", "zone": "server"},
                                              {"id": "b", "label": "B", "zone": "database"}],
          "messages": [{"from": "a", "to": "b", "text": "go"}, {"from": "b", "to": "a", "text": "ok", "kind": "ret"}]}
    sc.update(over)
    return {"scenarios": [sc]}


class TestEvidence(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.repo, "src", "x"))
        open(os.path.join(self.repo, "src", "x", "Real.cs"), "w").close()

    def test_real_and_prose_pass_fake_fails(self):
        m = _spec(source_paths=["src/x", "src/nope"])
        m["scenarios"][0]["messages"][0]["src"] = "Real.cs → Ghost.ts, this is prose"
        w = V.check_evidence(m, self.repo)
        self.assertEqual(len(w), 2, w)
        self.assertTrue(any("src/nope" in x for x in w))
        self.assertTrue(any("Ghost.ts" in x for x in w))

    def test_any_of_several_repos_is_enough(self):
        other = tempfile.mkdtemp()
        open(os.path.join(other, "Other.ts"), "w").close()
        m = _spec()
        m["scenarios"][0]["messages"][0]["src"] = "Other.ts"
        self.assertEqual(V.check_evidence(m, [self.repo, other]), [])
        self.assertEqual(len(V.check_evidence(m, [self.repo])), 1)


class TestSegments(unittest.TestCase):
    def test_second_segment_without_range_warns(self):
        m = _spec(fragments=[{"kind": "alt", "label": "x", "range": [0, 1],
                              "segments": [{"guard": "a"}, {"guard": "b"}]}])
        _, warns = V.validate(m)
        self.assertTrue(any("divider will NOT be drawn" in w for w in warns), warns)

    def test_second_segment_with_range_is_clean(self):
        m = _spec(fragments=[{"kind": "alt", "label": "x", "range": [0, 1],
                              "segments": [{"guard": "a"}, {"guard": "b", "range": [1, 1]}]}])
        _, warns = V.validate(m)
        self.assertFalse(any("divider" in w for w in warns), warns)


class TestFinalize(unittest.TestCase):
    def _run(self, spec):
        with tempfile.TemporaryDirectory() as d:
            p, out = os.path.join(d, "m.json"), os.path.join(d, "o.html")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(spec, f, ensure_ascii=False)
            r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "finalize.py"), p, out, "--no-browser"],
                               capture_output=True, text=True, encoding="utf-8")
            return r.returncode, os.path.exists(out), r.stdout

    def test_valid_spec_renders(self):
        code, wrote, _ = self._run(_spec())
        self.assertEqual((code, wrote), (0, True))

    def test_invalid_spec_fails_before_render(self):
        bad = _spec()
        bad["scenarios"][0]["messages"][0]["to"] = "ghost"
        code, wrote, out = self._run(bad)
        self.assertEqual((code, wrote), (1, False), out)

    def test_blank_page_fails_browser_gate(self):
        if not finalize.find_browser():
            self.skipTest("no Chrome/Edge available")
        real = render_html.emit_page
        render_html.emit_page = lambda m: "<html><body>blank</body></html>"
        try:
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "m.json")
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(_spec(), f)
                old = sys.argv
                sys.argv = ["finalize.py", p, os.path.join(d, "o.html")]
                with self.assertRaises(SystemExit) as cm:
                    finalize.main()
                sys.argv = old
                self.assertEqual(cm.exception.code, 1)
        finally:
            render_html.emit_page = real


if __name__ == "__main__":
    unittest.main()
