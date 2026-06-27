use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub server_url: String,
    pub api_key: String,
    // Set true once the user has explicitly completed setup. Defaults false so a
    // fresh install shows the config screen instead of silently pointing at
    // localhost with no key.
    #[serde(default)]
    pub configured: bool,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            server_url: "http://localhost:8000".into(),
            api_key: String::new(),
            configured: false,
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
        Ok(())
    }

    pub fn is_configured(&self) -> bool {
        self.configured && !self.server_url.is_empty()
    }
}
