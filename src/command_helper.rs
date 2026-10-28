use crate::{
    assets::{HELPER_INCLUDES, HELPERS},
    detection,
};
use anyhow::{Context, Result, ensure};
use clap::Args;
use std::{
    ffi::OsString,
    io::{self, Write},
    os::unix::process::ExitStatusExt,
    process::{Command, Stdio},
};

#[derive(Args)]
pub(crate) struct Helper {
    /// Print the composed helper script without executing it
    #[arg(short = 'p', long)]
    print: bool,

    #[arg(value_parser = clap::builder::PossibleValuesParser::new(HELPERS.iter().map(|(name, _)| *name)))]
    name: String,

    #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
    arguments: Vec<OsString>,
}

impl Helper {
    pub(crate) fn execute(self) -> Result<i32> {
        let script = HELPERS
            .iter()
            .find(|(name, _)| *name == self.name)
            .expect("helper name validated by clap")
            .1;

        let script = script
            .split('\n')
            .map(|line| {
                let Some(name) = line.trim().strip_prefix("# runbox include ") else {
                    return Ok(line);
                };

                let include = HELPER_INCLUDES
                    .iter()
                    .find(|(key, _)| *key == name.trim())
                    .with_context(|| format!("unknown helper include: {name}"))?
                    .1;

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
