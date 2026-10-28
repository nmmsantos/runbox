#![forbid(unsafe_code)]

mod assets;
mod command;
mod command_build;
mod command_helper;
mod command_run;
mod detection;
mod shim;
mod shim_linuxdeploy;

use std::process;

fn main() {
    match shim::run().unwrap_or_else(command::run) {
        Ok(code) => process::exit(code),
        Err(error) => {
            eprintln!("runbox: {error:#}");
            process::exit(1);
        }
    }
}
