.PHONY: ci lint test
ci: lint test
lint:
	ruff check src tests
test:
	pytest -q
