SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

COMPOSE := docker compose
ENV_FILE ?= .env
PROMPT ?=
CREW ?=
EFFORT ?=
SAVE ?=
INPUT ?=
PROMOTE ?=
OUTPUT_FORMAT ?=
NEW ?=0

.PHONY: help build run run-new promote test shell load-env up down logs

help:
	@printf "Targets:\n"
	@printf "  make build       Build the project image\n"
	@printf "  make run         Run start.sh with optional PROMPT/CREW/EFFORT/SAVE/INPUT/OUTPUT_FORMAT\n"
	@printf "  make run-new     Force planner generation from scratch (NEW=1)\n"
	@printf "  make promote     Promote a generated crew with PROMOTE=name\n"
	@printf "  make test        Compile-check Python files and validate start.sh syntax\n"
	@printf "  make shell       Open a shell with %s loaded\n" "$(ENV_FILE)"
	@printf "  make load-env    Alias for make shell\n"
	@printf "  make up          Start the compose service in the background\n"
	@printf "  make down        Stop the compose service\n"
	@printf "  make logs        Tail compose logs\n"
	@printf "\n"
	@printf "Optional variables:\n"
	@printf "  PROMPT=\"...\"      Task text passed to start.sh\n"
	@printf "  CREW=name         Skip planner and use a specific crew\n"
	@printf "  EFFORT=level      quick | standard | thorough | exhaustive\n"
	@printf "  SAVE=name         Save a generated crew under config/generated_crews/\n"
	@printf "  INPUT=path        Read the task text from a file\n"
	@printf "  OUTPUT_FORMAT=f   auto | text | html\n"
	@printf "  PROMOTE=name      Promote a generated crew into config/crews/\n"
	@printf "  ENV_FILE=.env      Alternate env file to source for shell target\n"

build:
	@$(COMPOSE) build

run:
	@args=(); \
	if [[ -n "$(CREW)" ]]; then args+=(--crew "$(CREW)"); fi; \
	if [[ -n "$(EFFORT)" ]]; then args+=(--effort "$(EFFORT)"); fi; \
	if [[ -n "$(SAVE)" ]]; then args+=(--save "$(SAVE)"); fi; \
	if [[ -n "$(OUTPUT_FORMAT)" ]]; then args+=(--format "$(OUTPUT_FORMAT)"); fi; \
	if [[ -n "$(INPUT)" ]]; then args+=(--input "$(INPUT)"); fi; \
	if [[ "$(NEW)" == "1" ]]; then args+=(--new); fi; \
	if [[ -n "$(PROMPT)" ]]; then args+=("$(PROMPT)"); fi; \
	./start.sh "$${args[@]}"

run-new:
	@$(MAKE) run NEW=1 PROMPT="$(PROMPT)" EFFORT="$(EFFORT)" SAVE="$(SAVE)" INPUT="$(INPUT)" OUTPUT_FORMAT="$(OUTPUT_FORMAT)"

promote:
	@if [[ -z "$(PROMOTE)" ]]; then \
		echo "PROMOTE=name is required" >&2; \
		exit 1; \
	fi
	@./start.sh --promote "$(PROMOTE)"

test:
	@python3 -m compileall supercrew.py src
	@bash -n start.sh

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
