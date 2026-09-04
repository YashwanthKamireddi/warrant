"""One definition of how a visitor moves through the console.

Four gates used to each carry their own copy of the click path. When the
console changed shape they all broke separately and were fixed separately,
which is how the SKU drift got in. The path lives here now: change the console,
change this file, and every gate follows.
"""

import os
import pathlib

from playwright.sync_api import Page


def enter(page: Page, base: str, *, agent: str = "auto") -> None:
    """Land in the console with a signed permission already in force.

    It derives and signs on arrival, so there is nothing to click: waiting for
    the permission to name its bounds is waiting for the bootstrap to finish.

    ``agent="manual"`` opens it without the agent running, for the gates that
    measure boxes rather than behaviour -- eleven viewports is eleven live model
    runs otherwise.

    Checks first that something on this port is actually the console. A stray
    process on the verify port -- `warrant api` is an easy one to leave running
    -- otherwise turns into a thirty second wait for a selector that was never
    going to appear, and a failure that reads like a console bug.
    """
    query = "" if agent == "auto" else f"?agent={agent}"
    page.goto(f"{base}/{query}#workspace", wait_until="networkidle")
    if page.locator(".shell, .lp").count() == 0:
        raise AssertionError(
            f"{base} is serving something, but it is not the console. "
            "Another process is probably holding this port."
        )
    page.wait_for_selector(".perm", timeout=30000)
    page.wait_for_selector(".bounds li", timeout=30000)
    page.wait_for_selector(".perm-sig", timeout=30000)


def agent_settled(page: Page, timeout_ms: int = 150_000) -> None:
    """Wait out the live agent, and answer it if it comes back asking.

    The model is live, so a run is not deterministic: sometimes it finds a
    basket the permission covers on its own, and sometimes it lands on an
    escalation and stops, waiting for a person. A gate that only handled the
    first case failed on the second for reasons that had nothing to do with
    what it was testing.
    """
    page.wait_for_selector(".entry:not(.pending)", timeout=timeout_ms)
    page.wait_for_function(
        "!document.querySelector('.entry.pending')", timeout=timeout_ms
    )
    ask = page.locator(".ask .btn-primary")
    if ask.count():
        ask.first.click()
        page.wait_for_function(
            "!document.querySelector('.ask')", timeout=60_000
        )


def scripted_baskets(page: Page, expected: int = 5) -> None:
    """Run the five reference baskets and wait for every verdict to land.

    Each teaches a different refusal -- replay, expiry, a planted product name,
    a merchant swap, a ceiling breach -- and they are real evaluations by the
    same gate, not fixtures with the answers written in.
    """
    before = page.locator(".entry").count()
    page.get_by_role("button", name="Put five harder baskets through it").click()
    page.wait_for_function(
        f"document.querySelectorAll('.entry').length >= {before + expected}",
        timeout=90_000,
    )


def open_proof(page: Page) -> None:
    """Open the drawer that holds the record and the documents."""
    if page.locator(".proof").count() == 0:
        page.get_by_role("button", name="See the record").click()
    page.wait_for_selector(".proof", timeout=15_000)
    page.wait_for_timeout(150)


def load_env(root: pathlib.Path | None = None) -> None:
    """Read .env the way the package does, for scripts that run before it.

    Both live walks carried their own copy of this. Two copies of the same
    eight lines is two places for one of them to stop matching the other.
    Real environment variables win, as they do everywhere else here.
    """
    env = (root or pathlib.Path(__file__).resolve().parents[1]) / ".env"
    if not env.is_file():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
