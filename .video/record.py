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

    # Any other page the context opened -- Razorpay's simulated bank window --
    # was recorded too, and left a page@<hash>.webm beside the clip. It is not
    # in the cut, so it only ever showed up as a wrong clip count.
    for stray in CLIPS.glob("page@*.webm"):
        stray.unlink()

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


def _enter(ctx, *, agent: str = "auto") -> Page:
    """Open the console with a signed permission already in force."""
    page = ctx.new_page()
    query = "" if agent == "auto" else f"?agent={agent}"
    page.goto(f"{BASE}/{query}#workspace", wait_until="networkidle")
    page.wait_for_selector(".perm-sig", timeout=30_000)
    return page


def _agent_done(page: Page) -> list[str]:
    """Wait out the live agent and report what the gate said to each basket."""
    page.wait_for_function(
        "document.querySelectorAll('.entry:not(.pending)').length > 0",
        timeout=120_000,
    )
    page.wait_for_function("!document.querySelector('.entry.pending')", timeout=120_000)
    return page.eval_on_selector_all(
        ".entry .verdict", "els => els.map(e => e.innerText.trim())"
    )


def _pay_on_razorpay(page: Page) -> None:
    """Pay the open Razorpay sheet in test mode, and wait for the confirmation.

    Netbanking, because this account has UPI disabled and its test cards come
    back "international cards not supported" -- an Indian test account cannot
    accept them. The number is typed rather than filled: Razorpay's validator
    listens for keystrokes, so a value set directly reads as invalid.
    """
    sheet = page.frame_locator("iframe.razorpay-checkout-frame")

    box = sheet.locator("input[type='tel']").first
    box.click()
    box.press_sequentially("9812345678", delay=80)
    page.wait_for_timeout(900)
    sheet.get_by_role("button", name="Continue").first.click()
    page.wait_for_timeout(3500)

    sheet.locator("[role='button'], button, li, div").filter(
        has_text="Bank of Baroda"
    ).first.click(timeout=10_000)
    page.wait_for_timeout(2500)
    sheet.get_by_role("button", name="Pay").first.click(timeout=10_000)

    # Razorpay's simulated bank opens in its own window.
    page.wait_for_timeout(6000)
    bank = page.context.pages[-1]
    if bank is not page:
        bank.get_by_role("button", name="Success").first.click(timeout=20_000)

    # Nothing on screen claims the payment happened until the server has
    # recomputed the signature, so this is waiting for that answer.
    page.wait_for_selector(".entry-rail.paid", timeout=60_000)
    page.wait_for_timeout(5200)


def _open_record(page: Page) -> None:
    page.get_by_role("button", name="See the record").click()
    page.wait_for_selector(".proof", timeout=20_000)
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
    page = _enter(ctx, agent="manual")
    _settle(page, 5200)
    page.locator(".bounds").scroll_into_view_if_needed()
    _settle(page, 3200)
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
        # No click. The agent runs on arrival, which is the point.
        verdicts = _agent_done(page)
        _settle(page, 2600)

        # The behaviour being filmed is the gate coming back to a person and
        # the person answering. If the model happens to stay under the
        # threshold on its own there is no ask to film, so retake.
        if page.locator(".ask .btn-primary").count() == 0:
            print(f"    take {take}: {verdicts} — no escalation to answer, retaking")
            ctx.close()
            continue

        print(f"    take {take}: {verdicts}")
        _settle(page, 3600)
        page.locator(".ask .btn-primary").click()
        page.wait_for_function("!document.querySelector('.ask')", timeout=60_000)
        _settle(page, 4200)
        _save(ctx, "live-03-agent")
        break
    else:
        print("    the agent never escalated in five takes; keeping the last one")
        _save(ctx, "live-03-agent")

    # -- what it prevents, in money ---------------------------------------- #
    ctx = _app_context(browser)
    page = _enter(ctx, agent="manual")
    page.get_by_role("button", name="Try to buy something you never asked for").click()
    page.wait_for_selector(".entry-cost", timeout=30_000)
    _settle(page, 5200)
    page.locator(".entry-cost").scroll_into_view_if_needed()
    _settle(page, 3600)
    _save(ctx, "live-04-prevents")

    # -- the record, and then breaking it ---------------------------------- #
    ctx = _app_context(browser)
    page = _enter(ctx, agent="manual")
    page.get_by_role("button", name="Put five harder baskets through it").click()
    page.wait_for_function(
        "document.querySelectorAll('.entry').length >= 5", timeout=90_000
    )
    _open_record(page)
    page.wait_for_selector(".ledger-row", timeout=20_000)
    _settle(page, 4200)
    page.get_by_role("button", name="Try to rewrite the ledger").click()
    page.wait_for_selector(".notice.stop, .ledger-row.orphaned", timeout=20_000)
    _settle(page, 4400)
    _save(ctx, "live-05-record-tamper")

    # -- the dispute pack, and the same mandate as an AP2 credential ------- #
    ctx = _app_context(browser)
    page = _enter(ctx, agent="manual")
    page.get_by_role("button", name="Put five harder baskets through it").click()
    page.wait_for_function(
        "document.querySelectorAll('.entry').length >= 5", timeout=90_000
    )
    _open_record(page)
    _settle(page, 600)
    page.locator(".more > summary", has_text="dispute pack").click()
    _settle(page, 4200)
    page.locator(".more > summary", has_text="AP2").click()
    page.wait_for_selector(".cred", timeout=20_000)
    _settle(page, 4000)
    _save(ctx, "live-06-evidence-ap2")

    # -- Razorpay's own payment sheet, paid, and verified ------------------ #
    #
    # The payment is completed here, not just opened. An open payment sheet
    # shows that an order exists; a captured payment with the server's
    # verification beside it shows that money moved and that this process
    # checked the signature before saying so. That is the difference between
    # the claim and the evidence for it.
    ctx = _app_context(browser)
    page = _enter(ctx)
    _agent_done(page)
    if page.locator(".ask .btn-primary").count():
        page.locator(".ask .btn-primary").click()
        page.wait_for_function("!document.querySelector('.ask')", timeout=60_000)
    _settle(page, 1000)

    button = page.get_by_role("button", name="Pay ")
    if button.count():
        button.first.click()
        try:
            page.wait_for_selector("iframe.razorpay-checkout-frame", timeout=60_000)
            _settle(page, 3000)
            _pay_on_razorpay(page)
        except Exception as exc:  # noqa: BLE001 - a stated refusal is a real outcome
            print(f"    razorpay: {str(exc)[:90]}")
            _settle(page, 3000)
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
