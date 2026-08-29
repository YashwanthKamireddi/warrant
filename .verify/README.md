# Browser verification

`npm run build` proves the TypeScript compiled. It says nothing about whether the
page renders, whether the API answers, or whether anything throws at runtime.

```
uv run warrant serve --port 8805 &
python3 .verify/walk.py http://127.0.0.1:8805
```

Walks the whole flow — derive, approve, five scripted baskets, ledger, evidence,
tamper, theme toggle — captures a screenshot at each step into `shots/`, and
exits non-zero on any console error or page exception.

The scripted verdicts it asserts (`ALLOW BLOCK BLOCK BLOCK ESCALATE`) must match
what `warrant demo` prints. They diverged once, when the storefront existed in
two places and drifted by one SKU; `tests/test_catalog.py` now guards that seam.
