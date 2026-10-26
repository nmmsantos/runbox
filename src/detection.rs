use anyhow::{Context, Result, ensure};
use nix::unistd::{Uid, User};
use std::{
    env,
    ffi::{OsStr, OsString},
    fs::{self, File},
    io::Read,
    os::unix::{ffi::OsStrExt, fs::FileTypeExt},
    path::{Path, PathBuf},
    process::Command,
};

pub(crate) fn image_tag(image_suffix: &str, uid: u32) -> String {
    format!("runbox-{image_suffix}-{uid}:local")
}

pub(crate) fn container_name(container_name_suffix: &str) -> Result<String> {
    const ALPHABET: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789";
    let mut random = [0u8; 6];

    File::open("/dev/urandom")?.read_exact(&mut random)?;

    let slug: String = random
        .iter()
        .map(|byte| ALPHABET[usize::from(*byte) % ALPHABET.len()] as char)
        .collect();

    Ok(format!("runbox-{container_name_suffix}-{slug}"))
}

pub(crate) fn in_container() -> bool {
    env::var_os("RUNBOX_SCRIPT").is_some_and(|value| !value.is_empty())
}

pub(crate) struct HostUser {
    pub(crate) uid: u32,
    pub(crate) gid: u32,
    pub(crate) name: String,
    pub(crate) runtime_dir: PathBuf,
}

pub(crate) fn resolve_user() -> Result<HostUser> {
    let mut uid = nix::unistd::getuid().as_raw();

    for name in ["RUNBOX_UID", "SUDO_UID"] {
        match env::var(name) {
            Ok(value) => {
                uid = value
                    .parse()
                    .with_context(|| format!("{name} must be a valid UID"))?;

                break;
            }
            Err(env::VarError::NotPresent) => continue,
            Err(error) => return Err(error).with_context(|| format!("read {name}")),
        }
    }

    let account = User::from_uid(Uid::from_raw(uid))?
        .with_context(|| format!("no account exists for UID={uid}"))?;

    let runtime_dir = env::var_os("XDG_RUNTIME_DIR")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(format!("/run/user/{uid}")));

    Ok(HostUser {
        uid,
        gid: account.gid.as_raw(),
        name: account.name,
        runtime_dir,
    })
}

pub(crate) fn mount_spec(path: &Path, readonly: bool) -> OsString {
    let mut encoded = OsString::from("type=bind");

    for prefix in [",\"src=", ",\"dst="] {
        encoded.push(prefix);

        for (index, part) in path
            .as_os_str()
            .as_bytes()
            .split(|&byte| byte == b'"')
            .enumerate()
        {
            if index > 0 {
                encoded.push("\"\"");
            }
            encoded.push(OsStr::from_bytes(part));
        }
        encoded.push("\"");
    }

    if readonly {
        encoded.push(",readonly");
    }

    encoded
}

fn is_socket(path: &Path) -> bool {
    fs::metadata(path).is_ok_and(|m| m.file_type().is_socket())
}

fn is_device(path: &Path) -> bool {
    fs::metadata(path).is_ok_and(|m| m.file_type().is_char_device())
}

pub(crate) fn docker_socket(command: &mut Command) {
    let path = Path::new("/var/run/docker.sock");

    if is_socket(path) {
        command.arg("--mount").arg(mount_spec(path, false));
    }
}

pub(crate) fn udev(command: &mut Command) {
    let path = Path::new("/run/udev");

    if path.is_dir() {
        command.arg("--mount").arg(mount_spec(path, true));
    }
}

pub(crate) fn devices(command: &mut Command) {
    for path in ["/dev/dri", "/dev/snd", "/dev/input"] {
        if Path::new(path).is_dir() {
            command.args(["--device", path]);
        }
    }

    for n in 1..5 {
        let path = format!("/dev/tty{n}");
        if is_device(Path::new(&path)) {
            command.args(["--device", &path]);
        }
    }
}

pub(crate) fn ntsync(command: &mut Command) -> Result<()> {
    if !in_container() {
        Command::new("modprobe").arg("ntsync").status()?;
    }

    if is_device(Path::new("/dev/ntsync")) {
        command.args(["--device", "/dev/ntsync"]);
    }

    Ok(())
}

pub(crate) fn wayland(command: &mut Command, runtime_dir: &Path) -> bool {
    let mut candidates = vec![runtime_dir.join(env::var_os("WAYLAND_DISPLAY").unwrap_or_default())];

    if let Ok(entries) = fs::read_dir(runtime_dir) {
        let mut paths: Vec<_> = entries
            .filter_map(Result::ok)
            .filter(|entry| entry.file_name().as_bytes().starts_with(b"wayland-"))
            .map(|entry| entry.path())
            .collect();
        paths.sort();
        candidates.extend(paths);
    }

    let wayland = candidates.into_iter().find(|p| is_socket(p));

    if let Some(path) = &wayland {
        let display = path.strip_prefix(runtime_dir).unwrap_or(path);
        let mut display_env = OsString::from("WAYLAND_DISPLAY=");

        display_env.push(display);

        command.arg("-e").arg(display_env);
        command.arg("--mount").arg(mount_spec(path, true));
    }

    wayland.is_some()
}

pub(crate) fn x11(command: &mut Command, user: &str, has_wayland: bool) -> Result<()> {
    let display = env::var("DISPLAY").unwrap_or_default();
    let x11 = PathBuf::from(format!(
        "/tmp/.X11-unix/X{}",
        display
            .split_once(':')
            .map_or(display.as_str(), |(_, s)| s)
            .split('.')
            .next()
            .unwrap_or("")
    ));

    if is_socket(&x11) {
        command.args(["-e", &format!("DISPLAY={display}")]);
        command.arg("--mount").arg(mount_spec(&x11, true));

        if !has_wayland {
            ensure!(
                Command::new("xhost")
                    .arg(format!("+SI:localuser:{user}"))
                    .status()?
                    .success(),
                "xhost failed"
            );
        }
    }

    Ok(())
}

pub(crate) fn pulse(command: &mut Command, runtime_dir: &Path) {
    if is_socket(&runtime_dir.join("pulse/native")) {
        let path = runtime_dir.join("pulse");
        command.arg("--mount").arg(mount_spec(&path, true));
    }
}

pub(crate) fn nvidia(command: &mut Command) -> Result<()> {
    if is_device(Path::new("/dev/nvidiactl")) {
        let nvidia = Command::new("docker")
            .args(["info", "-f", "{{.Runtimes.nvidia.Path}}"])
            .output()?;

        let value = String::from_utf8_lossy(&nvidia.stdout);

        if nvidia.status.success() && !["", "<no value>"].contains(&value.trim()) {
            command
                .args(["--runtime", "nvidia"])
                .args(["-e", "NVIDIA_VISIBLE_DEVICES=all"])
                .args(["-e", "NVIDIA_DRIVER_CAPABILITIES=all"]);
        }
    }

    Ok(())
}
