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
        audit-tokens audit-contrast browser verify clean

help:
	@printf '\n  \033[1mWarrant\033[0m — authorization for agent-initiated payments\n\n'
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@printf '\n'

install: ## install python and console dependencies
	uv sync
	cd console && npm install

demo: ## run the five-cart scenario in the terminal
	uv run warrant demo

bench: ## run the benchmark over 405 labelled sessions
	uv run python bench/run.py

build: ## build the console
	cd console && npm run build

console: build ## build the console and serve it with the API
	uv run warrant serve --port $(CONSOLE_PORT)

serve: ## serve the API without rebuilding the console
	uv run warrant serve --port $(CONSOLE_PORT)

# -- the gate --------------------------------------------------------------- #

test: ## run the python test suite
	uv run pytest -q

lint: ## lint the python source
	uv run ruff check engine bench tests

typecheck: ## typecheck the console
	cd console && npm run typecheck

audit-tokens: ## fail on any colour outside the token system
	python3 .verify/audit_tokens.py

audit-contrast: ## fail on any rendered pair below WCAG AA
	python3 .verify/audit_contrast.py

browser: build ## drive the console in a real browser and screenshot every state
	@uv run warrant serve --port $(VERIFY_PORT) >/tmp/warrant-verify.log 2>&1 & \
	echo $$! > /tmp/warrant-verify.pid; \
	trap 'kill $$(cat /tmp/warrant-verify.pid) 2>/dev/null' EXIT; \
	for i in $$(seq 1 40); do \
		curl -sf http://127.0.0.1:$(VERIFY_PORT)/api/meta >/dev/null && break; \
		sleep 0.25; \
	done; \
	python3 .verify/layout.py http://127.0.0.1:$(VERIFY_PORT) && \
	python3 .verify/walk.py http://127.0.0.1:$(VERIFY_PORT)

verify: lint test typecheck audit-tokens audit-contrast browser ## everything, in order
	@printf '\n  \033[32mAll gates passed.\033[0m Screenshots in .verify/shots/\n\n'

clean:
	rm -rf console/dist .verify/shots .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
