// commands.rs — Command implementations.
//
// Depends on: all other modules.
//
// Each function returns an exit code (i32), matching the Python cmd_* functions.

use std::fs;
use std::path::PathBuf;
use std::process::Command;

use crate::trydir;

// --------------------------------------------------------------------------- //
// init
// --------------------------------------------------------------------------- //

pub fn cmd_init(force: bool) -> i32 {
    let tls_dir = crate::config::tls_dir();

    if crate::pki::pki_exists() && !force {
        println!(
            "PKI already exists at {} (use --force to regenerate)",
            tls_dir.display()
        );
    } else {
        println!("generating PKI at {} ...", tls_dir.display());
        crate::pki::generate_pki();
        println!("  CA:              {}", crate::config::ca_crt().display());
        println!(
            "  server cert:     {}",
            crate::config::server_crt().display()
        );
        println!(
            "  client cert:     {}",
            crate::config::client_crt().display()
        );
        println!(
            "  JWT signing key: {}",
            crate::config::jwt_signing().display()
        );
        println!(
            "  JWT public key:  {}",
            crate::config::jwt_public().display()
        );
        let kid = fs::read_to_string(crate::config::jwt_kid()).unwrap_or_default();
        println!("  JWT kid:         {}", kid.trim());
    }

    let gateway_toml = crate::config::gateway_toml();
    if gateway_toml.exists() && !force {
        println!(
            "gateway config already exists at {}",
            gateway_toml.display()
        );
    } else {
        crate::pki::write_gateway_toml();
        println!("wrote gateway config: {}", gateway_toml.display());
    }

    // Make sure the supervisor-bin dir exists so the driver can start.
    let supervisor_bin = crate::config::driver_supervisor_bin();
    let _ = fs::create_dir_all(&supervisor_bin);
    println!("supervisor bin dir:  {}", supervisor_bin.display());
    println!("trybox init complete. Next: trybox driver start && trybox gateway start");
    0
}

// --------------------------------------------------------------------------- //
// doctor
// --------------------------------------------------------------------------- //

pub fn cmd_doctor() -> i32 {
    let mut checks: Vec<(String, bool)> = Vec::new();

    // macOS arm64
    let arch = Command::new("uname").arg("-m").output();
    let arch_str = match arch {
        Ok(o) => String::from_utf8_lossy(&o.stdout).trim().to_string(),
        Err(_) => String::new(),
    };
    checks.push(("macOS arm64".to_string(), arch_str == "arm64"));

    // container CLI
    checks.push((
        "container CLI".to_string(),
        crate::openshell::which("container").is_some(),
    ));

    // try CLI
    checks.push((
        "try CLI".to_string(),
        crate::openshell::which("try").is_some(),
    ));

    // openshell CLI
    let osc = crate::openshell::openshell_bin();
    checks.push(("openshell CLI".to_string(), osc.is_some()));

    // openshell-gateway binary
    let gw_bin = crate::openshell::which("openshell-gateway");
    checks.push(("openshell-gateway binary".to_string(), gw_bin.is_some()));

    // openshell-driver-apple-container binary
    let driver_bin = crate::openshell::which("openshell-driver-apple-container");
    checks.push((
        "openshell-driver-apple-container binary".to_string(),
        driver_bin.is_some(),
    ));

    // try path
    let try_path = crate::config::default_try_path();
    checks.push((
        format!("try path ({})", try_path.display()),
        try_path.exists(),
    ));

    // PKI dir
    let tls_dir = crate::config::tls_dir();
    checks.push((
        format!("PKI dir ({})", tls_dir.display()),
        tls_dir.exists() && crate::pki::pki_exists(),
    ));

    // gateway.toml
    let gateway_toml = crate::config::gateway_toml();
    checks.push((
        format!("gateway.toml ({})", gateway_toml.display()),
        gateway_toml.exists(),
    ));

    // Driver socket
    let driver_sock = crate::config::driver_sock();
    checks.push((
        format!("driver socket ({})", driver_sock.display()),
        driver_sock.exists(),
    ));

    // Driver running
    let dpid = crate::process::driver_running();
    checks.push((
        if let Some(pid) = dpid {
            format!("driver running (pid {})", pid)
        } else {
            "driver running".to_string()
        },
        dpid.is_some(),
    ));

    // Driver version
    if let Some(ref driver_bin) = driver_bin {
        let dv = crate::openshell::run_quiet(&[driver_bin.clone(), "--version".to_string()]);
        let version_line = if dv.success {
            dv.stdout.lines().next().unwrap_or("unknown").to_string()
        } else {
            "unknown".to_string()
        };
        checks.push((format!("driver version: {}", version_line), dv.success));
    }

    // Gateway running
    let gpid = crate::process::gateway_running();
    checks.push((
        if let Some(pid) = gpid {
            format!("gateway running (pid {})", pid)
        } else {
            "gateway running".to_string()
        },
        gpid.is_some(),
    ));

    // Gateway registration
    if osc.is_some() {
        checks.push((
            format!("gateway registered ({})", crate::config::GATEWAY_NAME),
            crate::openshell::gateway_registered(crate::config::GATEWAY_NAME),
        ));
    }

    let all_ok = checks.iter().all(|(_, ok)| *ok);
    for (label, ok) in &checks {
        let mark = if *ok { "ok  " } else { "FAIL" };
        println!("[{}] {}", mark, label);
    }
    if all_ok {
        0
    } else {
        1
    }
}

// --------------------------------------------------------------------------- //
// driver
// --------------------------------------------------------------------------- //

pub fn cmd_driver(action: &str, supervisor_bin_dir: Option<PathBuf>) -> i32 {
    if action == "status" {
        let pid = crate::process::driver_running();
        if let Some(pid) = pid {
            println!(
                "openshell-driver-apple-container running (pid {}, sock {})",
                pid,
                crate::config::driver_sock().display()
            );
            return 0;
        }
        println!("openshell-driver-apple-container not running");
        return 1;
    }

    if action == "stop" {
        let pid = crate::process::driver_running();
        if pid.is_none() {
            println!("no driver running");
            return 0;
        }
        let pid = pid.unwrap();
        crate::process::kill_process(pid);
        crate::process::unlink_pidfile(&crate::config::driver_pidfile());
        println!("stopped driver (pid {})", pid);
        return 0;
    }

    if action == "start" {
        if crate::process::driver_running().is_some() {
            let pid = crate::process::driver_running().unwrap();
            println!("driver already running (pid {})", pid);
            return 0;
        }
        let driver_bin = match crate::openshell::which("openshell-driver-apple-container") {
            Some(p) => p,
            None => {
                eprintln!("openshell-driver-apple-container not installed. See `trybox doctor`.");
                return 1;
            }
        };
        let supervisor_bin =
            supervisor_bin_dir.unwrap_or_else(crate::config::driver_supervisor_bin);
        if !supervisor_bin.exists() {
            eprintln!("supervisor_bin_dir missing: {}", supervisor_bin.display());
            return 1;
        }
        if !crate::pki::pki_exists() {
            eprintln!(
                "PKI missing at {} — run `trybox init` first.",
                crate::config::tls_dir().display()
            );
            return 1;
        }
        let _ = fs::create_dir_all(crate::config::state_dir());

        let cmd = vec![
            driver_bin.clone(),
            "--bind-socket".to_string(),
            crate::config::driver_sock().to_string_lossy().to_string(),
            "--supervisor-bin-dir".to_string(),
            supervisor_bin.to_string_lossy().to_string(),
            "--allow-same-uid-peer".to_string(),
            "--gateway-port".to_string(),
            crate::config::GATEWAY_PORT.to_string(),
            "--host-tls-ca".to_string(),
            crate::config::ca_crt().to_string_lossy().to_string(),
            "--host-tls-cert".to_string(),
            crate::config::client_crt().to_string_lossy().to_string(),
            "--host-tls-key".to_string(),
            crate::config::client_key().to_string_lossy().to_string(),
        ];
        println!("starting driver: {}", cmd.join(" "));
        match crate::process::spawn_daemon(
            &cmd,
            &crate::config::driver_log(),
            &crate::config::driver_pidfile(),
        ) {
            Ok(pid) => {
                println!(
                    "driver started (pid {}, sock {}, log {})",
                    pid,
                    crate::config::driver_sock().display(),
                    crate::config::driver_log().display()
                );
                0
            }
            Err(e) => {
                eprintln!("failed to start driver: {}", e);
                1
            }
        }
    } else {
        eprintln!("unknown driver action: {}", action);
        1
    }
}

// --------------------------------------------------------------------------- //
// gateway
// --------------------------------------------------------------------------- //

pub fn cmd_gateway(action: &str) -> i32 {
    if action == "status" {
        let pid = crate::process::gateway_running();
        if let Some(pid) = pid {
            println!(
                "openshell-gateway running (pid {}, log {})",
                pid,
                crate::config::gateway_log().display()
            );
            return 0;
        }
        println!("openshell-gateway not running");
        return 1;
    }

    if action == "stop" {
        let pid = crate::process::gateway_running();
        if pid.is_none() {
            println!("no gateway running");
            return 0;
        }
        let pid = pid.unwrap();
        crate::process::kill_process(pid);
        crate::process::unlink_pidfile(&crate::config::gateway_pidfile());
        println!("stopped gateway (pid {})", pid);
        return 0;
    }

    if action == "start" {
        if crate::process::gateway_running().is_some() {
            let pid = crate::process::gateway_running().unwrap();
            println!("gateway already running (pid {})", pid);
            return 0;
        }
        let gw_bin = match crate::openshell::which("openshell-gateway") {
            Some(p) => p,
            None => {
                eprintln!("openshell-gateway not installed. See `trybox doctor`.");
                return 1;
            }
        };
        let gateway_toml = crate::config::gateway_toml();
        if !gateway_toml.exists() {
            eprintln!(
                "gateway config missing: {} — run `trybox init` first.",
                gateway_toml.display()
            );
            return 1;
        }
        let _ = fs::create_dir_all(crate::config::state_dir());

        // Kill any stale process holding our port (e.g. launchd-managed gateway)
        crate::process::ensure_port_free(crate::config::GATEWAY_PORT);

        let cmd = vec![
            gw_bin.clone(),
            "--config".to_string(),
            gateway_toml.to_string_lossy().to_string(),
            "--compute-driver".to_string(),
            "apple-container".to_string(),
            "--compute-driver-socket".to_string(),
            crate::config::driver_sock().to_string_lossy().to_string(),
            "--db-url".to_string(),
            crate::config::DB_URL.to_string(),
        ];
        println!("starting gateway: {}", cmd.join(" "));
        match crate::process::spawn_daemon(
            &cmd,
            &crate::config::gateway_log(),
            &crate::config::gateway_pidfile(),
        ) {
            Ok(pid) => {
                println!(
                    "gateway started (pid {}, log {})",
                    pid,
                    crate::config::gateway_log().display()
                );
                0
            }
            Err(e) => {
                eprintln!("failed to start gateway: {}", e);
                1
            }
        }
    } else {
        eprintln!("unknown gateway action: {}", action);
        1
    }
}

// --------------------------------------------------------------------------- //
// image
// --------------------------------------------------------------------------- //

pub fn cmd_image(tag: &str) -> i32 {
    // Find build.sh: relative to CWD, or in share dir
    let candidates = [
        PathBuf::from("images/build.sh"),
        crate::config::share_dir().join("images").join("build.sh"),
    ];
    let script = candidates.iter().find(|p| p.exists());

    let script = match script {
        Some(p) => p,
        None => {
            eprintln!("images/build.sh not found");
            return 1;
        }
    };

    let status = Command::new("bash")
        .arg(script)
        .env("TRYBOX_IMAGE_REF", tag)
        .status();
    match status {
        Ok(s) => s.code().unwrap_or(1),
        Err(e) => {
            eprintln!("failed to run build.sh: {}", e);
            1
        }
    }
}

// --------------------------------------------------------------------------- //
// list
// --------------------------------------------------------------------------- //

pub fn cmd_list() -> i32 {
    let sandboxes: std::collections::HashMap<String, serde_json::Value> =
        crate::openshell::sandbox_list()
            .into_iter()
            .filter_map(|s| {
                let name = s.get("name").and_then(|n| n.as_str())?.to_string();
                Some((name, s))
            })
            .collect();

    let try_path = crate::config::default_try_path();
    if !try_path.exists() {
        println!("(no tries yet)");
        return 0;
    }

    let re = regex::Regex::new(r"^(\d{4}-\d{2}-\d{2})-(.+)$").unwrap();
    let mut rows: Vec<(String, String, String, String)> = Vec::new();

    let entries = match fs::read_dir(&try_path) {
        Ok(e) => e,
        Err(_) => {
            println!("(no tries yet)");
            return 0;
        }
    };

    let mut dir_entries: Vec<_> = entries.collect::<Result<_, _>>().unwrap_or_default();
    dir_entries.sort_by_key(|e| e.file_name());

    for entry in dir_entries {
        if !entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
            continue;
        }
        let name = entry.file_name().to_string_lossy().to_string();
        if let Some(caps) = re.captures(&name) {
            let date_prefix = caps[1].to_string();
            let slug = caps[2].to_string();
            let sb_name = format!("trybox-{}", slug);
            let state = sandboxes
                .get(&sb_name)
                .and_then(|s| s.get("state").and_then(|v| v.as_str()))
                .unwrap_or("-")
                .to_string();
            rows.push((date_prefix, slug, sb_name, state));
        }
    }

    if rows.is_empty() {
        println!("(no tryboxes yet)");
        return 0;
    }

    let width = rows.iter().map(|r| r.1.len()).max().unwrap_or(0);
    for (date_prefix, slug, sb_name, state) in &rows {
        println!(
            "{:<10}  {:<width$}  {:<10} {}",
            date_prefix,
            slug,
            state,
            sb_name,
            width = width
        );
    }
    0
}

// --------------------------------------------------------------------------- //
// stop
// --------------------------------------------------------------------------- //

pub fn cmd_stop(name: &str) -> i32 {
    let slug = trydir::slugify(name);
    let t = trydir::find_trybox(&slug, &crate::config::default_try_path());
    let target = t
        .as_ref()
        .map(|t| t.sandbox_name.clone())
        .unwrap_or_else(|| format!("trybox-{}", slug));

    let osc = match crate::openshell::openshell_bin() {
        Some(p) => p,
        None => {
            eprintln!("openshell CLI not found");
            return 1;
        }
    };
    let status = Command::new(&osc)
        .args(&["sandbox", "stop", &target])
        .status();
    match status {
        Ok(s) => s.code().unwrap_or(1),
        Err(e) => {
            eprintln!("failed to run openshell sandbox stop: {}", e);
            1
        }
    }
}

// --------------------------------------------------------------------------- //
// rm
// --------------------------------------------------------------------------- //

pub fn cmd_rm(name: &str, keep_dir: bool, yes: bool) -> i32 {
    let slug = trydir::slugify(name);
    let t = trydir::find_trybox(&slug, &crate::config::default_try_path());
    let target = t
        .as_ref()
        .map(|t| t.sandbox_name.clone())
        .unwrap_or_else(|| format!("trybox-{}", slug));

    let osc = match crate::openshell::openshell_bin() {
        Some(p) => p,
        None => {
            eprintln!("openshell CLI not found");
            return 1;
        }
    };

    let status = Command::new(&osc)
        .args(&["sandbox", "delete", &target])
        .status();
    let rc = match status {
        Ok(s) => s.code().unwrap_or(1),
        Err(e) => {
            eprintln!("failed to run openshell sandbox delete: {}", e);
            1
        }
    };
    if rc != 0 {
        return rc;
    }

    if let Some(t) = &t {
        if !keep_dir {
            let prompt = format!("also delete {}? [y/N] ", t.dir.display());
            let should_delete = if yes {
                true
            } else {
                print!("{}", prompt);
                use std::io::Write;
                let _ = std::io::stdout().flush();
                let mut input = String::new();
                let _ = std::io::stdin().read_line(&mut input);
                let input = input.trim().to_lowercase();
                input == "y" || input == "yes"
            };
            if should_delete {
                let _ = fs::remove_dir_all(&t.dir);
                println!("deleted {}", t.dir.display());
            }
        }
    }
    0
}

// --------------------------------------------------------------------------- //
// new_or_resume (bare name form)
// --------------------------------------------------------------------------- //

pub fn cmd_new_or_resume(
    name: Vec<String>,
    agent: String,
    image: String,
    policy: String,
    try_path: PathBuf,
) -> i32 {
    let name = trydir::slugify(&name.join(" "));
    if name.is_empty() {
        eprintln!("trybox needs a non-empty name");
        return 1;
    }

    // --- ensure infrastructure is running ---
    println!("ensuring driver ...");
    if !crate::openshell::ensure_driver() {
        eprintln!("failed to start driver — run `trybox driver start` manually");
        return 1;
    }
    println!("ensuring gateway ...");
    if !crate::openshell::ensure_gateway() {
        eprintln!("failed to start gateway — run `trybox gateway start` manually");
        return 1;
    }
    println!("ensuring gateway registered ...");
    if crate::openshell::ensure_gateway_registered() != 0 {
        eprintln!("failed to register/select gateway");
        return 1;
    }

    let existing = trydir::find_trybox(&name, &try_path);
    if let Some(t) = existing {
        if !crate::openshell::sandbox_exists(&t.sandbox_name) {
            println!(
                " resurrection: try dir {} exists, but sandbox {} is gone — recreating",
                t.dir.display(),
                t.sandbox_name
            );
            crate::openshell::sandbox_create(&t, &agent, &image, &policy);
        }
        println!("connecting: {}", t.dir.display());
        return crate::openshell::sandbox_connect(&t);
    }

    let t = trydir::create_try_dir(&name, &try_path);
    println!("created try dir: {}", t.dir.display());
    crate::openshell::sandbox_create(&t, &agent, &image, &policy);
    crate::openshell::sandbox_connect(&t)
}
