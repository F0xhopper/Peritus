use std::time::Duration;

use anyhow::Result;
use reqwest::Client;
use serde::de::DeserializeOwned;

use crate::api::sse::{parse_sse_stream, parse_sse_stream_with_seq, SeqStream, SseStream};
use crate::api::types::*;

/// Slugify a topic the same way the server does (`experts.py::_slugify`) so the
/// client can address the build's reconnect endpoint by slug.
pub fn slugify(topic: &str) -> String {
    let mut out = String::new();
    let mut prev_dash = false;
    for ch in topic.to_lowercase().chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch);
            prev_dash = false;
        } else if !prev_dash {
            out.push('-');
            prev_dash = true;
        }
    }
    out.trim_matches('-').chars().take(80).collect()
}

// Per-request timeout for the short JSON endpoints. NOT applied to the SSE
// streams, where a whole-request timeout would abort a long-running build/chat.
const REQUEST_TIMEOUT: Duration = Duration::from_secs(20);

#[derive(Clone)]
pub struct ApiClient {
    client: Client,
    base_url: String,
    // Bearer credential: a Supabase access token, or the legacy static key.
    token: String,
}

impl ApiClient {
    pub fn new(base_url: String, token: String) -> Self {
        // connect_timeout bounds connection establishment without capping the body
        // read, so an unreachable backend fails fast while SSE streams stay open.
        let client = Client::builder()
            .connect_timeout(Duration::from_secs(10))
            .build()
            .unwrap_or_default();
        Self {
            client,
            base_url,
            token,
        }
    }

    fn auth(&self, rb: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
        if self.token.is_empty() {
            rb
        } else {
            rb.header("Authorization", format!("Bearer {}", self.token))
        }
    }

    pub async fn list_experts(&self) -> Result<Vec<ExpertSummary>> {
        let resp = self.auth(self.client.get(format!("{}/experts", self.base_url)))
            .timeout(REQUEST_TIMEOUT)
            .send().await?;
        json_or_err(resp).await
    }

    pub async fn delete_expert(&self, slug: &str) -> Result<()> {
        let resp = self.auth(self.client.delete(format!("{}/experts/{}", self.base_url, slug)))
            .timeout(REQUEST_TIMEOUT)
            .send().await?;
        expect_success(resp).await
    }

    /// Start a build and stream its progress. Events carry their durable `seq` so a
    /// dropped connection can be resumed via [`build_events_stream`].
    /// `tier: None` lets the server resolve the deepest tier the account affords.
    pub async fn build_stream(
        &self, topic: String, tier: Option<String>,
    ) -> Result<SeqStream<BuildEvent>> {
        let req = BuildRequest { topic, tier };
        let resp = self.auth(self.client.post(format!("{}/experts/build", self.base_url)))
            .json(&req)
            .send().await?;
        let resp = stream_or_err(resp).await?;
        Ok(parse_sse_stream_with_seq(resp.bytes_stream()))
    }

    /// Reconnect to an in-flight (or finished) build's durable event log, resuming
    /// after the last `seq` already seen. Used to survive dropped connections.
    pub async fn build_events_stream(&self, slug: &str, after: u64) -> Result<SeqStream<BuildEvent>> {
        let resp = self.auth(self.client.get(
            format!("{}/experts/{}/build/events?after={}", self.base_url, slug, after)))
            .send().await?;
        let resp = stream_or_err(resp).await?;
        Ok(parse_sse_stream_with_seq(resp.bytes_stream()))
    }

    /// Cancel the active build for an expert. The terminal 'cancelled' event
    /// arrives via the event stream, so callers only need to fire this.
    pub async fn cancel_build(&self, slug: &str) -> Result<()> {
        let resp = self.auth(self.client.post(format!("{}/experts/{}/build/cancel", self.base_url, slug)))
            .timeout(REQUEST_TIMEOUT)
            .send().await?;
        expect_success(resp).await
    }

    pub async fn chat_stream(&self, slug: &str, req: ChatRequest) -> Result<SseStream<ChatEvent>> {
        let resp = self.auth(self.client.post(format!("{}/experts/{}/chat", self.base_url, slug)))
            .json(&req)
            .send().await?;
        let resp = stream_or_err(resp).await?;
        Ok(parse_sse_stream(resp.bytes_stream()))
    }

    // ── Auth (public backend-for-frontend endpoints) ─────────────────────────

    pub async fn otp_request(&self, email: &str) -> Result<()> {
        let resp = self.client.post(format!("{}/auth/otp", self.base_url))
            .json(&OtpRequestBody { email: email.to_string() })
            .timeout(REQUEST_TIMEOUT)
            .send().await?;
        expect_success(resp).await
    }

    pub async fn otp_verify(&self, email: &str, code: &str) -> Result<Session> {
        let resp = self.client.post(format!("{}/auth/verify", self.base_url))
            .json(&VerifyBody { email: email.to_string(), token: code.to_string() })
            .timeout(REQUEST_TIMEOUT)
            .send().await?;
        json_or_err(resp).await
    }

    pub async fn refresh(&self, refresh_token: &str) -> Result<Session> {
        let resp = self.client.post(format!("{}/auth/refresh", self.base_url))
            .json(&RefreshBody { refresh_token: refresh_token.to_string() })
            .timeout(REQUEST_TIMEOUT)
            .send().await?;
        json_or_err(resp).await
    }

    /// Revoke the current session server-side. Best-effort: the caller clears the
    /// local session regardless, so a network error here is not fatal.
    pub async fn logout(&self) -> Result<()> {
        let resp = self.auth(self.client.post(format!("{}/auth/logout", self.base_url)))
            .timeout(REQUEST_TIMEOUT)
            .send().await?;
        expect_success(resp).await
    }
}

/// True when an error came from an HTTP 401 (token missing/invalid/expired).
pub fn is_unauthorized(err: &anyhow::Error) -> bool {
    if let Some(re) = err.downcast_ref::<reqwest::Error>() {
        return re.status() == Some(reqwest::StatusCode::UNAUTHORIZED);
    }
    err.downcast_ref::<ApiError>()
        .map(|e| e.status == 401)
        .unwrap_or(false)
}

#[derive(Debug)]
struct ApiError {
    status: u16,
    detail: String,
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.detail)
    }
}

impl std::error::Error for ApiError {}

async fn json_or_err<T: DeserializeOwned>(resp: reqwest::Response) -> Result<T> {
    let status = resp.status();
    if status.is_success() {
        Ok(resp.json().await?)
    } else {
        Err(error_from(resp, status).await.into())
    }
}

async fn expect_success(resp: reqwest::Response) -> Result<()> {
    let status = resp.status();
    if status.is_success() {
        Ok(())
    } else {
        Err(error_from(resp, status).await.into())
    }
}

/// Pass a streaming response through, or read its body and surface the server's
/// error detail. `.error_for_status()` alone would throw the JSON body away —
/// which is exactly where the server puts the message worth showing (a 402's
/// credit shortfall, a 409's "expert is still building", a 429's retry advice).
async fn stream_or_err(resp: reqwest::Response) -> Result<reqwest::Response> {
    let status = resp.status();
    if status.is_success() {
        Ok(resp)
    } else {
        Err(error_from(resp, status).await.into())
    }
}

async fn error_from(resp: reqwest::Response, status: reqwest::StatusCode) -> ApiError {
    let body = resp.text().await.unwrap_or_default();
    // FastAPI errors are {"detail": ...} where detail is either a plain string
    // or a structured object ({"code", "message", "remedy", ...} — the
    // entitlement denials). Prefer the human-readable message either way; fall
    // back to the raw body/status.
    let detail = serde_json::from_str::<serde_json::Value>(&body)
        .ok()
        .and_then(|v| {
            let d = v.get("detail")?;
            if let Some(s) = d.as_str() {
                return Some(s.to_string());
            }
            let msg = d.get("message").and_then(|m| m.as_str())?;
            let remedy = d
                .get("remedy")
                .and_then(|r| r.get("label"))
                .and_then(|l| l.as_str());
            Some(match remedy {
                Some(label) => format!("{} ({})", msg, label),
                None => msg.to_string(),
            })
        })
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| {
            if body.is_empty() { status.to_string() } else { body }
        });
    ApiError { status: status.as_u16(), detail }
}
