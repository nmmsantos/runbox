# Project conventions

## README

- Keep the README focused on using runbox: installation, running scripts, and practical examples.
- Do not catalog every helper, image, or source file. Adding a helper or image should not require a README update.
- Use the `arch` image and the full Java helper example to demonstrate usage; keep those examples accurate.
- Keep general helper mentions, `runbox helper --help`, and the note that helpers are bundled in the executable. Put individual helper argument details in their usage messages.

Keep these agent instructions focused on general conventions too; do not list helpers or their individual arguments and environment requirements.

## Shell scripts

- Helpers run inside disposable containers. Keep them simple; do not add temporary-file cleanup traps or host-oriented housekeeping. Files in mounted destinations persist, so handle those paths deliberately.
- Preserve direct download pipelines such as `curl | tar`; do not replace them with intermediate archive files without a concrete need.
- Use POSIX `/bin/sh` and consistent argument conventions. When a helper takes a destination argument, put it first.
- Preserve required caller-provided environment variables; do not guess, default, assign, or replace them with arguments. Do not introduce undocumented environment assumptions.
- Treat environment variables provided by the container image as established runtime inputs; check the image definition before replacing them.
- Helpers that return shell activation commands start with `exec 3>&1 >&2`: setup output goes to stderr, and only the activation payload is written to file descriptor 3.
- Helpers that perform actions without returning an activation payload use normal stdout and stderr; they do not need that redirection.

## Builds

- Use the Makefile targets, including `make release`, in workflows and instructions.
