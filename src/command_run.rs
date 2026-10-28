use crate::{assets::IMAGES, command_build, detection};
use anyhow::{Context, Result, ensure};
use clap::Args;
use std::{
    collections::BTreeMap,
    env,
    ffi::OsString,
    fs,
    os::unix::{fs::PermissionsExt, process::CommandExt},
    path::PathBuf,
    process::{Command, Stdio},
};

#[derive(Args)]
pub(crate) struct Run {
    #[arg(value_name = "IMAGE_NAME", value_parser = clap::builder::PossibleValuesParser::new(IMAGES.iter().map(|(name, _)| *name)))]
    image_suffix: String,

    #[arg(value_name = "CONTAINER_NAME")]
    container_name_suffix: String,

    script: PathBuf,

    /// Bind a path read/write (repeatable)
    #[arg(short = 'p', long = "path", value_name = "PATH")]
    paths: Vec<PathBuf>,

    /// Bind a path read-only (repeatable)
    #[arg(short = 'r', long = "ro-path", value_name = "PATH")]
    ro_paths: Vec<PathBuf>,

    #[arg(allow_hyphen_values = true, value_name = "DOCKER_ARGUMENTS")]
    arguments_after_script: Vec<OsString>,

    #[arg(last = true, value_name = "SCRIPT_ARGUMENTS")]
    arguments_after_separator: Vec<OsString>,
}

impl Run {
    pub(crate) fn execute(self) -> Result<()> {
        let (docker_arguments, script_arguments) = match self
            .arguments_after_script
            .iter()
            .position(|arg| arg == "--")
        {
            Some(i) => (
                &self.arguments_after_script[..i],
                &self.arguments_after_script[i + 1..],
            ),
            None => (
                self.arguments_after_script.as_slice(),
                self.arguments_after_separator.as_slice(),
            ),
        };

        let script = self.script.canonicalize().context("resolve script")?;

        let metadata = fs::metadata(&script)?;

        ensure!(
            metadata.is_file() && metadata.permissions().mode() & 0o111 != 0,
            "script is not executable"
        );

        let script_dir = script.parent().unwrap();
        let runbox_bin = env::current_exe()?.canonicalize()?;

        let mut mounts = BTreeMap::from([(script_dir.to_path_buf(), false), (runbox_bin, true)]);

        for (paths, readonly) in [(&self.paths, false), (&self.ro_paths, true)] {
            for path in paths {
                let path = path.canonicalize().context("resolve bind mount path")?;

                if let Some(existing) = mounts.insert(path.clone(), readonly) {
                    ensure!(
                        existing == readonly,
                        "conflicting mount permissions: {}",
                        path.display()
                    );
                }
            }
        }

        ensure!(
            !docker_arguments
                .iter()
                .any(|arg| arg == "--name" || arg.as_encoded_bytes().starts_with(b"--name=")),
            "use the mandatory CONTAINER_NAME instead of Docker --name"
        );

        let user = detection::resolve_user()?;
        let image_tag = detection::image_tag(&self.image_suffix, user.uid);

        if !Command::new("docker")
            .args(["image", "inspect", &image_tag])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()?
            .success()
        {
            command_build::run(&self.image_suffix, &image_tag, &user)?;
        }

        let container_name = detection::container_name(&self.container_name_suffix)?;

        let mut script_env = OsString::from("RUNBOX_SCRIPT=");
        script_env.push(&script);

        let mut command = Command::new("docker");

        command
            .arg("run")
            .args(["--cap-add", "SYS_ADMIN"])
            .args(["--cap-add", "SYS_NICE"])
            .args(["--cap-add", "SYS_PTRACE"])
            .args(["--cap-add", "SYS_TTY_CONFIG"])
            .args(["--ipc", "host"])
            .args(["--name", &container_name])
            .args(["--net", "host"])
            .arg("--rm")
            .args(["--security-opt", "seccomp=unconfined"])
            .arg("-e")
            .arg(script_env)
            .arg("-w")
            .arg(script_dir);

        let mut mounts: Vec<_> = mounts.into_iter().collect();
        mounts.sort_by_key(|(p, _)| p.components().count());

        for (path, readonly) in mounts {
            command
                .arg("--mount")
                .arg(detection::mount_spec(&path, readonly));
        }

        detection::docker_socket(&mut command);
        detection::udev(&mut command);
        detection::devices(&mut command);
        detection::ntsync(&mut command)?;

        let has_wayland = detection::wayland(&mut command, &user.runtime_dir);

        detection::x11(&mut command, &user.name, has_wayland)?;
        detection::pulse(&mut command, &user.runtime_dir);
        detection::nvidia(&mut command)?;

        command
            .args(docker_arguments)
            .arg(image_tag)
            .arg(script)
            .args(script_arguments);

        Err(command.exec()).context("exec docker run")
    }
}
