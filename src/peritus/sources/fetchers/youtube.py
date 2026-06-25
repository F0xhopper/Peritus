from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceType

logger = get_logger(__name__)


class YoutubeFetcher:
    async def fetch(self, topic: str, max_results: int = 5) -> list[RawSource]:
        if not settings.EXA_API_KEY:
            logger.warning("EXA_API_KEY not set — skipping YouTube fetcher")
            return []

        video_ids = await _discover_video_ids(topic, max_results)
        sources = []
        for vid_id, title in video_ids:
            try:
                transcript = _fetch_transcript(vid_id)
                if not transcript:
                    continue
                sources.append(RawSource(
                    source_type=SourceType.YOUTUBE,
                    url=f"https://www.youtube.com/watch?v={vid_id}",
                    title=title,
                    author=None,
                    text=transcript,
                    metadata={"video_id": vid_id},
                ))
            except Exception as exc:
                logger.warning("YouTube transcript failed for %r: %s", vid_id, exc)
        return sources


async def _discover_video_ids(topic: str, limit: int) -> list[tuple[str, str]]:
    """Use Exa to find YouTube video URLs for the topic."""
    try:
        from exa_py import Exa  # type: ignore
        client = Exa(api_key=settings.EXA_API_KEY)
        results = client.search(
            f"{topic} site:youtube.com",
            num_results=limit,
            type="neural",
        )
        pairs = []
        for r in results.results:
            url = r.url or ""
            if "youtube.com/watch?v=" in url:
                vid_id = url.split("v=")[1].split("&")[0]
                pairs.append((vid_id, r.title or url))
        return pairs
    except Exception as exc:
        logger.warning("YouTube discovery via Exa failed: %s", exc)
        return []


def _fetch_transcript(video_id: str) -> str:
    api = YouTubeTranscriptApi()
    fetched = api.fetch(video_id)
    return " ".join(entry.text for entry in fetched)
