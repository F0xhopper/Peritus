import asyncio
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceCandidate, SourceType

logger = get_logger(__name__)


class YoutubeFetcher:
    async def search(self, query: str, max_results: int = 5) -> list[SourceCandidate]:
        if not settings.EXA_API_KEY:
            logger.warning("EXA_API_KEY not set — skipping YouTube fetcher")
            return []

        try:
            from exa_py import Exa  # type: ignore
            client = Exa(api_key=settings.EXA_API_KEY)
            results = await asyncio.to_thread(
                client.search,
                f"{query} site:youtube.com",
                num_results=max_results,
                type="neural",
            )
        except Exception as exc:
            logger.warning("YouTube discovery via Exa failed: %s", exc)
            return []

        candidates = []
        for r in results.results:
            url = r.url or ""
            vid_id = _extract_video_id(url)
            if not vid_id:
                continue
            title = r.title or url
            candidates.append(SourceCandidate(
                source_type=SourceType.YOUTUBE,
                url=f"https://www.youtube.com/watch?v={vid_id}",
                title=title,
                author=None,
                snippet=title,
                metadata={"video_id": vid_id},
            ))
        return candidates

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        vid_id = candidate.metadata["video_id"]
        try:
            transcript = await asyncio.to_thread(_fetch_transcript, vid_id)
        except Exception as exc:
            logger.warning("YouTube transcript failed for %r: %s", vid_id, exc)
            return None
        if not transcript or len(transcript) < 500:
            return None
        return RawSource(
            source_type=SourceType.YOUTUBE,
            url=candidate.url,
            title=candidate.title,
            author=None,
            text=transcript,
            metadata=candidate.metadata,
        )


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from any supported URL format."""
    try:
        parsed = urlparse(url)
        if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
            vid_id = parse_qs(parsed.query).get("v", [None])[0]
            return vid_id
        if parsed.hostname in ("youtu.be",):
            return parsed.path.lstrip("/") or None
    except Exception:
        pass
    return None


def _fetch_transcript(video_id: str) -> str:
    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
    except Exception:
        fetched = api.fetch(video_id)
    return " ".join(entry.text for entry in fetched)
