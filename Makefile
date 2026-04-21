PYTHON ?= python3
SRC_DIR := src/open_workshop_manager
SCRIPT_DIRS := scripts migration_scripts
ROOT_FILES := main.py
FORMAT_TARGETS := $(SRC_DIR) $(SCRIPT_DIRS) $(ROOT_FILES)
LINT_TARGETS := $(SRC_DIR) $(SCRIPT_DIRS) $(ROOT_FILES)
TYPE_CHECK_TARGETS := $(SRC_DIR) $(SCRIPT_DIRS) $(ROOT_FILES)
PYTHONPATH := src

.PHONY: format lint type-check

format:
	$(PYTHON) -m isort $(FORMAT_TARGETS)
	$(PYTHON) -m black $(FORMAT_TARGETS)

lint:
	$(PYTHON) -m flake8 $(LINT_TARGETS)
	$(PYTHON) -m isort --check-only --diff $(LINT_TARGETS)

type-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m mypy $(TYPE_CHECK_TARGETS)
