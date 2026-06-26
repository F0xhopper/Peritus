import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    DATABASE_SSL: bool = os.getenv("DATABASE_SSL", "false").lower() == "true"

    # Embeddings
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    EMBED_MODEL: str = os.getenv("EMBED_MODEL", "text-embedding-3-large")
    EMBED_DIM: int = int(os.getenv("EMBED_DIM", "3072"))

    # Anthropic — validation, graph extraction, persona, chat
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    # Fast model for contextualisation, reranking, planning, coverage
    FAST_MODEL: str = os.getenv("FAST_MODEL", "claude-haiku-4-5-20251001")

    # Graph extraction model — Haiku is sufficient and much cheaper than Sonnet
    GRAPH_MODEL: str = os.getenv("GRAPH_MODEL", "claude-haiku-4-5-20251001")

    # Source fetchers
    EXA_API_KEY: str = os.getenv("EXA_API_KEY", "")

    # Mistral OCR (PDF parsing)
    MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
    MISTRAL_OCR_MODEL: str = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")

    # Contextual retrieval
    CONTEXT_ENABLED: bool = os.getenv("CONTEXT_ENABLED", "true").lower() == "true"
    CONTEXT_MAX_CHARS: int = int(os.getenv("CONTEXT_MAX_CHARS", "2000"))
    CONTEXT_CONCURRENCY: int = int(os.getenv("CONTEXT_CONCURRENCY", "4"))

    # Reranking
    RERANK_ENABLED: bool = os.getenv("RERANK_ENABLED", "true").lower() == "true"
    RERANK_CANDIDATES: int = int(os.getenv("RERANK_CANDIDATES", "50"))

    # Source validation concurrency limit
    VALIDATE_CONCURRENCY: int = int(os.getenv("VALIDATE_CONCURRENCY", "5"))

    # Graph extraction batch size (chunks per Claude call)
    GRAPH_BATCH_SIZE: int = int(os.getenv("GRAPH_BATCH_SIZE", "20"))

    # Chunking
    CHUNK_SIZE_CHARS: int = int(os.getenv("CHUNK_SIZE_CHARS", "1500"))
    CHUNK_OVERLAP_CHARS: int = int(os.getenv("CHUNK_OVERLAP_CHARS", "200"))

    def check_required_vars(self) -> list[str]:
        missing = []
        if not self.DATABASE_URL:
            missing.append("DATABASE_URL")
        if not self.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")
        if not self.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")
        return missing


settings = Settings()
