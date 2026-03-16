from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import arxiv
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound

from core.exceptions import SourceIngestionError
from core.logger import get_logger
from domain.entities import SourceDocument

logger = get_logger(__name__)


async def fetch_arxiv_papers(topic: str, max_results: int = 5) -> list[SourceDocument]:
    logger.info("arxiv_search", topic=topic)
    try:
        loop = asyncio.get_event_loop()
        client = arxiv.Client()

        def _search() -> list[SourceDocument]:
            search = arxiv.Search(
                query=topic,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance,
            )
            docs: list[SourceDocument] = []
            for result in client.results(search):
                content = f"# {result.title}\n\n**Authors:** {', '.join(str(a) for a in result.authors)}\n\n**Abstract:**\n{result.summary}\n\n**Published:** {result.published}"
                docs.append(
                    SourceDocument(
                        url=result.entry_id,
                        title=result.title,
                        content=content,
                        source_type="arxiv",
                        metadata={
                            "authors": [str(a) for a in result.authors],
                            "published": str(result.published),
                            "doi": result.doi,
                        },
                    )
                )
            return docs

        return await loop.run_in_executor(None, _search)
    except Exception as exc:
        logger.warning("arxiv_search_failed", error=str(exc))
        return []


def _extract_video_id(url: str) -> str | None:
    import re

    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
        r"(?:youtu\.be\/)([0-9A-Za-z_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


async def fetch_youtube_transcript(
    video_url: str,
    title: str = "",
) -> SourceDocument | None:
    video_id = _extract_video_id(video_url)
    if not video_id:
        logger.warning("youtube_invalid_url", url=video_url)
        return None

    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        full_text = " ".join(entry["text"] for entry in transcript_list)
        if len(full_text.strip()) < 100:
            return None
        return SourceDocument(
            url=video_url,
            title=title or f"YouTube: {video_id}",
            content=full_text[:15_000],
            source_type="youtube",
            metadata={"video_id": video_id},
        )
    except NoTranscriptFound:
        logger.warning("youtube_no_transcript", video_id=video_id)
        return None
    except Exception as exc:
        logger.warning("youtube_transcript_failed", video_id=video_id, error=str(exc))
        return None


async def parse_file_with_unstructured(file_path: str) -> SourceDocument | None:
    try:
        from unstructured.partition.auto import partition

        loop = asyncio.get_event_loop()

        def _parse() -> list:
            return partition(filename=file_path)

        elements = await loop.run_in_executor(None, _parse)
        text = "\n\n".join(str(el) for el in elements if str(el).strip())
        if len(text.strip()) < 50:
            return None

        name = Path(file_path).name
        return SourceDocument(
            url=f"file://{file_path}",
            title=name,
            content=text[:20_000],
            source_type="unstructured",
            metadata={"file": file_path},
        )
    except Exception as exc:
        logger.warning("unstructured_parse_failed", path=file_path, error=str(exc))
        return None
