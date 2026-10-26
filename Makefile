PREFIX ?= /usr/local
TARGET ?= x86_64-unknown-linux-musl

.DEFAULT_GOAL := dev

.PHONY: dev release lint test install install-dev uninstall

dev: lint
	cargo build --locked --target "$(TARGET)"

release: lint
	cargo build --release --locked --target "$(TARGET)"

lint:
	cargo fmt --check
	cargo clippy --locked --target "$(TARGET)" -- -D warnings

test:
	python3 -B test/run.py

install:
	install -Dm 0755 "target/$(TARGET)/release/runbox" "$(DESTDIR)$(PREFIX)/bin/runbox"

install-dev:
	install -Dm 0755 "target/$(TARGET)/debug/runbox" "$(DESTDIR)$(PREFIX)/bin/runbox"

uninstall:
	rm -f "$(DESTDIR)$(PREFIX)/bin/runbox"
