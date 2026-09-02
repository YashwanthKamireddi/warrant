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
    """
    page.goto(f"{base}/#workspace", wait_until="networkidle")
    page.wait_for_selector(".certificate", timeout=30000)
    page.wait_for_selector(".seal:not(.unsigned)", timeout=30000)


def step(page: Page, name: str) -> None:
    """Move to one act of the walkthrough and wait for it to paint."""
    n = STEPS[name]
    page.locator(f".stepbtn:nth-of-type({n})").click()
    page.wait_for_selector(".act", timeout=15000)
    page.wait_for_timeout(120)


def scripted_baskets(page: Page, expected: int = 5) -> None:
    """Run the five-basket script and wait for every verdict to land."""
    step(page, "prevents")
    page.get_by_role("button", name="Run five scripted baskets").click()
    page.wait_for_function(
        f"document.querySelectorAll('.decision').length === {expected}",
        timeout=60000,
    )
