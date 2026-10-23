# runbox

Run executable scripts in disposable Docker containers, with access to the host's desktop, audio, and devices. Select an image for the environment you need, and use optional helpers from inside your scripts.

The script directory keeps the same absolute path inside the container. Files written there remain on the host after the container exits.

## Requirements

- Linux with a local Docker daemon and support for BuildKit builds.
- Rust with the `x86_64-unknown-linux-musl` target, Cargo, and Make to build and install the executable.
- Permission to use Docker and access the required host devices. The examples below use `sudo` for container operations.
- `modprobe` on the host; `xhost` when using an X11 session without Wayland.

Image builds also require the host groups `audio`, `input`, `render`, and `video`. Internet access is needed to build images and for helpers that download software.

## Install

With a rustup-managed toolchain, install the target once:

```sh
rustup target add x86_64-unknown-linux-musl
```

From the project directory:

```sh
make release
sudo make install
```

`make` (or `make dev`) builds a statically linked debug executable at `target/x86_64-unknown-linux-musl/debug/runbox`. `make release` builds a stripped, statically linked executable at `target/x86_64-unknown-linux-musl/release/runbox` that does not require the system's libc. `make install` copies the release executable to `/usr/local/bin/runbox`; build it first so compilation runs as your normal user.

To install for your user instead:

```sh
make install PREFIX="$HOME/.local"
```

Ensure the chosen prefix's `bin` directory is on your `PATH`. `DESTDIR` is also supported for staged installations.

The installed executable includes the image definitions and helpers. Rebuild and reinstall it after changing those resources.

## Discover available choices

```sh
runbox --help
runbox build --help
runbox run --help
runbox helper --help
```

The command help lists the available images and helpers. The examples use the `arch` image.

## Run a script

Create an executable script, such as `hello.sh`:

```sh
#!/bin/sh
set -eu

printf 'Working directory: %s\n' "$PWD"
printf 'Hello, %s!\n' "${1:-world}"
```

Then run it:

```sh
chmod +x hello.sh
sudo runbox run arch hello ./hello.sh -- "Ada"
```

The script's interpreter must be available in the selected image. Scripts can be written in any language supported by that image.

The image is built automatically if it is missing. The container runs as a user matching your host UID and GID, including when invoked through `sudo`. Its working directory is the script's directory.

`hello` is a label for this invocation. The actual container name has the form `runbox-hello-<random suffix>`, so you can run multiple instances with the same label. The container is removed when it exits, and the command preserves its exit status.

### Arguments and Docker options

```text
runbox run IMAGE_NAME CONTAINER_NAME SCRIPT [--path PATH] [--ro-path PATH] [DOCKER_ARGUMENTS...] -- [SCRIPT_ARGUMENTS...]
```

Put mount options immediately after the script, followed by any Docker options. Everything after `--` is passed to the script unchanged. Without `--`, trailing arguments are treated as Docker options.

For example, to provide an environment variable and an interactive terminal:

```sh
sudo runbox run arch hello ./hello.sh \
    -it --env GREETING=hello -- "Ada"
```

Use the required `CONTAINER_NAME` argument to name an invocation; Docker's `--name` option is rejected.

### Mount additional files

```sh
sudo runbox run arch job ./job.sh \
    --path /absolute/path/to/output \
    --ro-path /absolute/path/to/input --
```

Both options accept existing files or directories and can be repeated. Relative paths are resolved from the directory where you invoke the command. Symlinks are resolved to their targets.

| Path | Access inside the container |
| --- | --- |
| Script directory | Read/write, mounted automatically |
| Installed `runbox` executable | Read-only, mounted automatically |
| `--path PATH` | Read/write |
| `--ro-path PATH` | Read-only |

All these mounts retain their absolute host paths. Giving the same resolved path conflicting access modes is an error.

Changes elsewhere in the container, including its home directory, are discarded when it exits. Store anything you want to keep in a writable host mount.

## Build or refresh an image

```sh
sudo runbox build arch
```

An explicit build pulls the base image and rebuilds without Docker's build cache. Normal runs reuse an existing image. Images are tagged per host UID, so different users have separate image tags.

## A script that launches itself in the container

Save this as `java-demo.sh`:

```sh
#!/bin/sh

set -eu

ME="$(readlink -f "$0")"

if [ "${RUNBOX_SCRIPT:-}" != "$ME" ]; then
    exec runbox run arch java-demo "$ME" -- "$@"
fi

JAVA_VERSION=21.0.5+11
DATA_DIR="$(dirname "$ME")/.data"

mkdir -p "$DATA_DIR"

ACTIVATION="$(runbox helper java "$DATA_DIR" "$JAVA_VERSION")"
eval "$ACTIVATION"

exec java -version
```

Make it executable, then run it from the host:

```sh
chmod +x java-demo.sh
sudo ./java-demo.sh
```

The first invocation launches the same script inside an `arch` container. Runbox sets `RUNBOX_SCRIPT` to the script's absolute path, so the second invocation continues with the Java setup instead of launching another container. `-- "$@"` forwards the original script arguments.

The `java` helper takes a parent destination directory followed by an exact JDK version. It downloads the JDK into `java-temurin-<version>` under that directory when that installation is absent and prints shell commands to set `JAVA_HOME` and update `PATH`. The assignment captures those commands; `eval` applies them to the current shell. With `set -e`, a failed helper stops the script before evaluation.

The example pins a Java version and stores it in `.data` beside the script. That directory is in the automatic writable mount, so the installation survives container removal and is reused on subsequent runs. Change `JAVA_VERSION` to select another release; the helper creates a separate folder for each version.

The final command prints the installed Java version. Helpers run inside the container, and their diagnostics go to standard error. Standard output is forwarded only when the helper succeeds.

## Host integration

Available Wayland, X11, and PulseAudio sockets are connected automatically, along with graphics, sound, input, and virtual terminal devices. NVIDIA integration is enabled when the device and Docker runtime are available. The tool also attempts to load the host's `ntsync` module and passes its device through when present.

The runtime directory comes from `XDG_RUNTIME_DIR`, falling back to `/run/user/<uid>`.

Containers share the host network and IPC namespace and receive additional capabilities with an unconfined seccomp profile. The local Docker socket is mounted when available, allowing scripts to launch further containers through the host daemon.

Nested invocations use the same path conventions. Pass each required path explicitly to the nested invocation; the parent's extra mounts are not inherited automatically.

Host environment variables are not generally copied into the container. Use Docker's `--env` option to pass values your script needs.
