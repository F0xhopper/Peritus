use anyhow::Result;
use bytes::Bytes;
use futures_util::Stream;
use serde::de::DeserializeOwned;
use std::pin::Pin;

pub type SseStream<T> = Pin<Box<dyn Stream<Item = Result<T>> + Send>>;

pub fn parse_sse_stream<T: DeserializeOwned + Send + 'static>(
    byte_stream: impl Stream<Item = reqwest::Result<Bytes>> + Send + 'static,
) -> SseStream<T> {
    use futures_util::StreamExt;
    let stream = async_stream::stream! {
        let mut buf = String::new();
        tokio::pin!(byte_stream);
        while let Some(chunk) = byte_stream.next().await {
            match chunk {
                Err(e) => { yield Err(anyhow::anyhow!("Stream error: {}", e)); break; }
                Ok(bytes) => {
                    buf.push_str(&String::from_utf8_lossy(&bytes));
                    while let Some(pos) = buf.find('\n') {
                        let line = buf[..pos].trim().to_string();
                        buf.drain(..=pos);
                        if let Some(data) = line.strip_prefix("data: ") {
                            match serde_json::from_str::<T>(data) {
                                Ok(event) => yield Ok(event),
                                Err(e) => tracing::warn!("SSE parse error: {} for: {}", e, data),
                            }
                        }
                    }
                }
            }
        }
    };
    Box::pin(stream)
}
