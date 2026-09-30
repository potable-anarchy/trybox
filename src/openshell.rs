// openshell.rs — OpenShell CLI wrappers: gateway list/register, sandbox CRUD.
//
// Depends on: config.rs, process.rs, trydir.rs

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use crate::trydir::Trybox;

/// Find a binary in PATH, falling back to the dev release dir.
/// Mirrors Python's _which().
pub fn which(name: &str) -> Option<String> {
    // Try PATH first
    if let Ok(output) = Command::new("which").arg(name).output() {
        if output.status.success() {
            let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !path.is_empty() {
                return Some(path);
            }
        }
    }

    // Fallback to dev release dir
    let dev = crate::config::home()
        .join(crate::config::DEV_RELEASE_SUBDIR)
        .join(name);
    if dev.exists() {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(meta) = fs::metadata(&dev) {
            if meta.permissions().mode() & 0o111 != 0 {
                return Some(dev.to_string_lossy().to_string());
            }
        }
    }
    None
}

/// Return the openshell binary path.
pub fn openshell_bin() -> Option<String> {
    which("openshell")
}

/// Output from a quiet subprocess run (mirrors _run()).
pub struct QuietOutput {
    pub success: bool,
    pub stdout: String,
    pub stderr: String,
}

/// Run a command, capturing output, never raising (mirrors _run()).
pub fn run_quiet(cmd: &[String]) -> QuietOutput {
    if cmd.is_empty() {
        return QuietOutput {
            success: false,
            stdout: String::new(),
            stderr: "empty command".to_string(),
        };
    }
    let output = Command::new(&cmd[0]).args(&cmd[1..]).output();
    match output {
        Ok(o) => QuietOutput {
            success: o.status.success(),
            stdout: String::from_utf8_lossy(&o.stdout).to_string(),
            stderr: String::from_utf8_lossy(&o.stderr).to_string(),
        },
        Err(e) => QuietOutput {
            success: false,
            stdout: String::new(),
            stderr: e.to_string(),
        },
    }
}

/// Return registered gateways as parsed from `openshell gateway list --json`.
pub fn gateway_list() -> Vec<serde_json::Value> {
    let osc = match openshell_bin() {
        Some(p) => p,
        None => return vec![],
    };
    let result = run_quiet(&[
        osc,
        "gateway".to_string(),
        "list".to_string(),
        "--json".to_string(),
    ]);
    if !result.success || result.stdout.trim().is_empty() {
        return vec![];
    }
    serde_json::from_str(&result.stdout).unwrap_or_default()
}

/// Check if a gateway is registered by name.
pub fn gateway_registered(name: &str) -> bool {
    gateway_list()
        .iter()
        .any(|g| g.get("name").and_then(|n| n.as_str()) == Some(name))
}

/// Register + select the trybox gateway if needed; returns exit code.
pub fn ensure_gateway_registered() -> i32 {
    let osc = match openshell_bin() {
        Some(p) => p,
        None => {
            eprintln!("openshell CLI not found in PATH (brew install nvidia/openshell/openshell)");
            return 1;
        }
    };

    if !gateway_registered(crate::config::GATEWAY_NAME) {
        // Copy mTLS certs BEFORE gateway add — `openshell gateway add --local`
        // requires them to exist in the gateway config directory.
        let mtls_dir = crate::config::home()
            .join(".config")
            .join("openshell")
            .join("gateways")
            .join(crate::config::GATEWAY_NAME)
            .join("mtls");
        let _ = fs::create_dir_all(&mtls_dir);
        let _ = fs::copy(crate::config::ca_crt(), mtls_dir.join("ca.crt"));
        let _ = fs::copy(crate::config::client_crt(), mtls_dir.join("tls.crt"));
        let _ = fs::copy(crate::config::client_key(), mtls_dir.join("tls.key"));

        let result = run_quiet(&[
            osc.clone(),
            "gateway".to_string(),
            "add".to_string(),
            "--local".to_string(),
            "--name".to_string(),
            crate::config::GATEWAY_NAME.to_string(),
            crate::config::gateway_endpoint(),
        ]);
        if !result.success {
            // Gateway may already be registered from a previous run.
            // Try to select it; if that works, we're fine.
            let result2 = run_quiet(&[
                osc.clone(),
                "gateway".to_string(),
                "select".to_string(),
                crate::config::GATEWAY_NAME.to_string(),
            ]);
            if result2.success {
                println!(
                    "gateway already registered: {}",
                    crate::config::GATEWAY_NAME
                );
            } else {
                eprintln!(
                    "openshell gateway add failed:\n{}",
                    if !result.stderr.trim().is_empty() {
                        result.stderr.trim()
                    } else {
                        result.stdout.trim()
                    }
                );
                return 1;
            }
        } else {
            println!("registered gateway: {}", crate::config::GATEWAY_NAME);
        }
    }

    let result = run_quiet(&[
        osc,
        "gateway".to_string(),
        "select".to_string(),
        crate::config::GATEWAY_NAME.to_string(),
    ]);
    if !result.success {
        eprintln!(
            "openshell gateway select failed:\n{}",
            if !result.stderr.trim().is_empty() {
                result.stderr.trim()
            } else {
                result.stdout.trim()
            }
        );
        return 1;
    }
    0
}

/// Return list of openshell sandboxes as parsed JSON values.
pub fn sandbox_list() -> Vec<serde_json::Value> {
    let osc = match openshell_bin() {
        Some(p) => p,
        None => return vec![],
    };
    let result = run_quiet(&[
        osc,
        "sandbox".to_string(),
        "list".to_string(),
        "--json".to_string(),
    ]);
    if !result.success {
        return vec![];
    }
    serde_json::from_str(&result.stdout).unwrap_or_default()
}

/// Check if a sandbox exists by name.
pub fn sandbox_exists(name: &str) -> bool {
    sandbox_list()
        .iter()
        .any(|s| s.get("name").and_then(|n| n.as_str()) == Some(name))
}

/// Create the openshell sandbox for this trybox.
pub fn sandbox_create(t: &Trybox, agent: &str, image: &str, policy: &str) {
    let osc = match openshell_bin() {
        Some(p) => p,
        None => {
            eprintln!("openshell CLI not found in PATH");
            std::process::exit(1);
        }
    };

    let mut cmd = vec![
        osc,
        "sandbox".to_string(),
        "create".to_string(),
        "--name".to_string(),
        t.sandbox_name.clone(),
        "--from".to_string(),
        image.to_string(),
    ];

    if !policy.is_empty() && Path::new(policy).exists() {
        cmd.push("--policy".to_string());
        cmd.push(policy.to_string());
    }

    cmd.push("--".to_string());
    // Agent command must be shlex-split, not passed as single string
    let agent_parts = shell_words::split(agent).unwrap_or_else(|_| vec![agent.to_string()]);
    cmd.extend(agent_parts);

    println!("creating sandbox: {}", cmd.join(" "));
    let status = Command::new(&cmd[0]).args(&cmd[1..]).status();
    match status {
        Ok(s) if !s.success() => {
            eprintln!("openshell sandbox create failed (exit {})", s);
            std::process::exit(1);
        }
        Err(e) => {
            eprintln!("failed to run openshell sandbox create: {}", e);
            std::process::exit(1);
        }
        _ => {}
    }
}

/// Connect to an existing sandbox; replaces this process (inherits stdio).
pub fn sandbox_connect(t: &Trybox) -> i32 {
    let osc = match openshell_bin() {
        Some(p) => p,
        None => {
            eprintln!("openshell CLI not found in PATH");
            std::process::exit(1);
        }
    };
    let status = Command::new(&osc)
        .args(&["sandbox", "connect", &t.sandbox_name])
        .status();
    match status {
        Ok(s) => s.code().unwrap_or(1),
        Err(e) => {
            eprintln!("failed to run openshell sandbox connect: {}", e);
            1
        }
    }
}

/// Start the driver if not running; return true if it's up.
pub fn ensure_driver() -> bool {
    if crate::process::driver_running().is_some() {
        return true;
    }
    crate::commands::cmd_driver("start", None) == 0
}

/// Start the gateway if not running; return true if it's up.
pub fn ensure_gateway() -> bool {
    if crate::process::gateway_running().is_some() {
        return true;
    }
    crate::commands::cmd_gateway("start") == 0
}
