.PHONY: all test verify verify-audit verify-ledger test-py test-node clean

PYTHON ?= $(shell if [ -f .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
PYTEST ?= $(shell if [ -f .venv/bin/pytest ]; then echo .venv/bin/pytest; else echo pytest; fi)

all: test

# Reproducible audit of the published frozen artifacts.
verify-audit:
	@PYTHONPATH=. $(PYTHON) scripts/verify_audit.py

# Ledger migration, registry hash, append-only invariants, and cohort checks.
verify-ledger:
	@PYTHONPATH=. $(PYTHON) scripts/verify_ledger.py

# Python suite. Ledger tests run in verify-ledger so this target does not repeat them.
test-py:
	@PYTHONPATH=. $(PYTEST) test/ tests/ -q --tb=short --ignore=tests/ledger

test-node:
	@npm test
	@npm --prefix terminal run typecheck

# Schema, registry, append-only chain, structural rules, cohort separation,
# language lint, the published audit, and the existing Python and Node suites.
verify: verify-audit verify-ledger test-py test-node
	@echo "All PropStein verification gates passed."

test: verify
	@echo "All PropStein test suites and cryptographic verifiers passed."

clean:
	@rm -rf .pytest_cache __pycache__ src/__pycache__ scripts/__pycache__
