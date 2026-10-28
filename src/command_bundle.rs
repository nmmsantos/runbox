use crate::assets::BINARIES;
use anyhow::{Context, Result, ensure};
use clap::Args;
use glob::Pattern;
use std::{
    collections::BTreeSet, env, fs, io::Read, os::unix::fs::PermissionsExt, path::PathBuf,
    process::Command,
};

#[derive(Args)]
#[command(group(clap::ArgGroup::new("inputs").args(["executables", "libraries"]).required(true).multiple(true)))]
pub(crate) struct Bundle {
    /// New or empty destination directory
    destination: PathBuf,

    /// Additional library search directory (repeatable)
    #[arg(short = 'L', long, value_name = "DIRECTORY")]
    library_path: Vec<PathBuf>,

    /// File patterns for executables or libraries to place in usr/bin
    #[arg(short = 'e', long = "executable", num_args = 1.., value_name = "PATTERN")]
    executables: Vec<Pattern>,

    /// File patterns for libraries to place in usr/lib
    #[arg(short = 'l', long = "library", num_args = 1.., value_name = "PATTERN")]
    libraries: Vec<Pattern>,

    /// Library name patterns to exclude from deployment
    #[arg(long, value_name = "PATTERN")]
    exclude_library: Vec<String>,
}

impl Bundle {
    pub(crate) fn execute(self) -> Result<()> {
        let destination = std::path::absolute(&self.destination)?;

        if destination.exists() {
            ensure!(
                fs::read_dir(&destination)?.next().is_none(),
                "destination must be empty"
            );
        }

        let mut command = Command::new("linuxdeploy");

        command.arg("--appdir").arg(&destination);

        let mut copies = Vec::new();

        for file in expand(self.executables)? {
            let mut magic = Vec::new();

            fs::File::open(&file)?.take(4).read_to_end(&mut magic)?;

            if magic == b"\x7fELF" {
                command.arg("-e").arg(file);
            } else {
                copies.push(file);
            }
        }

        for file in expand(self.libraries)? {
            command.arg("-l").arg(file);
        }

        for pattern in self.exclude_library {
            command.arg("--exclude-library").arg(pattern);
        }

        let mut search = self
            .library_path
            .iter()
            .map(std::path::absolute)
            .collect::<std::io::Result<Vec<_>>>()?;

        if let Some(original) = env::var_os("LD_LIBRARY_PATH") {
            search.extend(env::split_paths(&original));
        }

        command.env("LD_LIBRARY_PATH", env::join_paths(search)?);

        let binaries = tempfile::tempdir()?;

        for (name, bytes) in BINARIES {
            let file = binaries.path().join(name);
            fs::write(&file, bytes)?;
            fs::set_permissions(&file, fs::Permissions::from_mode(0o755))?;
        }

        let mut path = vec![binaries.path().to_path_buf()];

        if let Some(original) = env::var_os("PATH") {
            path.extend(env::split_paths(&original));
        }

        command.env("PATH", env::join_paths(path)?);

        ensure!(
            command.status().context("run linuxdeploy")?.success(),
            "linuxdeploy failed"
        );

        for file in copies {
            fs::copy(
                &file,
                destination.join("usr/bin").join(file.file_name().unwrap()),
            )?;
        }

        let share = destination.join("usr/share");

        if share.exists() {
            fs::remove_dir_all(share)?;
        }

        Ok(())
    }
}

fn expand(inputs: Vec<Pattern>) -> Result<BTreeSet<PathBuf>> {
    let mut files = BTreeSet::new();

    for input in inputs {
        let input = input.as_str();
        let mut found = false;

        for path in glob::glob(input)? {
            let path = path?;

            if path.is_file() {
                files.insert(std::path::absolute(path)?);
                found = true;
            }
        }

        ensure!(found, "no files matching {input:?}");
    }

    Ok(files)
}
