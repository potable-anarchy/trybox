.PHONY: install uninstall doctor check smoke
install:
	bash install.sh --source "$(CURDIR)"
uninstall:
	bash uninstall.sh --yes
doctor:
	"$(HOME)/.local/bin/trybox" doctor
check:
	bash install.sh --check
smoke:
	python3 scripts/smoke-test.py
