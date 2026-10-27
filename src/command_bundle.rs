use anyhow::{Context, Result, ensure};
use clap::Args;
use glob::Pattern;
use std::{
    collections::{BTreeMap, BTreeSet},
    env,
    ffi::OsString,
    fs,
    path::{Path, PathBuf},
    process::Command,
};
use walkdir::WalkDir;

#[derive(Args)]
pub(crate) struct Bundle {
    /// New or empty destination directory
    destination: PathBuf,

    /// Print planned operations without writing files
    #[arg(long)]
    dry_run: bool,

    /// Additional library search directory (repeatable)
    #[arg(long, value_name = "DIRECTORY")]
    library_path: Vec<PathBuf>,

    /// Exclude an absolute source path glob (repeatable)
    #[arg(long, value_name = "PATTERN")]
    exclude: Vec<Pattern>,

    #[arg(last = true, required = true, value_name = "PATH")]
    paths: Vec<PathBuf>,
}

impl Bundle {
    pub(crate) fn execute(self) -> Result<()> {
        let mut scanner = DependencyScanner::new(&self.library_path, self.exclude)?;
        let destination = std::path::absolute(&self.destination)?;

        if destination.exists() {
            ensure!(
                fs::read_dir(&destination)?.next().is_none(),
                "destination must be empty"
            );
        }

        let mut files = Vec::new();

        for entry in self
            .paths
            .iter()
            .flat_map(|path| WalkDir::new(path).follow_links(true))
        {
            let entry = entry?;

            if entry.file_type().is_dir() {
                continue;
            }

            ensure!(
                entry.file_type().is_file(),
                "not a file: {:?}",
                entry.path()
            );

            files.push(entry.into_path());
        }

        scanner.scan(files)?;

        if !self.dry_run {
            fs::create_dir_all(&destination)?;
        }

        for (source, operation) in scanner.operations {
            let target = destination.join(source.strip_prefix("/")?);

            if self.dry_run {
                println!("{target:?}: {operation:?}");
            } else {
                operation.execute(&source, &target)?;
            }
        }

        Ok(())
    }
}

struct DependencyScanner {
    library_path: OsString,
    libraries: BTreeMap<OsString, PathBuf>,
    exclude: Vec<Pattern>,
    operations: BTreeMap<PathBuf, Operation>,
    files: BTreeSet<PathBuf>,
}

impl DependencyScanner {
    fn new(paths: &[PathBuf], exclude: Vec<Pattern>) -> Result<Self> {
        let mut search = env::var_os("LD_LIBRARY_PATH")
            .map(|value| env::split_paths(&value).collect::<Vec<_>>())
            .unwrap_or_default();

        for path in paths {
            search.push(std::path::absolute(path)?);
        }

        Ok(Self {
            library_path: env::join_paths(search)?,
            libraries: BTreeMap::new(),
            files: BTreeSet::new(),
            exclude,
            operations: BTreeMap::new(),
        })
    }

    fn scan(&mut self, files: Vec<PathBuf>) -> Result<()> {
        for file in files {
            let file = normalize_path(&file)?;

            if self.files.contains(&file) {
                continue;
            }

            let output = Command::new("ldd")
                .env("LC_ALL", "C")
                .env("LD_LIBRARY_PATH", &self.library_path)
                .arg(&file)
                .output()
                .context("run ldd")?;

            let stdout = String::from_utf8(output.stdout)?;
            let stderr = String::from_utf8_lossy(&output.stderr);

            if stderr.contains("not a dynamic executable") || stdout.trim() == "statically linked" {
                self.files.insert(file.clone());
                self.plan(file, BTreeMap::new())?;
                continue;
            }

            ensure!(output.status.success(), "ldd {file:?}: {stderr}");

            let interpreter = Command::new("patchelf")
                .arg("--print-interpreter")
                .arg(&file)
                .output()?;

            let interpreter = if interpreter.status.success() {
                Some(fs::canonicalize(
                    String::from_utf8(interpreter.stdout)?.trim_end(),
                )?)
            } else {
                None
            };

            for line in stdout.lines().map(str::trim) {
                let line = line.rsplit_once(" (0x").map_or(line, |(path, _)| path);

                let (name, path) = match line.split_once(" => ") {
                    Some(pair) => pair,
                    None if line.starts_with('/') => (line, line),
                    _ => continue,
                };

                ensure!(path != "not found", "unresolved dependencies: {name}");

                let path = normalize_path(Path::new(path))?;

                self.insert_library(name, path)?;
            }

            self.scan_recursive(vec![file], interpreter.as_deref())?;
        }

        Ok(())
    }

    fn insert_library(&mut self, name: &str, path: PathBuf) -> Result<()> {
        let key = Path::new(name)
            .file_name()
            .context("library name")?
            .to_owned();

        if let Some(previous) = self.libraries.insert(key, path.clone()) {
            ensure!(
                fs::canonicalize(&previous)? == fs::canonicalize(&path)?,
                "conflicting library paths: {previous:?} and {path:?}"
            );
        }

        Ok(())
    }

    fn scan_recursive(&mut self, paths: Vec<PathBuf>, interpreter: Option<&Path>) -> Result<()> {
        for path in paths {
            if self.files.contains(&path) {
                continue;
            }

            let dependencies = self.dependencies(&path, interpreter)?;
            let paths = dependencies.values().cloned().collect();

            self.files.insert(path.clone());
            self.plan(path, dependencies)?;
            self.scan_recursive(paths, interpreter)?;
        }

        Ok(())
    }

    fn dependencies(
        &self,
        file: &Path,
        interpreter: Option<&Path>,
    ) -> Result<BTreeMap<String, PathBuf>> {
        let mut resolved = BTreeMap::new();

        let needed = Command::new("patchelf")
            .arg("--print-needed")
            .arg(file)
            .output()?;

        ensure!(
            needed.status.success(),
            "read dependencies of {file:?}: {}",
            String::from_utf8_lossy(&needed.stderr)
        );

        let needed = String::from_utf8(needed.stdout)?;

        for name in needed.lines() {
            let key = Path::new(name).file_name().context("library name")?;
            let path = self
                .libraries
                .get(key)
                .with_context(|| format!("unresolved dependencies: {name} needed by {file:?}"))?;

            if let Some(interpreter) = interpreter
                && fs::canonicalize(path)? == interpreter
            {
                continue;
            }

            resolved.insert(name.to_owned(), path.clone());
        }

        Ok(resolved)
    }

    fn plan(&mut self, source: PathBuf, mut dependencies: BTreeMap<String, PathBuf>) -> Result<()> {
        if self.excluded(&source) {
            return Ok(());
        }

        dependencies.retain(|_, path| !self.excluded(path));

        let origin = source.parent().unwrap();

        let operation = if dependencies.is_empty() {
            Operation::Copy
        } else {
            let directories = dependencies
                .values()
                .map(|path| {
                    let directory = path.parent().unwrap();
                    let common = origin
                        .components()
                        .zip(directory.components())
                        .take_while(|(a, b)| a == b)
                        .count();
                    let mut relative = PathBuf::from("$ORIGIN");
                    relative.extend(origin.components().skip(common).map(|_| ".."));
                    relative.extend(directory.components().skip(common));
                    relative
                })
                .collect::<BTreeSet<_>>();

            Operation::Patch {
                runpath: env::join_paths(directories)?,

                replacements: dependencies
                    .iter()
                    .filter(|(name, _)| name.contains('/'))
                    .map(|(name, path)| (name.clone(), PathBuf::from(path.file_name().unwrap())))
                    .collect(),
            }
        };

        self.operations.insert(source, operation);

        Ok(())
    }

    fn excluded(&self, path: &Path) -> bool {
        path.ancestors().any(|path| {
            self.exclude
                .iter()
                .any(|pattern| pattern.matches_path(path))
        })
    }
}

#[derive(Debug)]
enum Operation {
    Copy,
    Patch {
        runpath: OsString,
        replacements: BTreeMap<String, PathBuf>,
    },
}

impl Operation {
    fn execute(self, source: &Path, target: &Path) -> Result<()> {
        fs::create_dir_all(target.parent().unwrap())?;

        match self {
            Self::Copy => {
                fs::copy(source, target).with_context(|| format!("copy {source:?}"))?;
            }
            Self::Patch {
                runpath,
                replacements,
            } => {
                let mut command = Command::new("patchelf");

                for (name, path) in replacements {
                    command.args(["--replace-needed", &name]).arg(path);
                }

                let output = command
                    .arg("--set-rpath")
                    .arg(runpath)
                    .arg("--output")
                    .arg(target)
                    .arg(source)
                    .output()
                    .context("run patchelf")?;

                ensure!(
                    output.status.success(),
                    "patch {source:?}: {}",
                    String::from_utf8_lossy(&output.stderr)
                );

                fs::set_permissions(target, fs::metadata(source)?.permissions())?;
            }
        }

        Ok(())
    }
}

fn normalize_path(path: &Path) -> Result<PathBuf> {
    let mut normalized = PathBuf::new();

    for component in std::path::absolute(path)?.components() {
        if component == std::path::Component::ParentDir {
            normalized = fs::canonicalize(&normalized)?;
            normalized.pop();
        } else {
            normalized.push(component);
        }
    }

    Ok(normalized)
}
