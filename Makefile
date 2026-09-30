.PHONY: install uninstall doctor smoke clean driver-install

# Root paths
SRC_DIR         := $(shell pwd)
DRIVER_DIR      ?= ../openshell-driver-apple-container
BIN_DIR         ?= $(HOME)/.local/bin
STATE_DIR       ?= $(HOME)/.local/state/trybox

install: cli driver-install dirs
	@echo ""
	@echo "trybox installed. Next:"
	@echo "  $(MAKE) doctor"
	@echo ""
	@echo "If doctor passes:"
	@echo "  trybox my first idea"

cli:
	@if ! command -v uv >/dev/null; then \
	  echo "uv not found; install with: brew install uv"; exit 1; \
	fi
	uv tool install --force --python 3.12 "$(SRC_DIR)"

driver-install:
	@if [ ! -d "$(DRIVER_DIR)" ]; then \
	  echo "driver repo not at $(DRIVER_DIR); set DRIVER_DIR=/path/to/openshell-driver-apple-container"; \
	  exit 1; \
	fi
	PATH="/opt/homebrew/opt/rustup/bin:$$PATH" \
	  cargo install --path "$(DRIVER_DIR)" --root "$(HOME)/.local" --locked
	@echo ""
	@echo "driver installed to $(BIN_DIR)/openshell-driver-apple-container"
	@echo "start it with: openshell-driver-apple-container --bind-socket $(STATE_DIR)/driver.sock --supervisor-bin-dir $(DRIVER_DIR)/guest-bin"

dirs:
	mkdir -p "$(STATE_DIR)"
	mkdir -p "$(HOME)/src/tries"

doctor:
	"$(BIN_DIR)/trybox" doctor || uv tool run --from "$(SRC_DIR)" trybox doctor

smoke: install
	"$(BIN_DIR)/trybox" doctor

uninstall:
	uv tool uninstall trybox || true
	@echo "kept $(BIN_DIR)/openshell-driver-apple-container; remove manually if desired"

clean:
	rm -rf "$(STATE_DIR)"
	@echo "kept try dirs in $(HOME)/src/tries"
