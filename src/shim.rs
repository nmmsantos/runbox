use crate::shim_linuxdeploy;
use anyhow::Result;
use std::{env, ffi::OsStr, path::Path};

pub(crate) fn run() -> Option<Result<i32>> {
    let invocation = env::args_os().next()?;

    match Path::new(&invocation).file_name()? {
        name if name == OsStr::new("linuxdeploy") => Some(shim_linuxdeploy::execute()),
        _ => None,
    }
}
