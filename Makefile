SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

COMPOSE := docker compose
ENV_FILE ?= .env
PROMPT ?=

.PHONY: help build run shell load-env up down logs

help:
	@printf "Targets:\n"
	@printf "  make build       Build the project image\n"
	@printf "  make run         Run the project through docker compose\n"
	@printf "  make shell       Open a shell with %s loaded\n" "$(ENV_FILE)"
	@printf "  make load-env    Alias for make shell\n"
	@printf "  make up          Start the compose service in the background\n"
	@printf "  make down        Stop the compose service\n"
	@printf "  make logs        Tail compose logs\n"
	@printf "\n"
	@printf "Optional variables:\n"
	@printf "  PROMPT=\"...\"      Passed through to start.sh as the task prompt\n"
	@printf "  ENV_FILE=.env      Alternate env file to source for shell target\n"

build:
	@$(COMPOSE) build

run:
	@./start.sh "$(PROMPT)"

shell:
	@if [[ ! -f "$(ENV_FILE)" ]]; then \
		echo "Missing env file: $(ENV_FILE)" >&2; \
		exit 1; \
	fi
	@set -a; \
	source "$(ENV_FILE)"; \
	set +a; \
	echo "Loaded $(ENV_FILE) into a new shell. Exit to return."; \
	exec "$${SHELL:-bash}" -i

load-env: shell

up:
	@$(COMPOSE) up -d

down:
	@$(COMPOSE) down

logs:
	@$(COMPOSE) logs -f
