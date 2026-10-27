use crate::{
    command_build::Build, command_bundle::Bundle, command_helper::Helper, command_run::Run,
};
use anyhow::Result;
use clap::{Parser, Subcommand};
use std::process;

/// Run scripts in Docker and run embedded shell helpers
#[derive(Parser)]
#[command(version)]
struct Cli {
    #[command(subcommand)]
    command: Action,
}

#[derive(Subcommand)]
enum Action {
    /// Build the selected Docker image
    Build(Build),

    /// Bundle files and their shared libraries using ldd and patchelf
    Bundle(Bundle),

    /// Run a script in a Docker container
    Run(Run),

    /// Run an embedded shell helper inside a runbox container
    Helper(Helper),
}

fn execute() -> Result<i32> {
    match Cli::parse().command {
        Action::Build(command) => command.execute().map(|()| 0),
        Action::Bundle(command) => command.execute().map(|()| 0),
        Action::Run(command) => command.execute().map(|()| 0),
        Action::Helper(command) => command.execute(),
    }
}

pub(crate) fn run() {
    match execute() {
        Ok(code) => process::exit(code),
        Err(error) => {
            eprintln!("runbox: {error:#}");
            process::exit(1);
        }
    }
}
