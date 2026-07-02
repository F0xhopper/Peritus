use anyhow::Result;
use bytes::Bytes;
use futures_util::Stream;
use serde::de::DeserializeOwned;
use std::pin::Pin;

pub type SseStream<T> = Pin<Box<dyn Stream<Item = Result<T>> + Send>>;

/// An SSE event together with its `id:` cursor (used to resume a build after a
/// dropped connection).
pub struct SeqEvent<T> {
    pub seq: Option<u64>,
    pub event: T,
}

pub type SeqStream<T> = Pin<Box<dyn Stream<Item = Result<SeqEvent<T>>> + Send>>;

/// Like [`parse_sse_stream`] but also surfaces each event's `id:` field so the
/// caller can track the last durable `build_events.seq` it has seen.
pub fn parse_sse_stream_with_seq<T: DeserializeOwned + Send + 'static>(
    byte_stream: impl Stream<Item = reqwest::Result<Bytes>> + Send + 'static,
) -> SeqStream<T> {
    use futures_util::StreamExt;
    let stream = async_stream::stream! {
        // Buffer raw bytes and split on b'\n' so a multi-byte UTF-8 character
        // spanning a network-chunk boundary is never mangled — '\n' is a single
        // byte and cannot appear inside a multi-byte sequence.
        let mut buf: Vec<u8> = Vec::new();
        let mut current_id: Option<u64> = None;
        tokio::pin!(byte_stream);
        while let Some(chunk) = byte_stream.next().await {
            match chunk {
                Err(e) => { yield Err(anyhow::anyhow!("Stream error: {}", e)); break; }
                Ok(bytes) => {
                    buf.extend_from_slice(&bytes);
                    while let Some(pos) = buf.iter().position(|&b| b == b'\n') {
                        let line_bytes: Vec<u8> = buf.drain(..=pos).collect();
                        let line_cow = String::from_utf8_lossy(&line_bytes);
                        let line = line_cow.trim();
                        if let Some(id) = line.strip_prefix("id:") {
                            current_id = id.trim().parse::<u64>().ok();
                        } else if let Some(data) = line.strip_prefix("data: ") {
                            match serde_json::from_str::<T>(data) {
                                Ok(event) => yield Ok(SeqEvent { seq: current_id, event }),
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

pub fn parse_sse_stream<T: DeserializeOwned + Send + 'static>(
    byte_stream: impl Stream<Item = reqwest::Result<Bytes>> + Send + 'static,
) -> SseStream<T> {
    use futures_util::StreamExt;
    let seq_stream = parse_sse_stream_with_seq::<T>(byte_stream);
    let stream = async_stream::stream! {
        tokio::pin!(seq_stream);
        while let Some(item) = seq_stream.next().await {
            yield item.map(|se| se.event);
        }
    };
    Box::pin(stream)
}
