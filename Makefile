# Standard command interface: every routine task is a make target (see AGENTS.md).
# mr is a Claude Code plugin with no runtime dependencies: Python 3.9+ standard library only.
# A target that does not apply prints why and exits 0.

PY ?= python3
PYFLAGS := -B

.PHONY: help setup dev test lint fmt typecheck build charts clean check-install

help:
	@echo "Targets: setup dev test lint fmt typecheck build charts clean check-install"
	@echo "  setup      check the Python interpreter (nothing to install)"
	@echo "  dev        not applicable (plugin is loaded by Claude Code)"
	@echo "  test       unittest suite in tests/"
	@echo "  lint       regenerate check, chart check, plugin validation, sensitive-data scan"
	@echo "  fmt        not applicable (no formatter configured)"
	@echo "  typecheck  not applicable (no type checker configured)"
	@echo "  build      regenerate agents/ and skills/routing-policy/SKILL.md from config/ and policy/"
	@echo "  charts     rewrite docs/assets/chart-*.svg from docs/case-study/ and docs/cost/"
	@echo "  clean      remove Python bytecode caches"
	@echo "  check-install  check the installed plugin holds only files committed at HEAD"

setup:
	@$(PY) --version
	@echo "make setup: no dependencies to install; the plugin uses the standard library only"

dev:
	@echo "make dev: not applicable; the plugin has no dev server. Load it in Claude Code from this checkout."

test:
	PYTHONDONTWRITEBYTECODE=1 $(PY) -m unittest discover -s tests -v

lint:
	$(PY) $(PYFLAGS) scripts/generate.py --check
	$(PY) $(PYFLAGS) scripts/render_charts.py --check
	@# Validate what git would ship (tracked + untracked, not ignored): the workspace's
	@# git-ignored CLAUDE.md pointer and .agent/ run state are not part of the plugin.
	@if command -v claude >/dev/null 2>&1; then \
		tmp=$$(mktemp -d) && git ls-files -z --cached --others --exclude-standard \
		  | rsync -a --from0 --files-from=- . "$$tmp/" \
		  && claude plugin validate "$$tmp" --strict; rc=$$?; rm -rf "$$tmp"; exit $$rc; \
	else \
		echo "make lint: claude CLI not on PATH; plugin validation skipped"; \
	fi
	$(PY) $(PYFLAGS) scripts/scan_sensitive.py --history

fmt:
	@echo "make fmt: not applicable; no formatter is configured"

typecheck:
	@echo "make typecheck: not applicable; no type checker is configured"

build:
	$(PY) $(PYFLAGS) scripts/generate.py

charts:
	$(PY) $(PYFLAGS) scripts/render_charts.py

clean:
	find . -name __pycache__ -type d -not -path './.git/*' -prune -exec rm -rf {} +
	@echo "make clean: removed Python bytecode caches"

check-install:
	$(PY) $(PYFLAGS) scripts/check_install.py
