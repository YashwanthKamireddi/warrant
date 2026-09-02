# Integrating Warrant

Warrant sits between an agent and a payment. The agent proposes a basket; you
ask Warrant whether the person actually permitted it; you pay only if the
answer is yes.

Nothing here is specific to any merchant, country or rail. The examples use a
grocer because a grocer is not interesting.

Every Python block on this page is executed by `make docs-examples` on every
build. If one of them stops working, the build fails. This page cannot drift.

---

## Install

```
pip install git+https://github.com/YashwanthKamireddi/warrant
```

The distribution is `warrant-pay`; the import is `warrant`. (`warrant` on PyPI
is an unrelated Cognito client.)

## Your merchants

An acquirer assigns a merchant a category code at onboarding, and the merchant
does not get to write its own. Warrant checks a basket's declared categories
against what the merchant's acquirer actually underwrote, so it needs your book
of merchants. Copy `warrant.example.toml` and edit it:

```toml
[[merchant]]
id = "acme-grocers"
mcc = "5411"
description = "Grocery stores and supermarkets"
categories = ["grocery", "food_beverage"]
```

A merchant that is not in this file permits **nothing**. Unregistered fails
closed, never open.

---

## In your code

Three calls. One when the person approves, one per basket, and one if they
change their mind.

```python
import time

from warrant import Warrant
from warrant.models import Scope

now = int(time.time())
warrant = Warrant(merchants="warrant.example.toml")

# 1. The person approves, once. These bounds usually come from a form they
#    filled in -- an amount, a merchant, a category, a duration.
permission = warrant.permit(
    "lunch for the team",
    scope=Scope(
        merchants=("acme-grocers",),
        categories=("food_beverage",),
        max_total_paise=100_000,
        max_per_txn_paise=50_000,
        max_txns=3,
        not_before=now,
        expires_at=now + 7200,
    ),
)

# Show them this before anything is signed.
print(permission.approval_prompt)

# 2. The agent proposes a basket. Check it before you charge anything.
decision = warrant.check(permission, "acme-grocers", [
    {"sku": "sandwich", "category": "food_beverage", "qty": 2, "unit_paise": 24_000},
])
assert decision.allowed

# The same basket, with something nobody asked for in it.
refused = warrant.check(permission, "acme-grocers", [
    {"sku": "cable", "category": "electronics", "qty": 1, "unit_paise": 29_900},
])
assert not refused.allowed
print(refused.reasons[0])

# 3. Charge it. spend() decides and places the debit in one step, and records
#    the decision either way.
paid = warrant.spend(permission, "acme-grocers", [
    {"sku": "sandwich", "category": "food_beverage", "qty": 2, "unit_paise": 24_000},
])
assert paid.settled

warrant.close()
```

`check()` is side-effect free: no budget consumed, no attempt spent, nothing
written. Use it to show someone what would happen. Use `spend()` to make it
happen.

### Verdicts

| | |
|---|---|
| `allow` | Every bound the person signed is satisfied. |
| `block` | Something is outside the permission. `decision.reasons` says what. |
| `escalate` | Nothing is violated, but it is worth a human glance — approaching the ceiling, or over a step-up threshold. `decision.needs_approval` is true. |

`escalate` is not a refusal and not an allow. Treating it as either throws away
the only signal that says "this is technically fine and still surprising".

---

## As a service

If your agent runs somewhere else, mount the router into your existing app.

```python
from fastapi import FastAPI

from warrant import Warrant
from warrant.service import warrant_router

app = FastAPI()

@app.get("/orders")
def orders() -> dict[str, str]:
    return {"your": "routes are untouched"}

app.include_router(warrant_router(Warrant(merchants="warrant.example.toml")))

# Your routes are untouched, and Warrant answers beside them.
from fastapi.testclient import TestClient

with TestClient(app) as client:
    assert client.get("/orders").json() == {"your": "routes are untouched"}
    assert client.get("/warrant/ready").json()["status"] == "ready"
```

Or run it standalone:

```
warrant api --port 8080 --ledger ./warrant.db --merchants ./warrant.toml
```

### Endpoints

| | |
|---|---|
| `POST /warrant/permissions` | Sign what the person approved. Returns an id. |
| `POST /warrant/permissions/{id}/check` | Would this basket be allowed? Always `200`, including when the answer is no — the caller asked a question. |
| `POST /warrant/permissions/{id}/spend` | Decide and charge. `200` if allowed, `403` if blocked, `409` if it needs approval. |
| `POST /warrant/permissions/{id}/revoke` | Stop it being spendable. `204`. |
| `GET  /warrant/permissions/{id}/evidence` | What you would file if the charge is disputed. |
| `GET  /warrant/health` | Liveness. |
| `GET  /warrant/ready` | Readiness — round-trips the ledger. A process whose ledger is unreachable is alive and must not be sent traffic. |

A refusal carries the same body a success would. An agent that has to infer
*why* it was refused from a status code will infer wrong.

---

## Production notes

Things that are fine for an evaluation and wrong for a deployment.

**Key custody.** `Warrant()` generates a signing key if you do not give it one,
and the service holds the subject's key in process. In a real deployment the
subject's key lives on the subject's device and the service only ever verifies
signatures. `POST /permissions` reports `key_custody` so an integrator finds
this out from the API rather than from the source.

```python
from warrant import Warrant
from warrant.crypto import SigningKey

# A generated key means last week's receipts cannot be verified by this
# week's process. Load yours.
warrant = Warrant(key=SigningKey.from_seed("replace-me-with-real-key-material"))
warrant.close()
```

**Durability.** The default ledger is in memory. Pass a path, and back it up:
the ledger is the record you produce when someone disputes a charge.

**The permission store** in the service is bounded and not durable. A restart
loses the permissions it held; the ledger survives, and a permission is
re-signable.

**Envelope.** `Envelope` is the hard outer bound no derived scope may exceed —
the ceiling on the ceiling. Set it to what your business can actually tolerate
losing, because it is what stands between you and a model that proposes
something absurd.

---

## What Warrant does not do

It does not detect fraud. Fraud detection asks whether a payment looks like a
bad actor; Warrant asks whether the account holder permitted this particular
purchase. Both, or neither.

It does not catch a merchant mislabelling its own catalogue. A merchant whose
MCC permits food, listing a power bank as food, passes. Catching that needs the
purchased item as the rail sees it, which no metadata layer can reach.

It does not stop everything. Over 540 labelled cases it lets 90 through. It
also never once stopped a purchase the person actually authorised, which is the
number a merchant cares about.
