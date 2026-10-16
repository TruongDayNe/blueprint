#!/usr/bin/env python3
"""One-shot delivery gate (archify's `finalize` idea): validate -> evidence -> stamp -> render ->
real-browser check. Exits non-zero on the first failing gate, so "done" means every gate passed.

Usage: python3 finalize.py <master.json> <out.html> [--repo DIR]... [--strict-evidence]
                           [--no-browser] [--png out.png]

The browser gate loads the rendered page in headless Chrome/Edge (BLUEPRINT_BROWSER overrides the
path), dumps the DOM after scripts ran, and checks that every scenario title and every message
label is actually present - catching a blank page or a JS failure that a static render cannot.
"""
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_html  # noqa: E402
import validate_master as V  # noqa: E402

_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser():
    env = os.environ.get("BLUEPRINT_BROWSER")
    if env and os.path.exists(env):
        return env
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    return next((c for c in _CANDIDATES if os.path.exists(c)), None)


def browser_dump(browser, page):
    uri = "file:///" + os.path.abspath(page).replace("\\", "/").lstrip("/")
    with tempfile.TemporaryDirectory() as profile:
        r = subprocess.run([browser, "--headless=new", "--disable-gpu", f"--user-data-dir={profile}",
                            "--virtual-time-budget=6000", "--dump-dom", uri],
                           capture_output=True, timeout=120)
    return r.stdout.decode("utf-8", errors="replace")


def browser_png(browser, page, png):
    uri = "file:///" + os.path.abspath(page).replace("\\", "/").lstrip("/")
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([browser, "--headless=new", "--disable-gpu", f"--user-data-dir={profile}",
                        "--window-size=1400,1000", "--virtual-time-budget=8000",
                        f"--screenshot={os.path.abspath(png)}", uri], capture_output=True, timeout=120)


def labels(m):
    for sc in (m.get("scenarios") or [m]):
        yield sc.get("title", "")
        for msg in sc.get("messages", []):
            if "phase" not in msg and "note" not in msg and msg.get("text"):
                yield msg["text"]


def fail(gate, detail):
    print(f"FAIL [{gate}] {detail}")
    sys.exit(1)


def main():
    for st in (sys.stdout, sys.stderr):
        if hasattr(st, "reconfigure"):
            st.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:]
    repos = [argv[k + 1] for k, a in enumerate(argv[:-1]) if a == "--repo"]
    png = argv[argv.index("--png") + 1] if "--png" in argv else None
    skip = {png, *repos} - {None}
    pos = [a for a in argv if not a.startswith("--") and a not in skip]
    if len(pos) != 2:
        raise SystemExit(__doc__)
    master, out = pos

    with open(master, encoding="utf-8") as f:
        m = json.load(f)

    errs, warns = V.validate(m)
    ev = V.check_evidence(m, repos) if repos else []
    (errs if "--strict-evidence" in argv else warns).extend(ev)
    for w in warns:
        print("  warn:", w)
    if errs:
        fail("validate", "; ".join(errs))
    print("ok   [validate]" + (" [evidence]" if repos else ""))

    if repos:
        head = subprocess.run(["git", "-C", repos[0], "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if head:
            m.setdefault("provenance", {})["git_sha"] = head
            with open(master, "w", encoding="utf-8") as f:
                json.dump(m, f, indent=2, ensure_ascii=False)
            print(f"ok   [stamp] {head[:10]}")

    try:
        page = render_html.emit_page(m)
    except ValueError as e:
        fail("render", str(e))
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"ok   [render] {out} ({len(page) // 1024} KB)")

    if "--no-browser" in argv:
        print("skip [browser] --no-browser")
        return
    browser = find_browser()
    if not browser:
        print("skip [browser] no Chrome/Edge found (set BLUEPRINT_BROWSER)")
        return
    dom = html.unescape(browser_dump(browser, out))
    missing = [t for t in dict.fromkeys(labels(m)) if t and t not in dom]
    if len(dom) < 2000 or missing:
        fail("browser", f"{len(missing)} label(s) missing from the rendered DOM, e.g. {missing[:3]}")
    print("ok   [browser] every title and message label present in the live DOM")
    if png:
        browser_png(browser, out, png)
        print(f"ok   [png] {png}")


if __name__ == "__main__":
    main()
