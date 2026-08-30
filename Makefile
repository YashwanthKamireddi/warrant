# Warrant — no agent spends without one.
#
#   make demo      the five-cart scenario, in the terminal
#   make bench     405 labelled sessions, four policies, honest losses
#   make console   build the console and serve everything on one port
#   make verify    the full gate: tests, types, tokens, contrast, layout, browser
#
# `make demo` and `make bench` need no API key and no network.

VERIFY_PORT ?= 8899
CONSOLE_PORT ?= 8787

.DEFAULT_GOAL := help
.PHONY: help install demo bench console serve test lint typecheck build \
        audit-secrets docs-check audit-tokens audit-contrast audit-overlap browser browser-razorpay browsers verify clean open bench-live

help:
	@printf '\n  \033[1mWarrant\033[0m — authorization for agent-initiated payments\n\n'
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@printf '\n'

install: console/node_modules ## install python deps, console deps and the browser driver
	uv sync
	uv run playwright install chromium

demo: ## run the five-cart scenario in the terminal
	uv run warrant demo

bench: ## run the benchmark and refresh the committed results artifact
	uv run python bench/run.py --write-results bench/RESULTS.json

bench-live: ## live-model run on only the categories a model can change (~30 calls)
	uv run python bench/run.py --live --per-category 5 \
		--categories injection_subtle,semantic_drift,legitimate

build: console/node_modules ## build the console
	cd console && npm run build

console: build ## build the console and serve it at http://127.0.0.1:8787
	@printf '\n  Console: \033[36mhttp://127.0.0.1:$(CONSOLE_PORT)\033[0m\n\n'
	uv run warrant serve --port $(CONSOLE_PORT)

open: build ## build, serve, and open the console in your browser
	@(uv run warrant serve --port $(CONSOLE_PORT) &) ; \
	for i in $$(seq 1 40); do \
		curl -sf http://127.0.0.1:$(CONSOLE_PORT)/api/meta >/dev/null && break; \
		sleep 0.25; \
	done; \
	(xdg-open http://127.0.0.1:$(CONSOLE_PORT) 2>/dev/null \
		|| open http://127.0.0.1:$(CONSOLE_PORT) 2>/dev/null \
		|| printf '  Open http://127.0.0.1:$(CONSOLE_PORT)\n'); \
	printf '\n  Serving on \033[36mhttp://127.0.0.1:$(CONSOLE_PORT)\033[0m — Ctrl-C to stop.\n\n'; \
	wait

serve: ## serve the API without rebuilding the console
	uv run warrant serve --port $(CONSOLE_PORT)

# -- the gate --------------------------------------------------------------- #

test: ## run the python test suite
	uv run pytest -q

lint: ## lint the python source
	uv run ruff check engine bench tests

# A fresh clone has no node_modules, so every console target has to be able to
# create it. `make verify` on a clean checkout failed at typecheck with exit 127
# until this existed.
console/node_modules: console/package-lock.json
	cd console && npm ci --silent
	@touch console/node_modules

typecheck: console/node_modules ## typecheck the console
	cd console && npm run typecheck

audit-secrets: ## fail if any credential material is tracked or in history
	uv run python .verify/audit_secrets.py

docs-check: ## fail if any number in the README drifts from what the code measures
	uv run python .verify/audit_docs.py

audit-tokens: ## fail on any colour outside the token system
	uv run python .verify/audit_tokens.py

audit-contrast: ## fail on any rendered pair below WCAG AA
	uv run python .verify/audit_contrast.py

audit-overlap: build ## fail if anything spills its box or paints over a sibling
	@$(MAKE) --no-print-directory _with-server SCRIPT=.verify/audit_overlap.py

browser-razorpay: build ## drive the console against real Razorpay test mode (needs keys)
	@$(MAKE) --no-print-directory _with-server SCRIPT=.verify/walk_razorpay.py

browser: build ## layout, overlap and flow checks in a real browser, with screenshots
	@uv run warrant serve --port $(VERIFY_PORT) >/tmp/warrant-verify.log 2>&1 & \
	echo $$! > /tmp/warrant-verify.pid; \
	trap 'kill $$(cat /tmp/warrant-verify.pid) 2>/dev/null' EXIT; \
	for i in $$(seq 1 40); do \
		curl -sf http://127.0.0.1:$(VERIFY_PORT)/api/meta >/dev/null && break; \
		sleep 0.25; \
	done; \
	uv run python .verify/layout.py http://127.0.0.1:$(VERIFY_PORT) && \
	uv run python .verify/audit_overlap.py http://127.0.0.1:$(VERIFY_PORT) && \
	uv run python .verify/walk.py http://127.0.0.1:$(VERIFY_PORT)

# Boots the console on the verify port, runs one script against it, tears down.
_with-server:
	@uv run warrant serve --port $(VERIFY_PORT) >/tmp/warrant-verify.log 2>&1 & \
	echo $$! > /tmp/warrant-verify.pid; \
	trap 'kill $$(cat /tmp/warrant-verify.pid) 2>/dev/null' EXIT; \
	for i in $$(seq 1 40); do \
		curl -sf http://127.0.0.1:$(VERIFY_PORT)/api/meta >/dev/null && break; \
		sleep 0.25; \
	done; \
	uv run python $(SCRIPT) http://127.0.0.1:$(VERIFY_PORT)

# Chromium is a prerequisite of the browser gate, not a thing to remember.
browsers:
	@uv run python -c "import pathlib,sys; \
		sys.exit(0 if any(pathlib.Path.home().joinpath('.cache/ms-playwright').glob('chromium*')) else 1)" \
		|| uv run playwright install chromium

verify: audit-secrets lint test typecheck docs-check audit-tokens audit-contrast browsers browser ## everything, in order
	@printf '\n  \033[32mAll gates passed.\033[0m Screenshots in .verify/shots/\n\n'

clean:
	rm -rf console/dist .verify/shots .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
