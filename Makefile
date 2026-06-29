.PHONY: help lint fmt test
.DEFAULT_GOAL := help

help:
	@fgrep -h "##" $(MAKEFILE_LIST) | fgrep -v fgrep | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

lint: ## Run code linters
	uv run ty check
	uv run ruff format --check
	uv run ruff check

fmt: ## Run code formatters
	uv run ruff format
	uv run ruff check --fix

test:  ## Run unit tests
	uv run pytest -vv tests --cov=anydi
	uv run pytest -vv tests/ext/test_pytest_plugin.py --cov=anydi --cov-append -p anydi
