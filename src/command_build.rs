use crate::{assets, detection};
use anyhow::{Context, Result, ensure};
use clap::Args;
use nix::unistd::Group;
use std::{
    ffi::OsString,
    io::Write,
    process::{Command, Stdio},
};

#[derive(Args)]
pub(crate) struct Build {
    #[arg(value_name = "IMAGE_NAME", value_parser = clap::builder::PossibleValuesParser::new(assets::image_names()))]
    image_suffix: String,
}

impl Build {
    pub(crate) fn execute(self) -> Result<()> {
        let user = detection::resolve_user()?;
        let image_tag = detection::image_tag(&self.image_suffix, user.uid);

        run(&self.image_suffix, &image_tag, &user)
    }
}

pub(crate) fn run(image_suffix: &str, image_tag: &str, user: &detection::HostUser) -> Result<()> {
    let dockerfile = assets::image(image_suffix)?;

    let mut build = Command::new("docker");

    let mut runtime_dir_arg = OsString::from("xdg_runtime_dir=");
    runtime_dir_arg.push(&user.runtime_dir);

    build
        .arg("build")
        .args(["--build-arg", &format!("my_gid={}", user.gid)])
        .args(["--build-arg", &format!("my_uid={}", user.uid)])
        .args(["--build-arg", &format!("my_user={}", user.name)])
        .arg("--build-arg")
        .arg(runtime_dir_arg)
        .args(["--network", "host"])
        .arg("--no-cache")
        .args(["--progress", "plain"])
        .arg("--pull")
        .args(["-t", image_tag]);

    for name in ["audio", "input", "render", "video"] {
        let group = Group::from_name(name)?
            .with_context(|| format!("required group does not exist: {name}"))?;

        build.args(["--build-arg", &format!("{name}_gid={}", group.gid.as_raw())]);
    }

    build.arg("-");

    let mut child = build.stdin(Stdio::piped()).spawn()?;

    child
        .stdin
        .take()
        .unwrap()
        .write_all(dockerfile.as_bytes())?;

    ensure!(child.wait()?.success(), "image build failed");

    Ok(())
}
