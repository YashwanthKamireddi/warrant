"""One definition of how a visitor moves through the console.

Four gates used to each carry their own copy of the click path. When the
console changed shape they all broke separately and were fixed separately,
which is how the SKU drift got in. The path lives here now: change the console,
change this file, and every gate follows.
"""

from playwright.sync_api import Page

STEPS = {
    "permission": 1,
    "agent": 2,
    "prevents": 3,
    "record": 4,
}


def enter(page: Page, base: str) -> None:
    """Land in the workspace with a signed permission already in force.

    The console derives and signs on arrival, so there is nothing to click:
    waiting for the certificate is waiting for the bootstrap to finish.

    Checks first that something on this port is actually the console. A stray
    process on the verify port -- `warrant api` is an easy one to leave running
    -- otherwise turns into a thirty second wait for a selector that was never
    going to appear, and a failure that reads like a console bug.
    """
    page.goto(f"{base}/#workspace", wait_until="networkidle")
    if page.locator(".shell, .lp").count() == 0:
        raise AssertionError(
            f"{base} is serving something, but it is not the console. "
            "Another process is probably holding this port."
        )
    page.wait_for_selector(".certificate", timeout=30000)
    page.wait_for_selector(".seal:not(.unsigned)", timeout=30000)


def step(page: Page, name: str) -> None:
    """Move to one act of the walkthrough and wait for it to paint."""
    n = STEPS[name]
    page.locator(f".stepbtn:nth-of-type({n})").click()
    page.wait_for_selector(".act", timeout=15000)
    page.wait_for_timeout(120)


def scripted_baskets(page: Page, expected: int = 5) -> None:
    """Run the five reference baskets and wait for every verdict to land.

    They live on the record now. They used to sit beside the live agent as a
    second way to do the same thing, which made the fixture compete with the
    real model for the reader's attention -- and the fixture won, because it was
    instant.
    """
    step(page, "record")
    page.get_by_role("button", name="Put five baskets through the gate").click()
    page.wait_for_function(
        f"document.querySelectorAll('.ledger-row').length > {expected}",
        timeout=60000,
    )
    # The verdicts are rendered where the baskets are proposed; the record is
    # where they end up. Both are true and they are different screens.
    step(page, "prevents")
    page.wait_for_function(
        f"document.querySelectorAll('.decision').length === {expected}",
        timeout=30000,
    )
