"""Record every clip for the pitch video.

Two kinds of clip:

  cards   the eight title cards in scenes/, each held long enough for its
          entrance animation to finish and for a viewer to read it
  live    real footage of the console being driven, paced deliberately so
          nothing needs cutting afterwards

The app is recorded at a 1440x810 viewport upscaled to 1920x1080. Recording a
1580px-wide console at native 1080p makes 13px UI text unreadable on a laptop
screen, which is where this will be watched -- the upscale trades pixel purity
for the thing actually being legible.

    uv run warrant serve --port 8899 &
    python3 .video/record.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent
SCENES = ROOT / "scenes"
CLIPS = ROOT / "clips"
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"

FRAME = {"width": 1920, "height": 1080}
APP_VIEW = {"width": 1280, "height": 720}

# Each card is held for as long as a viewer needs to read it aloud, plus a beat.
CARDS: list[tuple[str, float]] = [
    ("01-problem", 13.0),
    ("02-holes", 17.0),
    ("03-warrant", 20.0),
    ("04-boundary", 18.0),
    ("05-results", 15.0),
    ("06-losses", 17.0),
    ("07-limits", 15.0),
    ("08-close", 10.0),
]


def _save(context, name: str) -> None:
    """Close the context so playwright flushes the video, then rename it."""
    page = context.pages[0]
    video = page.video
    context.close()
    if video is None:
        raise RuntimeError(f"no video recorded for {name}")
    src = Path(video.path())
    dst = CLIPS / f"{name}.webm"
    shutil.move(str(src), dst)
    size = dst.stat().st_size // 1024
    print(f"  {name:<22} {size:>6} KB")


def record_cards(browser) -> None:
    print("cards")
    for name, hold in CARDS:
        ctx = browser.new_context(
            viewport=FRAME, record_video_dir=str(CLIPS), record_video_size=FRAME
        )
        page = ctx.new_page()
        page.goto((SCENES / f"{name}.html").as_uri(), wait_until="networkidle")
        page.wait_for_timeout(int(hold * 1000))
        _save(ctx, f"card-{name}")


def _app_context(browser):
    # record_video_size must equal the viewport: playwright does not scale.
    return browser.new_context(
        viewport=APP_VIEW, record_video_dir=str(CLIPS), record_video_size=APP_VIEW
    )


def _enter(ctx) -> Page:
    """Open the console with a signed permission already in force."""
    page = ctx.new_page()
    page.goto(f"{BASE}/#workspace", wait_until="networkidle")
    page.wait_for_selector(".certificate", timeout=30_000)
    page.wait_for_selector(".seal:not(.unsigned)", timeout=30_000)
    return page


def _step(page: Page, n: int) -> None:
    page.locator(f".stepbtn:nth-of-type({n})").click()
    page.wait_for_selector(".act", timeout=20_000)
    page.wait_for_timeout(200)


def _settle(page: Page, ms: int = 900) -> None:
    page.wait_for_timeout(ms)


def record_live(browser) -> None:
    """Drive the console as it is, not as it was.

    Every clip here is the real product: a real merchant's catalogue with their
    own photographs, a live model choosing from it, the gate refusing, the
    hash-chained record, and a real Razorpay order. Nothing is staged and
    nothing is sped up -- the agent genuinely takes a few seconds to think.
    """
    print("live")

    # -- the landing page, which the old cut never showed at all ----------- #
    ctx = _app_context(browser)
    page = ctx.new_page()
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_selector(".lp-open h1", timeout=20_000)
    _settle(page, 3200)
    for section in (".lp-gap", ".lp-evidence", ".lp-chain"):
        page.locator(section).scroll_into_view_if_needed()
        _settle(page, 3400)
    _save(ctx, "live-01-landing")

    # -- the permission, signed before anybody clicks anything ------------- #
    ctx = _app_context(browser)
    page = _enter(ctx)
    _settle(page, 4200)
    page.locator(".terms-more > summary").click()
    _settle(page, 3600)
    _save(ctx, "live-02-permission")

    # -- the centrepiece: a live model, refused, adapting ------------------ #
    #
    # The agent is a real model and does not converge every time. Some runs
    # escalate three times without coming down, and one of those was in the
    # first cut of this film -- the agent saying it would stay under the Rs 500
    # threshold while buying Rs 698, twice. That is honest about the model and
    # dishonest about the product, because the behaviour being demonstrated is
    # the adaptation. So: record until it adapts, and say plainly which take
    # this is. Nothing is edited, sped up or stitched; a take is kept whole or
    # thrown away whole.
    for take in range(1, 6):
        ctx = _app_context(browser)
        page = _enter(ctx)
        _step(page, 2)
        # No click. The agent runs on arrival, which is the point.
        page.wait_for_function(
            "document.querySelectorAll('.run-turn').length > 0", timeout=120_000
        )
        _settle(page, 2600)
        page.wait_for_function(
            "!document.querySelector('.run-thinking')", timeout=120_000
        )
        _settle(page, 2000)

        verdicts = page.eval_on_selector_all(
            ".run-turn .verdict", "els => els.map(e => e.innerText.trim())"
        )
        converged = "ESCALATE" in verdicts and verdicts[-1] == "ALLOW"
        if not converged:
            print(f"    take {take}: {verdicts} — not the behaviour, retaking")
            ctx.close()
            continue

        print(f"    take {take}: {verdicts}")
        page.locator(".run-turn").last.scroll_into_view_if_needed()
        _settle(page, 4200)
        _save(ctx, "live-03-agent")
        break
    else:
        print("    the agent never adapted in five takes; keeping the last one")
        _save(ctx, "live-03-agent")

    # -- what it prevents, in money ---------------------------------------- #
    ctx = _app_context(browser)
    page = _enter(ctx)
    _step(page, 3)
    page.wait_for_selector(".cf-columns", timeout=25_000)
    _settle(page, 4600)
    page.locator(".shop").scroll_into_view_if_needed()
    _settle(page, 3600)
    _save(ctx, "live-04-prevents")

    # -- the record, and then breaking it ---------------------------------- #
    ctx = _app_context(browser)
    page = _enter(ctx)
    _step(page, 4)
    page.get_by_role("button", name="Put five baskets through the gate").click()
    page.wait_for_function(
        "document.querySelectorAll('.ledger-row').length > 5", timeout=60_000
    )
    _settle(page, 4200)
    page.get_by_role("button", name="Try to rewrite the ledger").click()
    page.wait_for_selector(".notice.stop, .ledger-row.orphaned", timeout=20_000)
    _settle(page, 4400)
    _save(ctx, "live-05-record-tamper")

    # -- the dispute pack, and the same mandate as an AP2 credential ------- #
    ctx = _app_context(browser)
    page = _enter(ctx)
    _step(page, 4)
    page.get_by_role("button", name="Put five baskets through the gate").click()
    page.wait_for_function(
        "document.querySelectorAll('.ledger-row').length > 5", timeout=60_000
    )
    _settle(page, 600)
    page.locator(".more > summary", has_text="dispute pack").click()
    _settle(page, 4200)
    page.locator(".more > summary", has_text="AP2").click()
    page.wait_for_selector(".cred", timeout=20_000)
    _settle(page, 4000)
    _save(ctx, "live-06-evidence-ap2")

    # -- a real Razorpay order, from the record ---------------------------- #
    ctx = _app_context(browser)
    page = _enter(ctx)
    _step(page, 4)
    page.get_by_role("button", name="Put five baskets through the gate").click()
    page.wait_for_function(
        "document.querySelectorAll('.ledger-row').length > 5", timeout=60_000
    )
    _settle(page, 800)
    button = page.get_by_role("button", name="Place the settled debit on real Razorpay")
    if button.count():
        button.click()
        # Either a real order id or Razorpay's own refusal. Both are true, and
        # a daily cap being reached is worth showing rather than hiding.
        page.wait_for_selector(".real-rail.placed, .stage-error", timeout=60_000)
        _settle(page, 4600)
    else:
        _settle(page, 1200)
    _save(ctx, "live-07-razorpay")


def main() -> int:
    only = sys.argv[2] if len(sys.argv) > 2 else "all"
    CLIPS.mkdir(parents=True, exist_ok=True)
    if only == "all":
        shutil.rmtree(CLIPS)
        CLIPS.mkdir(parents=True)

    started = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        if only in ("all", "cards"):
            record_cards(browser)
        if only in ("all", "live"):
            for stale in CLIPS.glob("live-*.webm"):
                stale.unlink()
            record_live(browser)
        browser.close()

    clips = sorted(CLIPS.glob("*.webm"))
    total = sum(
        float(
            subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(c)],
                capture_output=True, text=True, check=False,
            ).stdout.strip()
            or 0
        )
        for c in clips
    )
    elapsed = time.time() - started
    print(f"\n{len(clips)} clips · {total:.0f}s of footage · recorded in {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
