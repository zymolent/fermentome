# Test recipes

test:
    python -m pytest

lint:
    ruff check .

fmt:
    ruff format .

typecheck:
    mypy

check: lint fmt-check typecheck test

fmt-check:
    ruff format --check .

clean:
    rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
