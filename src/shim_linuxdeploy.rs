use crate::assets::binary;
use anyhow::{Context, Result};
use std::{
    env,
    ffi::OsString,
    fs,
    io::{self, Write},
    os::unix::{
        ffi::OsStrExt,
        fs::{PermissionsExt, symlink},
        process::ExitStatusExt,
    },
    path::{Path, PathBuf, absolute},
    process::Command,
};

pub(crate) fn pre_run(print: bool) -> Result<String> {
    let prefix = "runbox-linuxdeploy-";

    let directory = if print {
        PathBuf::from(format!("/tmp/{prefix}XXXXXX"))
    } else {
        tempfile::Builder::new().prefix(prefix).tempdir()?.keep()
    };

    if !print {
        let app = directory.join("app");
        let private = app.join("_linuxdeploy");

        fs::create_dir_all(&private)?;

        let patchelf = app.join("patchelf");
        fs::write(&patchelf, binary("patchelf")?)?;
        fs::set_permissions(&patchelf, fs::Permissions::from_mode(0o755))?;

        symlink(env::current_exe()?, app.join("linuxdeploy"))?;

        let linuxdeploy = private.join("linuxdeploy");
        fs::write(&linuxdeploy, binary("linuxdeploy")?)?;
        fs::set_permissions(&linuxdeploy, fs::Permissions::from_mode(0o755))?;

        let dpkg_query = private.join("dpkg-query");
        fs::write(&dpkg_query, b"#!/bin/sh\n\nexit 1\n")?;
        fs::set_permissions(&dpkg_query, fs::Permissions::from_mode(0o755))?;

        let strip = private.join("strip");
        fs::write(&strip, b"#!/bin/sh\n\nexit 0\n")?;
        fs::set_permissions(&strip, fs::Permissions::from_mode(0o755))?;
    }

    let path = directory
        .to_str()
        .context("helper temporary directory must be UTF-8")?
        .replace('\'', "'\\''");

    Ok(format!("INSTALL_DIR='{path}'"))
}

pub(crate) fn execute() -> Result<i32> {
    let install = env::args_os()
        .next()
        .context("missing linuxdeploy invocation")?;

    let install = Path::new(&install);
    let install = if install
        .parent()
        .is_some_and(|parent| !parent.as_os_str().is_empty())
    {
        install.to_path_buf()
    } else {
        env::split_paths(&env::var_os("PATH").context("PATH is unset")?)
            .map(|directory| directory.join(install))
            .find(|candidate| candidate.is_file())
            .context("linuxdeploy was not found on PATH")?
    };

    let install = install
        .parent()
        .context("linuxdeploy invocation has no directory")?
        .to_path_buf();

    let mut incoming: Vec<_> = env::args_os().skip(1).collect();
    let mut outgoing = Vec::new();
    let mut libraries = Vec::new();
    let mut appdir = None;
    let mut cleanup = false;
    let mut help = false;

    while !incoming.is_empty() {
        let arg = incoming.remove(0);

        let Some(text) = arg.to_str() else {
            outgoing.push(arg);
            continue;
        };

        if let Some(taken) = take_values(
            &mut incoming,
            text,
            "--appdir=",
            "--appdir",
            "--appdir",
            Count::One,
        ) {
            if let TakeResult::One(Some(value)) = &taken {
                appdir = Some(PathBuf::from(value));
            }
            append(&mut outgoing, arg, "--appdir", taken);
        } else if let Some(taken) = take_values(
            &mut incoming,
            text,
            "--library=",
            "-l",
            "--library",
            Count::Many,
        ) {
            append(&mut outgoing, arg, "-l", taken);
        } else if let Some(taken) = take_values(
            &mut incoming,
            text,
            "--executable=",
            "-e",
            "--executable",
            Count::Many,
        ) {
            append(&mut outgoing, arg, "-e", taken);
        } else if let Some(taken) = take_values(
            &mut incoming,
            text,
            "--deploy-deps-only=",
            "--deploy-deps-only",
            "--deploy-deps-only",
            Count::Many,
        ) {
            append(&mut outgoing, arg, "--deploy-deps-only", taken);
        } else if let Some(TakeResult::Many(values)) = take_values(
            &mut incoming,
            text,
            "--library-path=",
            "-L",
            "--library-path",
            Count::Many,
        ) {
            let Some(values) = values else {
                anyhow::bail!("--library-path requires a value");
            };

            if values.iter().any(|value| value.is_empty()) {
                anyhow::bail!("--library-path requires a value");
            }

            for value in values {
                libraries.push(absolute(value)?);
            }
        } else if text == "--remove-empty-dirs" {
            cleanup = true;
        } else if text == "--help" || text == "-h" {
            help = true;
            outgoing.push(arg);
        } else {
            outgoing.push(arg);
        }
    }

    let mut command = Command::new("linuxdeploy");

    command.args(&outgoing);

    let mut paths = vec![install.join("_linuxdeploy")];

    if let Some(path) = env::var_os("PATH") {
        paths.extend(env::split_paths(&path));
    }

    command.env("PATH", env::join_paths(paths).context("compose PATH")?);

    if !libraries.is_empty() {
        let mut paths = libraries.clone();

        if let Some(path) = env::var_os("LD_LIBRARY_PATH") {
            paths.extend(env::split_paths(&path));
        }

        command.env(
            "LD_LIBRARY_PATH",
            env::join_paths(paths).context("compose LD_LIBRARY_PATH")?,
        );
    }

    let status = command.status().context("execute linuxdeploy")?;

    if help {
        io::stderr().write_all(EXTRA_HELP)?;
    } else if status.success()
        && cleanup
        && let Some(appdir) = &appdir
    {
        remove_empty_dirs(appdir)?;
    }

    Ok(status
        .code()
        .unwrap_or_else(|| 128 + status.signal().unwrap_or(1)))
}

const EXTRA_HELP: &[u8] = b"\
\n      -L[path...], --library-path=[path...]  Prepend directories to LD_LIBRARY_PATH\
\n      --remove-empty-dirs                   Recursively prune empty AppDir subdirectories after success\
\n      -e, -l, --deploy-deps-only            Accept multiple paths per option; the shell expands globs\n";

enum Count {
    One,
    Many,
}

enum TakeResult {
    One(Option<OsString>),
    Many(Option<Vec<OsString>>),
}

fn take_values(
    incoming: &mut Vec<OsString>,
    text: &str,
    equals: &str,
    short: &str,
    long: &str,
    count: Count,
) -> Option<TakeResult> {
    let values = if let Some(value) = text.strip_prefix(equals) {
        vec![OsString::from(value)]
    } else if !short.starts_with("--")
        && let Some(value) = text.strip_prefix(short).filter(|value| !value.is_empty())
    {
        vec![OsString::from(value)]
    } else if text == long || text == short {
        let mut values = Vec::new();

        while (matches!(count, Count::Many) || values.is_empty())
            && incoming
                .first()
                .is_some_and(|next| !(next.as_bytes().starts_with(b"-") && next != "-"))
        {
            values.push(incoming.remove(0));
        }

        values
    } else {
        return None;
    };

    Some(match count {
        Count::One => TakeResult::One(values.into_iter().next()),
        Count::Many => TakeResult::Many((!values.is_empty()).then_some(values)),
    })
}

fn append(outgoing: &mut Vec<OsString>, arg: OsString, flag: &str, taken: TakeResult) {
    let values = match taken {
        TakeResult::One(value) => Vec::from_iter(value),
        TakeResult::Many(values) => values.unwrap_or_default(),
    };
    if values.is_empty() {
        outgoing.push(arg);
    } else {
        for value in values {
            outgoing.extend([OsString::from(flag), value]);
        }
    }
}

fn remove_empty_dirs(root: &Path) -> Result<()> {
    for entry in fs::read_dir(root)? {
        let path = entry?.path();
        let file_type = fs::symlink_metadata(&path)?.file_type();

        if file_type.is_symlink() || !file_type.is_dir() {
            continue;
        }

        remove_empty_dirs(&path)?;

        if fs::read_dir(&path)?.next().is_none() {
            fs::remove_dir(path)?;
        }
    }

    Ok(())
}
