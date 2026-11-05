.PHONY: ci lint test lock
ci: lint test
lint:
	ruff check src tests
test:
	pytest -q
# Bağımlılık kilidi: hash'li, çok platformlu (tekrarlanabilir kurulum). pyproject değişince yeniden üret.
lock:
	uv pip compile pyproject.toml --extra symbols --universal --python-version 3.11 --generate-hashes -o requirements.lock
	uv pip compile pyproject.toml --extra symbols --extra dev --universal --python-version 3.11 --generate-hashes -o requirements-dev.lock
