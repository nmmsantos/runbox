#![forbid(unsafe_code)]

mod assets;
mod command;
mod command_build;
mod command_helper;
mod command_run;
mod detection;

fn main() {
    command::run();
}
