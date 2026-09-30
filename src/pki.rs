// pki.rs — PKI generation (openssl subprocess) + gateway.toml writing.
//
// Depends on: config.rs
//
// CRITICAL: All openssl commands must match the Python CLI exactly.
// We shell out to openssl (NOT rcgen) to guarantee identical certificate
// format that the gateway (Rust) expects.

use std::fs;
use std::path::Path;
use std::process::Command;

use sha2::{Digest, Sha256};

/// Run openssl with the given args. Exits with a formatted error on failure.
fn openssl(args: &[&str]) {
    let result = Command::new("openssl").args(args).output();
    match result {
        Ok(output) if output.status.success() => {}
        Ok(output) => {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let cmd_preview = args.iter().take(2).cloned().collect::<Vec<_>>().join(" ");
            eprintln!(
                "openssl {} ... failed (exit {}):\n{}",
                cmd_preview,
                output.status,
                stderr.trim()
            );
            std::process::exit(1);
        }
        Err(e) => {
            eprintln!("failed to execute openssl: {}", e);
            std::process::exit(1);
        }
    }
}

/// Return an openssl binary that supports Ed25519.
/// macOS LibreSSL lacks Ed25519 genpkey, so prefer Homebrew openssl@3.
fn openssl_ed() -> String {
    for candidate in &[
        "/opt/homebrew/opt/openssl@3/bin/openssl",
        "/usr/local/opt/openssl@3/bin/openssl",
    ] {
        if Path::new(candidate).exists() {
            return candidate.to_string();
        }
    }
    // Fall back to whatever "openssl" is in PATH
    which("openssl").unwrap_or_else(|| "openssl".to_string())
}

/// which() helper — find a binary in PATH.
fn which(name: &str) -> Option<String> {
    let output = Command::new("which").arg(name).output().ok()?;
    if output.status.success() {
        let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if !path.is_empty() {
            return Some(path);
        }
    }
    None
}

/// Ensure all required directories exist.
pub fn ensure_dirs() {
    for d in &[
        crate::config::share_dir(),
        crate::config::state_dir(),
        crate::config::tls_dir(),
        crate::config::server_dir(),
        crate::config::client_dir(),
        crate::config::jwt_dir(),
    ] {
        let _ = fs::create_dir_all(d);
    }
}

/// Check if all PKI files exist.
pub fn pki_exists() -> bool {
    [
        crate::config::ca_crt(),
        crate::config::server_crt(),
        crate::config::server_key(),
        crate::config::client_crt(),
        crate::config::client_key(),
        crate::config::jwt_signing(),
        crate::config::jwt_public(),
        crate::config::jwt_kid(),
    ]
    .iter()
    .all(|p| p.exists())
}

/// Generate the full PKI: TLS CA + server/client certs + Ed25519 JWT keys.
pub fn generate_pki() {
    ensure_dirs();

    let tls = crate::config::tls_dir();
    let ca_key = crate::config::ca_key();
    let ca_crt = crate::config::ca_crt();
    let server_key = crate::config::server_key();
    let server_crt = crate::config::server_crt();
    let client_key = crate::config::client_key();
    let client_crt = crate::config::client_crt();
    let jwt_signing = crate::config::jwt_signing();
    let jwt_public = crate::config::jwt_public();
    let jwt_kid = crate::config::jwt_kid();

    // --- CA (ECDSA P-256) ---
    openssl(&[
        "ecparam",
        "-name",
        "prime256v1",
        "-genkey",
        "-noout",
        "-out",
        ca_key.to_str().unwrap(),
    ]);
    openssl(&[
        "req",
        "-x509",
        "-new",
        "-key",
        ca_key.to_str().unwrap(),
        "-subj",
        "/CN=trybox-ca/O=trybox",
        "-days",
        "3650",
        "-out",
        ca_crt.to_str().unwrap(),
    ]);

    // --- Server cert (SAN IP:127.0.0.1) ---
    let serial_file = tls.join("ca.srl");
    let server_ext = tls.join("server.ext");
    fs::write(
        &server_ext,
        "subjectAltName=IP:127.0.0.1,DNS:localhost\nextendedKeyUsage=serverAuth\n",
    )
    .unwrap();
    let server_csr = tls.join("server.csr");

    openssl(&[
        "ecparam",
        "-name",
        "prime256v1",
        "-genkey",
        "-noout",
        "-out",
        server_key.to_str().unwrap(),
    ]);
    openssl(&[
        "req",
        "-new",
        "-key",
        server_key.to_str().unwrap(),
        "-subj",
        "/CN=trybox-server/O=trybox",
        "-out",
        server_csr.to_str().unwrap(),
    ]);
    openssl(&[
        "x509",
        "-req",
        "-sha256",
        "-in",
        server_csr.to_str().unwrap(),
        "-CA",
        ca_crt.to_str().unwrap(),
        "-CAkey",
        ca_key.to_str().unwrap(),
        "-CAserial",
        serial_file.to_str().unwrap(),
        "-CAcreateserial",
        "-days",
        "3650",
        "-extfile",
        server_ext.to_str().unwrap(),
        "-out",
        server_crt.to_str().unwrap(),
    ]);
    let _ = fs::remove_file(&server_csr);
    let _ = fs::remove_file(&server_ext);

    // --- Client cert (for mTLS) ---
    let client_csr = tls.join("client.csr");
    let client_ext = tls.join("client.ext");
    fs::write(&client_ext, "extendedKeyUsage=clientAuth\n").unwrap();

    openssl(&[
        "ecparam",
        "-name",
        "prime256v1",
        "-genkey",
        "-noout",
        "-out",
        client_key.to_str().unwrap(),
    ]);
    openssl(&[
        "req",
        "-new",
        "-key",
        client_key.to_str().unwrap(),
        "-subj",
        "/CN=trybox-client/O=trybox",
        "-out",
        client_csr.to_str().unwrap(),
    ]);
    openssl(&[
        "x509",
        "-req",
        "-sha256",
        "-in",
        client_csr.to_str().unwrap(),
        "-CA",
        ca_crt.to_str().unwrap(),
        "-CAkey",
        ca_key.to_str().unwrap(),
        "-CAserial",
        serial_file.to_str().unwrap(),
        "-CAcreateserial",
        "-days",
        "3650",
        "-extfile",
        client_ext.to_str().unwrap(),
        "-out",
        client_crt.to_str().unwrap(),
    ]);
    let _ = fs::remove_file(&client_csr);
    let _ = fs::remove_file(&client_ext);

    // --- JWT keys (Ed25519) ---
    let ed_openssl = openssl_ed();
    let ed_result = Command::new(&ed_openssl)
        .args(&[
            "genpkey",
            "-algorithm",
            "Ed25519",
            "-out",
            jwt_signing.to_str().unwrap(),
        ])
        .output();
    match ed_result {
        Ok(output) if !output.status.success() => {
            let stderr = String::from_utf8_lossy(&output.stderr);
            eprintln!(
                "Ed25519 keygen failed (exit {}):\n{}\nInstall Homebrew openssl@3: brew install openssl@3",
                output.status,
                stderr.trim()
            );
            std::process::exit(1);
        }
        Err(e) => {
            eprintln!("failed to execute Ed25519 keygen: {}", e);
            std::process::exit(1);
        }
        _ => {}
    }

    let pub_result = Command::new(&ed_openssl)
        .args(&[
            "pkey",
            "-in",
            jwt_signing.to_str().unwrap(),
            "-pubout",
            "-out",
            jwt_public.to_str().unwrap(),
        ])
        .output();
    match pub_result {
        Ok(output) if !output.status.success() => {
            let stderr = String::from_utf8_lossy(&output.stderr);
            eprintln!(
                "Ed25519 pubkey extraction failed (exit {}):\n{}",
                output.status,
                stderr.trim()
            );
            std::process::exit(1);
        }
        Err(e) => {
            eprintln!("failed to extract Ed25519 public key: {}", e);
            std::process::exit(1);
        }
        _ => {}
    }

    // JWT kid = sha256(public_key_bytes)[:32]
    let pub_bytes = fs::read(&jwt_public).unwrap();
    let mut hasher = Sha256::new();
    hasher.update(&pub_bytes);
    let hash = hasher.finalize();
    let kid = hash
        .iter()
        .map(|b| format!("{:02x}", b))
        .collect::<String>();
    let kid = &kid[..32];
    fs::write(&jwt_kid, kid).unwrap();

    // Lock down private material.
    for key in &[&ca_key, &server_key, &client_key, &jwt_signing] {
        set_mode_600(key);
    }
}

#[cfg(unix)]
fn set_mode_600(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    if let Ok(meta) = fs::metadata(path) {
        let mut perms = meta.permissions();
        perms.set_mode(0o600);
        let _ = fs::set_permissions(path, perms);
    }
}

#[cfg(not(unix))]
fn set_mode_600(_path: &Path) {}

/// Write the gateway config TOML, pointing at the PKI dir.
pub fn write_gateway_toml() {
    let tls = crate::config::tls_dir();
    let toml = format!(
        "[openshell]\nversion = 2\n\n\
[openshell.gateway]\n\
name = \"{name}\"\n\
compute_driver = \"apple-container\"\n\
bind_address = \"{bind}\"\n\
log_level = \"debug,openshell_driver_apple_container=trace\"\n\
guest_tls_ca = \"{tls}/ca.crt\"\n\
guest_tls_cert = \"{tls}/client/tls.crt\"\n\
guest_tls_key = \"{tls}/client/tls.key\"\n\n\
[openshell.gateway.auth]\n\
allow_unauthenticated_users = true\n\n\
[openshell.gateway.tls]\n\
cert_path = \"{tls}/server/tls.crt\"\n\
key_path = \"{tls}/server/tls.key\"\n\
client_ca_path = \"{tls}/ca.crt\"\n\n\
[openshell.gateway.gateway_jwt]\n\
signing_key_path = \"{tls}/jwt/signing.pem\"\n\
public_key_path = \"{tls}/jwt/public.pem\"\n\
kid_path = \"{tls}/jwt/kid\"\n\n\
[openshell.drivers.apple-container]\n\
default_image = \"{image}\"\n\
supervisor_bin_dir = \"{supervisor}\"\n",
        name = crate::config::GATEWAY_NAME,
        bind = crate::config::GATEWAY_BIND,
        tls = tls.display(),
        image = crate::config::SANDBOX_IMAGE,
        supervisor = crate::config::driver_supervisor_bin().display(),
    );

    let toml_path = crate::config::gateway_toml();
    if let Some(parent) = toml_path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    fs::write(&toml_path, toml).unwrap();
}
