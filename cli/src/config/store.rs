use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub server_url: String,
    // Legacy static API key. Superseded by Supabase login (access_token) but kept
    // so existing single-key deployments keep working.
    #[serde(default)]
    pub api_key: String,
    // Set true once the user has explicitly completed setup. Defaults false so a
    // fresh install shows the config screen instead of silently pointing at
    // localhost with no key.
    #[serde(default)]
    pub configured: bool,

    // ── Supabase session (populated by login) ────────────────────────────────
    #[serde(default)]
    pub access_token: String,
    #[serde(default)]
    pub refresh_token: String,
    // Unix seconds at which the access token expires.
    #[serde(default)]
    pub expires_at: i64,
    // The signed-in user's email, shown in the UI.
    #[serde(default)]
    pub email: String,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            server_url: "http://localhost:8000".into(),
            api_key: String::new(),
            configured: false,
            access_token: String::new(),
            refresh_token: String::new(),
            expires_at: 0,
            email: String::new(),
        }
    }
}

impl Config {
    pub fn config_path() -> PathBuf {
        dirs::config_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("peritus")
            .join("config.toml")
    }

    pub fn load() -> Self {
        let path = Self::config_path();
        if let Ok(s) = std::fs::read_to_string(&path) {
            toml::from_str(&s).unwrap_or_default()
        } else {
            Self::default()
        }
    }

    pub fn save(&self) -> Result<()> {
        let path = Self::config_path();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&path, toml::to_string_pretty(self)?)?;
        // The refresh token is a long-lived credential — keep the file owner-only.
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600));
        }
        Ok(())
    }

    pub fn is_configured(&self) -> bool {
        self.configured && !self.server_url.is_empty()
    }

    /// The credential to send as `Authorization: Bearer`. Prefers a live Supabase
    /// session, falling back to the legacy static key.
    pub fn bearer(&self) -> String {
        if !self.access_token.is_empty() {
            self.access_token.clone()
        } else {
            self.api_key.clone()
        }
    }

    pub fn has_session(&self) -> bool {
        !self.refresh_token.is_empty()
    }

    /// True when the access token is missing or expires within `skew_secs`.
    pub fn access_expiring(&self, skew_secs: i64) -> bool {
        if self.access_token.is_empty() {
            return true;
        }
        now_unix() + skew_secs >= self.expires_at
    }

    pub fn set_session(
        &mut self,
        access_token: String,
        refresh_token: String,
        expires_at: i64,
        email: String,
    ) {
        self.access_token = access_token;
        self.refresh_token = refresh_token;
        self.expires_at = expires_at;
        if !email.is_empty() {
            self.email = email;
        }
    }

    pub fn clear_session(&mut self) {
        self.access_token.clear();
        self.refresh_token.clear();
        self.expires_at = 0;
        self.email.clear();
    }
}

pub fn now_unix() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}
