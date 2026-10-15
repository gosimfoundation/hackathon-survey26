//! OpenAI-compatible chat client for the optional model stage. Port of `python-pro/llm_client.py`.
//!
//! Configuration (environment, or a local `.env` in the working directory that is never packed):
//!
//! ```text
//! OPENAI_API_KEY    required for the model stage (KIMI_API_KEY is accepted as an alternate name)
//! OPENAI_BASE_URL   default https://api.kimi.com/coding/v1 (Kimi Coding Plan; outside mainland China
//!                   use https://api.kimi.ai/coding/v1). On the platform this is injected automatically.
//! OPENAI_MODEL      default k3
//! ```
//!
//! The only caller is `log_reader.rs`, which runs every request on a background thread, so the decision loop
//! never waits for the network. k3 only accepts the default temperature, so none is sent.

use serde_json::{json, Map, Value};
use std::time::Duration;

const DEFAULT_BASE_URL: &str = "https://api.kimi.com/coding/v1";
const DEFAULT_MODEL: &str = "k3";

fn env_trim(name: &str) -> String {
    std::env::var(name).map(|v| v.trim().to_string()).unwrap_or_default()
}

/// OBSERVER_MODEL_DISABLED=1: the platform runs this evaluation without a model. No call is made.
pub fn model_disabled() -> bool {
    std::env::var("OBSERVER_MODEL_DISABLED").map(|v| v == "1").unwrap_or(false)
}

pub fn api_key() -> String {
    let key = env_trim("OPENAI_API_KEY");
    if key.is_empty() {
        env_trim("KIMI_API_KEY")
    } else {
        key
    }
}

/// Fill missing environment variables from a local .env (for local runs only).
pub fn load_dotenv(path: &std::path::Path) {
    let Ok(text) = std::fs::read_to_string(path) else { return };
    for line in text.lines() {
        let line = line.trim();
        let Some((name, value)) = line.split_once('=') else { continue };
        if line.starts_with('#') {
            continue;
        }
        let name = name.trim();
        let value = value.trim().trim_matches('"').trim_matches('\'');
        if !name.is_empty() && !value.is_empty() && env_trim(name).is_empty() {
            std::env::set_var(name, value);
        }
    }
}

/// A failed request: the HTTP status (0 when there was none: network error, unreadable reply) and what went wrong.
pub struct Failure {
    pub status: u16,
    pub message: String,
}

impl Failure {
    fn new(status: u16, message: impl Into<String>) -> Failure {
        Failure { status, message: message.into() }
    }
}

/// Endpoint, key and model; cheap to clone into a background thread.
#[derive(Clone)]
pub struct LlmClient {
    base_url: String,
    key: String,
    pub model: String,
}

impl LlmClient {
    pub fn from_env() -> LlmClient {
        let base = env_trim("OPENAI_BASE_URL");
        let model = env_trim("OPENAI_MODEL");
        LlmClient {
            base_url: if base.is_empty() { DEFAULT_BASE_URL.into() } else { base.trim_end_matches('/').into() },
            key: api_key(),
            model: if model.is_empty() { DEFAULT_MODEL.into() } else { model },
        }
    }

    /// One blocking chat completion; returns the JSON object found in the reply.
    pub fn request(&self, system: &str, user: &Value, timeout: f64, max_tokens: u32) -> Result<Map<String, Value>, Failure> {
        let body = json!({
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": serde_json::to_string(user).unwrap_or_default()}],
            "max_tokens": max_tokens,
        });
        let agent = ureq::AgentBuilder::new().timeout(Duration::from_secs_f64(timeout.max(1.0))).build();
        let response = agent
            .post(&format!("{}/chat/completions", self.base_url))
            .set("Content-Type", "application/json")
            .set("Authorization", &format!("Bearer {}", self.key)) // never log the key
            .send_json(body);
        let data: Value = match response {
            Ok(r) => r.into_json().map_err(|e| Failure::new(0, format!("read: {}", e.kind())))?,
            Err(ureq::Error::Status(code, _)) => return Err(Failure::new(code, format!("HTTP {code}"))),
            Err(ureq::Error::Transport(t)) => return Err(Failure::new(0, format!("transport: {}", t.kind()))),
        };
        let text = data["choices"][0]["message"]["content"].as_str().unwrap_or("");
        // the first '{' to the last '}' (the reply may wrap the object in prose or a code fence)
        let object = match (text.find('{'), text.rfind('}')) {
            (Some(a), Some(b)) if a < b => &text[a..=b],
            _ => return Err(Failure::new(0, "no JSON object in the reply")),
        };
        match serde_json::from_str::<Value>(object) {
            Ok(Value::Object(map)) => Ok(map),
            _ => Err(Failure::new(0, "reply is not a JSON object")),
        }
    }
}
