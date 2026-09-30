// config.rs — All constants, paths, and env-var resolution.
//
// This module has NO dependencies on other trybox modules.
// It is the foundation that all other modules build on.

use std::path::PathBuf;

pub const VERSION: &str = "0.2.0";

pub const DB_URL: &str = "sqlite:////tmp/trybox-test.db";
pub const GATEWAY_BIND: &str = "127.0.0.1:17671";
pub const GATEWAY_PORT: u16 = 17671;
pub const GATEWAY_NAME: &str = "trybox-test";
pub const SANDBOX_IMAGE: &str = "local/trybox-sandbox:latest";

/// The hardcoded dev release fallback path for _which():
/// ~/code/tries/2026-09-29-trybox/OpenShell-upstream/target/release/
pub const DEV_RELEASE_SUBDIR: &str =
    "code/tries/2026-09-29-trybox/OpenShell-upstream/target/release";

// --- Path functions ---
// All mirror the Python constants exactly.

pub fn home() -> PathBuf {
    dirs::home_dir().unwrap_or_else(|| PathBuf::from("/"))
}

pub fn share_dir() -> PathBuf {
    home().join(".local").join("share").join("trybox")
}

pub fn state_dir() -> PathBuf {
    home().join(".local").join("state").join("trybox")
}

pub fn tls_dir() -> PathBuf {
    share_dir().join("tls")
}

pub fn ca_crt() -> PathBuf {
    tls_dir().join("ca.crt")
}

pub fn ca_key() -> PathBuf {
    tls_dir().join("ca.key")
}

pub fn server_dir() -> PathBuf {
    tls_dir().join("server")
}

pub fn server_crt() -> PathBuf {
    server_dir().join("tls.crt")
}

pub fn server_key() -> PathBuf {
    server_dir().join("tls.key")
}

pub fn client_dir() -> PathBuf {
    tls_dir().join("client")
}

pub fn client_crt() -> PathBuf {
    client_dir().join("tls.crt")
}

pub fn client_key() -> PathBuf {
    client_dir().join("tls.key")
}

pub fn jwt_dir() -> PathBuf {
    tls_dir().join("jwt")
}

pub fn jwt_signing() -> PathBuf {
    jwt_dir().join("signing.pem")
}

pub fn jwt_public() -> PathBuf {
    jwt_dir().join("public.pem")
}

pub fn jwt_kid() -> PathBuf {
    jwt_dir().join("kid")
}

pub fn gateway_toml() -> PathBuf {
    share_dir().join("gateway.toml")
}

pub fn gateway_pidfile() -> PathBuf {
    state_dir().join("gateway.pid")
}

pub fn gateway_log() -> PathBuf {
    state_dir().join("gateway.log")
}

pub fn driver_sock() -> PathBuf {
    state_dir().join("driver.sock")
}

pub fn driver_pidfile() -> PathBuf {
    state_dir().join("driver.pid")
}

pub fn driver_log() -> PathBuf {
    state_dir().join("driver.log")
}

pub fn driver_supervisor_bin() -> PathBuf {
    share_dir().join("supervisor-bin")
}

/// Default try path root: env TRY_PATH or ~/code/tries
pub fn default_try_path() -> PathBuf {
    match std::env::var("TRY_PATH") {
        Ok(v) => PathBuf::from(v),
        Err(_) => home().join("code").join("tries"),
    }
}

/// GATEWAY_ENDPOINT constant (corrected)
pub fn gateway_endpoint() -> String {
    format!("https://127.0.0.1:{}", GATEWAY_PORT)
}
