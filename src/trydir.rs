// trydir.rs — Try dir discovery/creation, slugify, Trybox struct.
//
// Depends on: config.rs

use std::fs;
use std::path::{Path, PathBuf};

use regex::Regex;

/// One trybox instance.
pub struct Trybox {
    /// slug, e.g. "my-big-new-project"
    #[allow(dead_code)]
    pub name: String,
    /// ~/code/tries/2026-09-29-my-big-new-project
    pub dir: PathBuf,
    /// trybox-my-big-new-project
    pub sandbox_name: String,
    /// YYYY-MM-DD
    #[allow(dead_code)]
    pub date_prefix: String,
}

/// Mirror try's behavior: whitespace -> '-'.
pub fn slugify(text: &str) -> String {
    let re = Regex::new(r"\s+").unwrap();
    re.replace_all(text.trim(), "-").to_lowercase()
}

/// Return today's date as YYYY-MM-DD.
/// Uses the `date` command to avoid pulling in chrono/time crates.
pub fn today() -> String {
    let output = std::process::Command::new("date").arg("+%Y-%m-%d").output();
    match output {
        Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).trim().to_string(),
        _ => {
            // Fallback: use system time (less precise but always available)
            use std::time::{SystemTime, UNIX_EPOCH};
            let secs = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_secs();
            // Very rough date calculation — should rarely be hit
            let days = secs / 86400;
            let year = 1970 + (days / 365) as i32;
            format!("{}-01-01", year) // crude fallback
        }
    }
}

/// Locate an existing trybox by slug (any date prefix).
pub fn find_trybox(name: &str, base: &Path) -> Option<Trybox> {
    if name.is_empty() || !base.exists() {
        return None;
    }

    let re_date = Regex::new(r"^\d{4}-\d{2}-\d{2}$").unwrap();

    let mut entries: Vec<_> = fs::read_dir(base).ok()?.collect::<Result<_, _>>().ok()?;
    // Reverse sort by name (mirrors sorted(base.iterdir(), reverse=True))
    entries.sort_by(|a, b| b.file_name().cmp(&a.file_name()));

    for entry in entries {
        if !entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
            continue;
        }
        let entry_name = entry.file_name();
        let entry_name = entry_name.to_string_lossy();
        let suffix = format!("-{}", name);
        if entry_name.ends_with(&suffix) {
            let parts: Vec<&str> = entry_name.splitn(4, '-').collect();
            if parts.len() >= 4 {
                let date_prefix = format!("{}-{}-{}", parts[0], parts[1], parts[2]);
                if re_date.is_match(&date_prefix) {
                    return Some(Trybox {
                        name: name.to_string(),
                        dir: entry.path(),
                        sandbox_name: format!("trybox-{}", name),
                        date_prefix,
                    });
                }
            }
        }
    }
    None
}

/// Create a fresh dated try dir (try's exact layout).
pub fn create_try_dir(name: &str, base: &Path) -> Trybox {
    let date_prefix = today();
    let dirname = format!("{}-{}", date_prefix, name);
    let target = base.join(&dirname);

    // Mirror try's uniqueness: if exists, append -2, -3, ...
    let target = if target.exists() {
        let mut n = 2;
        loop {
            let candidate = base.join(format!("{}-{}", dirname, n));
            if !candidate.exists() {
                break candidate;
            }
            n += 1;
        }
    } else {
        target
    };

    fs::create_dir_all(&target).unwrap();

    // Create .git directory
    let git_dir = target.join(".git");
    let _ = fs::create_dir(&git_dir);

    // git init -q
    let _ = std::process::Command::new("git")
        .arg("-C")
        .arg(&target)
        .arg("init")
        .arg("-q")
        .output();

    Trybox {
        name: name.to_string(),
        dir: target,
        sandbox_name: format!("trybox-{}", name),
        date_prefix,
    }
}
