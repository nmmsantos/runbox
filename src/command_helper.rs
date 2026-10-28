use crate::{assets, detection, shim_linuxdeploy};
use anyhow::{Context, Result, ensure};
use clap::Args;
use std::{
    ffi::OsString,
    io::{self, Write},
    os::unix::process::ExitStatusExt,
    process::{Command, Stdio},
};

type Hook = fn(bool) -> Result<String>;

const REGISTRY: &[(&str, Hook)] = &[("linuxdeploy", shim_linuxdeploy::pre_run)];

#[derive(Args)]
pub(crate) struct Helper {
    /// Print the composed helper script without executing it
    #[arg(short = 'p', long)]
    print: bool,

    #[arg(value_parser = clap::builder::PossibleValuesParser::new(assets::helper_names()))]
    name: String,

    #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
    arguments: Vec<OsString>,
}

impl Helper {
    pub(crate) fn execute(self) -> Result<i32> {
        let script = assets::helper(&self.name)?;

        let pre_run_output = REGISTRY
            .iter()
            .find(|(name, _)| *name == self.name)
            .map(|(_, hook)| hook(self.print))
            .transpose()?
            .unwrap_or_default();

        let script = script
            .split('\n')
            .map(|line| {
                if line.trim() == "# runbox pre-run-output" {
                    return Ok(pre_run_output.as_str());
                }

                let Some(name) = line.trim().strip_prefix("# runbox include ") else {
                    return Ok(line);
                };

                let include = assets::helper_include(name.trim())?;

                Ok(include
                    .trim()
                    .strip_prefix("#!/bin/sh")
                    .with_context(|| format!("helper include {name} has no shell shebang"))?
                    .trim())
            })
            .collect::<Result<Vec<_>>>()?
            .join("\n");

        if self.print {
            io::stdout().lock().write_all(script.as_bytes())?;
            return Ok(0);
        }

        ensure!(
            detection::in_container(),
            "helpers must run inside a runbox container"
        );

        let output = Command::new("/bin/sh")
            .arg("-c")
            .arg(script)
            .arg(&self.name)
            .args(&self.arguments)
            .stderr(Stdio::inherit())
            .output()
            .context("execute /bin/sh helper")?;

        if output.status.success() {
            io::stdout().lock().write_all(&output.stdout)?;
        }

        Ok(output
            .status
            .code()
            .unwrap_or_else(|| 128 + output.status.signal().unwrap_or(1)))
    }
}
