// process.rs — Process management: pidfiles, liveness checks, daemon spawn.
//
// Depends on: config.rs
//
// Mirrors Python's _pid_running, _read_pidfile, driver_running, gateway_running,
// and the daemon spawn behavior (subprocess.Popen with start_new_session=True).

use std::fs;
use std::io;
use std::path::Path;

use nix::sys::signal::{kill, Signal};
use nix::unistd::Pid;

/// Check if a process is alive (kill -0).
pub fn pid_running(pid: i32) -> bool {
    kill(Pid::from_raw(pid), None).is_ok()
}

/// Read a pidfile and check if the process is alive.
/// Returns None if the file doesn't exist, can't be parsed, or process is dead.
pub fn read_pidfile(pidfile: &Path) -> Option<i32> {
    if !pidfile.exists() {
        return None;
    }
    let content = fs::read_to_string(pidfile).ok()?;
    let pid: i32 = content.trim().parse().ok()?;
    if pid_running(pid) {
        Some(pid)
    } else {
        None
    }
}

/// Check if the driver is running. Returns the PID if so.
pub fn driver_running() -> Option<i32> {
    read_pidfile(&crate::config::driver_pidfile())
}

/// Check if the gateway is running. Returns the PID if so.
pub fn gateway_running() -> Option<i32> {
    read_pidfile(&crate::config::gateway_pidfile())
}

/// Send SIGTERM to a process.
pub fn kill_process(pid: i32) {
    let _ = kill(Pid::from_raw(pid), Signal::SIGTERM);
}

/// Spawn a daemon process, mirroring Python's:
///   subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
///
/// start_new_session=True calls setsid() in the child, detaching it from the
/// controlling terminal. We replicate this with pre_exec().
pub fn spawn_daemon(cmd: &[String], log_path: &Path, pidfile: &Path) -> io::Result<u32> {
    if cmd.is_empty() {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "empty command"));
    }

    let log_file = fs::OpenOptions::new()
        .append(true)
        .create(true)
        .open(log_path)?;

    // On Unix, merge stderr into stdout (stderr=subprocess.STDOUT) by using
    // the same file handle for both, and call setsid() in pre_exec.
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;

        let stderr_file = log_file.try_clone()?;
        let mut command = std::process::Command::new(&cmd[0]);
        unsafe {
            command
                .args(&cmd[1..])
                .stdout(std::process::Stdio::from(log_file))
                .stderr(std::process::Stdio::from(stderr_file))
                .pre_exec(|| {
                    libc::setsid();
                    Ok(())
                });
        }

        let child = command.spawn()?;
        let pid = child.id();
        fs::write(pidfile, pid.to_string())?;
        Ok(pid)
    }

    #[cfg(not(unix))]
    {
        let stderr_file = log_file.try_clone()?;
        let mut command = std::process::Command::new(&cmd[0]);
        command
            .args(&cmd[1..])
            .stdout(std::process::Stdio::from(log_file))
            .stderr(std::process::Stdio::from(stderr_file));
        let child = command.spawn()?;
        let pid = child.id();
        fs::write(pidfile, pid.to_string())?;
        Ok(pid)
    }
}

/// Remove a pidfile, ignoring "file not found" errors (mirrors Python's
/// `try: pidfile.unlink() except FileNotFoundError: pass`).
pub fn unlink_pidfile(pidfile: &Path) {
    let _ = fs::remove_file(pidfile);
}
