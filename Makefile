.PHONY: install uninstall doctor smoke clean driver-install

# Root paths
SRC_DIR         := $(shell pwd)
DRIVER_DIR      ?= ../openshell-driver-apple-container
BIN_DIR         ?= $(HOME)/.local/bin
STATE_DIR       ?= $(HOME)/.local/state/trybox
RUSTUP          := /opt/homebrew/opt/rustup/bin

install: cli driver-install dirs
	@echo ""
	@echo "trybox installed. Next:"
	@echo "  $(MAKE) doctor"
	@echo ""
	@echo "If doctor passes:"
	@echo "  trybox my first idea"

cli:
	PATH="$(RUSTUP):$$PATH" cargo install --path "$(SRC_DIR)" --root "$(HOME)/.local" --locked

driver-install:
	@if [ ! -d "$(DRIVER_DIR)" ]; then \
	  echo "driver repo not at $(DRIVER_DIR); set DRIVER_DIR=/path/to/openshell-driver-apple-container"; \
	  exit 1; \
	fi
	PATH="$(RUSTUP):$$PATH" \
	  cargo install --path "$(DRIVER_DIR)" --root "$(HOME)/.local" --locked
	@echo ""
	@echo "driver installed to $(BIN_DIR)/openshell-driver-apple-container"

dirs:
	mkdir -p "$(STATE_DIR)"
	mkdir -p "$(HOME)/code/tries"

doctor:
	"$(BIN_DIR)/trybox" doctor

smoke: install
	"$(BIN_DIR)/trybox" doctor

uninstall:
	rm -f "$(BIN_DIR)/trybox"
	@echo "kept $(BIN_DIR)/openshell-driver-apple-container; remove manually if desired"

clean:
	rm -rf "$(STATE_DIR)"
	@echo "kept try dirs in $(HOME)/code/tries"
