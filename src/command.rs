use crate::{command_build::Build, command_helper::Helper, command_run::Run};
use anyhow::Result;
use clap::{Parser, Subcommand};

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

    /// Run a script in a Docker container
    Run(Run),

    /// Run an embedded shell helper inside a runbox container
    Helper(Helper),
}

pub(crate) fn run() -> Result<i32> {
    match Cli::parse().command {
        Action::Build(command) => command.execute().map(|()| 0),
        Action::Run(command) => command.execute().map(|()| 0),
        Action::Helper(command) => command.execute(),
    }
}
