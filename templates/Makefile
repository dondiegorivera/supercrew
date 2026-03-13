# {{PROJECT_NAME}} — Makefile
# Self-documenting: run `make help` to see all targets.

.DEFAULT_GOAL := help
.PHONY: help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Build ---
# TODO: Add your build targets. Example:
# build: ## Build the project
# 	./scripts/build.sh

# --- Local Dev ---
# TODO: Add your local development targets. Example:
# dev: ## Start local dev server
# 	./scripts/dev.sh

# --- Tests ---
# TODO: Add your test targets. Example:
# test: ## Run tests
# 	pytest tests/

# --- Pipeline / Automation ---
# TODO: Add pipeline targets if your project has automated data processing. Example:
# scan: ## Run data collection pipeline
# 	python agent/scan.py
