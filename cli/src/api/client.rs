use anyhow::Result;
use reqwest::Client;

use crate::api::sse::{parse_sse_stream, SseStream};
use crate::api::types::*;

#[derive(Clone)]
pub struct ApiClient {
    client: Client,
    base_url: String,
    api_key: String,
}

impl ApiClient {
    pub fn new(base_url: String, api_key: String) -> Self {
        Self {
            client: Client::new(),
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
            .send().await?
            .error_for_status()?
            .json().await?;
        Ok(resp)
    }

    pub async fn get_expert(&self, slug: &str) -> Result<ExpertDetail> {
        let resp = self.auth(self.client.get(format!("{}/experts/{}", self.base_url, slug)))
            .send().await?
            .error_for_status()?
            .json().await?;
        Ok(resp)
    }

    pub async fn delete_expert(&self, slug: &str) -> Result<()> {
        self.auth(self.client.delete(format!("{}/experts/{}", self.base_url, slug)))
            .send().await?
            .error_for_status()?;
        Ok(())
    }

    pub async fn build_stream(&self, topic: String) -> Result<SseStream<BuildEvent>> {
        let req = BuildRequest { topic, depth: "normal".into() };
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
