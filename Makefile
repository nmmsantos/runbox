PREFIX ?= /usr/local
TARGET ?= x86_64-unknown-linux-musl

.PHONY: dev release install install-dev uninstall

dev:
	cargo build --locked --target "$(TARGET)"

release:
	cargo build --release --locked --target "$(TARGET)"

install:
	install -Dm 0755 "target/$(TARGET)/release/runbox" "$(DESTDIR)$(PREFIX)/bin/runbox"

install-dev:
	install -Dm 0755 "target/$(TARGET)/debug/runbox" "$(DESTDIR)$(PREFIX)/bin/runbox"

uninstall:
	rm -f "$(DESTDIR)$(PREFIX)/bin/runbox"
