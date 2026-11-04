.PHONY: all test verify test-py test-node clean

all: test

# 1. Reproducible Audit & Cryptographic Verifier
verify:
	@PYTHONPATH=. python3 scripts/verify_audit.py

# 2. Python Test Suite (456 tests)
test-py:
	@PYTHONPATH=. pytest tests/ -q

# 3. Node Test Suite (289 tests)
test-node:
	@npm test

# 4. Full Verification Run (All tests + Audit verification)
test: verify test-py test-node
	@echo "All PropStein test suites & cryptographic verifiers passed."

clean:
	@rm -rf .pytest_cache __pycache__ src/__pycache__ scripts/__pycache__
