use std::time::Duration;

use anyhow::Result;
use reqwest::Client;

use crate::api::sse::{parse_sse_stream, SseStream};
use crate::api::types::*;

// Per-request timeout for the short JSON endpoints. NOT applied to the SSE
// streams, where a whole-request timeout would abort a long-running build/chat.
const REQUEST_TIMEOUT: Duration = Duration::from_secs(20);

#[derive(Clone)]
pub struct ApiClient {
    client: Client,
    base_url: String,
    api_key: String,
}

impl ApiClient {
    pub fn new(base_url: String, api_key: String) -> Self {
        // connect_timeout bounds connection establishment without capping the body
        // read, so an unreachable backend fails fast while SSE streams stay open.
        let client = Client::builder()
            .connect_timeout(Duration::from_secs(10))
            .build()
            .unwrap_or_default();
        Self {
            client,
            base_url,
            api_key,
        }
    }

    fn auth(&self, rb: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
        if self.api_key.is_empty() {
            rb
        } else {
            rb.header("Authorization", format!("Bearer {}", self.api_key))
        }
    }

    pub async fn list_experts(&self) -> Result<Vec<ExpertSummary>> {
        let resp = self.auth(self.client.get(format!("{}/experts", self.base_url)))
            .timeout(REQUEST_TIMEOUT)
            .send().await?
            .error_for_status()?
            .json().await?;
        Ok(resp)
    }

    pub async fn get_expert(&self, slug: &str) -> Result<ExpertDetail> {
        let resp = self.auth(self.client.get(format!("{}/experts/{}", self.base_url, slug)))
            .timeout(REQUEST_TIMEOUT)
            .send().await?
            .error_for_status()?
            .json().await?;
        Ok(resp)
    }

    pub async fn delete_expert(&self, slug: &str) -> Result<()> {
        self.auth(self.client.delete(format!("{}/experts/{}", self.base_url, slug)))
            .timeout(REQUEST_TIMEOUT)
            .send().await?
            .error_for_status()?;
        Ok(())
    }

    pub async fn build_stream(&self, topic: String, tier: String) -> Result<SseStream<BuildEvent>> {
        let req = BuildRequest { topic, tier };
        let resp = self.auth(self.client.post(format!("{}/experts/build", self.base_url)))
            .json(&req)
            .send().await?
            .error_for_status()?;
        Ok(parse_sse_stream(resp.bytes_stream()))
    }

    pub async fn chat_stream(&self, slug: &str, req: ChatRequest) -> Result<SseStream<ChatEvent>> {
        let resp = self.auth(self.client.post(format!("{}/experts/{}/chat", self.base_url, slug)))
            .json(&req)
            .send().await?
            .error_for_status()?;
        Ok(parse_sse_stream(resp.bytes_stream()))
    }
}
