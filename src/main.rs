// trybox — turn a string into a dated try dir + a fresh openshell sandbox.
//
// MIT License. Copyright (c) 2026 Brad Dougherty.
//
// A thin wrapper around the OpenShell CLI that:
// 1. Generates a local PKI (TLS CA + server/client certs + Ed25519 JWT keys)
//    on `trybox init`.
// 2. Manages the three long-running processes: compute driver, gateway, and
//    (via the openshell CLI) the registered gateway endpoint.
// 3. Creates a dated try directory and a fresh sandbox, then connects to it.

mod commands;
mod config;
mod openshell;
mod pki;
mod process;
mod trydir;

use clap::{Parser, Subcommand};
use std::path::PathBuf;

const EPILOG: &str = "\
examples:
  trybox init
  trybox driver start
  trybox gateway start
  trybox my big new project
  trybox list
  trybox rm my-big-new-project

the name is slugged with try's rules (whitespace -> '-').
if a trybox by that name exists, `trybox <name>` resumes it; otherwise
it creates the try dir and a fresh openshell sandbox in one motion.";

/// trybox: one command to a sandboxed AI coding experiment on a Mac
#[derive(Parser)]
#[command(
    name = "trybox",
    version = config::VERSION,
    about = "One command to a sandboxed AI coding experiment on a Mac",
    long_about = None,
    disable_help_subcommand = true,
    after_help = EPILOG,
)]
struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,

    // --- Bare-name form flags (only used when no subcommand) ---
    /// agent CLI to run inside the sandbox (default: hermes; env TRYBOX_AGENT)
    #[arg(long, env = "TRYBOX_AGENT", default_value = "hermes")]
    agent: String,

    /// override sandbox image (default: local/trybox-sandbox:latest)
    #[arg(
        long,
        env = "TRYBOX_IMAGE",
        default_value = "local/trybox-sandbox:latest"
    )]
    image: String,

    /// openshell policy name (default: trybox-default-ro-github)
    #[arg(
        long,
        env = "TRYBOX_POLICY",
        default_value = "trybox-default-ro-github"
    )]
    policy: String,

    /// root for try dirs (default: ~/code/tries; env TRY_PATH)
    #[arg(long, env = "TRY_PATH")]
    try_path: Option<PathBuf>,

    /// name of the trybox to create or resume (free text)
    #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
    name: Vec<String>,
}

#[derive(Subcommand)]
enum Commands {
    /// Generate PKI + gateway config
    Init {
        /// regenerate PKI + config even if they exist
        #[arg(long)]
        force: bool,
    },
    /// Preflight checks
    Doctor,
    /// List tryboxes with sandbox state
    List,
    /// Stop a sandbox
    Stop { name: String },
    /// Delete a sandbox + optionally its try dir
    Rm {
        name: String,
        #[arg(long)]
        keep_dir: bool,
        #[arg(short = 'y', long)]
        yes: bool,
    },
    /// Manage the compute driver
    Driver {
        /// start | stop | status
        action: String,
        #[arg(long)]
        supervisor_bin_dir: Option<PathBuf>,
    },
    /// Manage the gateway
    Gateway {
        /// start | stop | status
        action: String,
    },
    /// Build the sandbox image
    Image {
        #[arg(long, default_value = "local/trybox-sandbox:latest")]
        tag: String,
    },
}

fn main() {
    let cli = Cli::parse();
    let exit_code = match cli.command {
        Some(cmd) => match cmd {
            Commands::Init { force } => commands::cmd_init(force),
            Commands::Doctor => commands::cmd_doctor(),
            Commands::List => commands::cmd_list(),
            Commands::Stop { name } => commands::cmd_stop(&name),
            Commands::Rm {
                name,
                keep_dir,
                yes,
            } => commands::cmd_rm(&name, keep_dir, yes),
            Commands::Driver {
                action,
                supervisor_bin_dir,
            } => commands::cmd_driver(&action, supervisor_bin_dir),
            Commands::Gateway { action } => commands::cmd_gateway(&action),
            Commands::Image { tag } => commands::cmd_image(&tag),
        },
        None => commands::cmd_new_or_resume(
            cli.name,
            cli.agent,
            cli.image,
            cli.policy,
            cli.try_path.unwrap_or_else(config::default_try_path),
        ),
    };
    std::process::exit(exit_code);
}
