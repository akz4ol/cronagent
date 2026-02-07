"""
Knowledge base with vector search for codebase understanding.

Provides:
- File indexing with semantic chunking
- Vector similarity search
- Project context retrieval
- Support for ChromaDB (local) and pgvector (server)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from cronagent.bus.events import EventBus, Events
from cronagent.config import MemoryConfig

logger = logging.getLogger(__name__)


class SourceType(str, Enum):
    """Document source types."""

    CODE = "code"
    DOCUMENTATION = "documentation"
    CONVERSATION = "conversation"
    INSIGHT = "insight"
    CLAUDE_MD = "claude_md"


@dataclass
class DocumentChunk:
    """Represents a chunk of a document with embedding."""

    doc_id: str
    content: str
    project_id: str
    source_type: SourceType = SourceType.CODE
    file_path: str | None = None
    chunk_index: int = 0
    total_chunks: int = 1
    language: str = "natural"
    content_hash: str = ""
    importance_score: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.content.encode()).hexdigest()[:16]


@dataclass
class SearchResult:
    """Result from knowledge base search."""

    chunk: DocumentChunk
    similarity: float
    highlights: list[str] | None = None


class KnowledgeBase:
    """
    Long-term knowledge storage with semantic search.

    Supports:
    - ChromaDB for local development
    - pgvector for server deployment (future)

    Usage:
        kb = KnowledgeBase(config.memory)
        await kb.initialize()

        # Index a file
        await kb.index_file("/path/to/file.py", "my-project")

        # Search
        results = await kb.search("authentication logic", "my-project")

        # Get project context
        context = await kb.get_project_context("my-project")
    """

    def __init__(
        self,
        config: MemoryConfig,
        event_bus: EventBus | None = None,
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self._client: Any = None
        self._collection: Any = None
        self._chunker = DocumentChunker()

    async def initialize(self) -> None:
        """Initialize the vector store."""
        if not self.config.enable_knowledge_base:
            logger.info("Knowledge base disabled")
            return

        if self.config.knowledge_store == "chromadb":
            await self._init_chromadb()
        else:
            logger.warning(f"Unsupported knowledge store: {self.config.knowledge_store}")

    async def _init_chromadb(self) -> None:
        """Initialize ChromaDB."""
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            logger.error("chromadb not installed. Install with: pip install chromadb")
            return

        # Expand path
        db_path = Path(self.config.chromadb_path).expanduser()
        db_path.mkdir(parents=True, exist_ok=True)

        # Create client with persistence
        self._client = chromadb.Client(
            Settings(
                chroma_db_impl="duckdb+parquet",
                persist_directory=str(db_path),
                anonymized_telemetry=False,
            )
        )

        # Get or create collection
        self._collection = self._client.get_or_create_collection(
            name="codebase_knowledge",
            metadata={
                "description": "CronAgent codebase knowledge",
                "hnsw:space": "cosine",
            },
        )

        logger.info(f"ChromaDB initialized at {db_path}")

    async def index_file(
        self,
        file_path: str,
        project_id: str,
        force_reindex: bool = False,
    ) -> list[str]:
        """
        Index a file into the knowledge base.

        Args:
            file_path: Path to file to index
            project_id: Project identifier
            force_reindex: Force re-indexing even if unchanged

        Returns:
            List of created document IDs
        """
        if not self._collection:
            logger.warning("Knowledge base not initialized")
            return []

        path = Path(file_path)
        if not path.exists():
            logger.warning(f"File not found: {file_path}")
            return []

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.warning(f"Failed to read file {file_path}: {e}")
            return []

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Check if already indexed
        if not force_reindex:
            existing = self._collection.get(
                where={
                    "$and": [
                        {"project_id": project_id},
                        {"content_hash": content_hash},
                    ]
                }
            )
            if existing and existing["ids"]:
                logger.debug(f"File already indexed: {file_path}")
                return existing["ids"]

        # Detect language and source type
        language = self._detect_language(file_path)
        source_type = self._infer_source_type(file_path)

        # Chunk the content
        chunks = self._chunker.chunk(content, language)

        # Create document chunks
        doc_ids = []
        documents = []
        metadatas = []

        for i, chunk_content in enumerate(chunks):
            doc_id = f"{project_id}:{path.name}:{i}"
            doc_ids.append(doc_id)
            documents.append(chunk_content)
            metadatas.append({
                "project_id": project_id,
                "file_path": str(file_path),
                "chunk_index": i,
                "total_chunks": len(chunks),
                "source_type": source_type.value,
                "language": language,
                "content_hash": content_hash if i == 0 else "",
                "importance_score": self._calculate_importance(file_path, source_type),
                "indexed_at": datetime.utcnow().isoformat(),
            })

        # Delete old versions
        try:
            self._collection.delete(
                where={
                    "$and": [
                        {"project_id": project_id},
                        {"file_path": str(file_path)},
                    ]
                }
            )
        except Exception:
            pass  # Collection might be empty

        # Add to collection (ChromaDB will generate embeddings)
        self._collection.add(
            ids=doc_ids,
            documents=documents,
            metadatas=metadatas,
        )

        logger.info(f"Indexed {len(chunks)} chunks from {file_path}")

        if self.event_bus:
            await self.event_bus.emit(
                Events.KNOWLEDGE_INDEXED,
                {
                    "file_path": file_path,
                    "project_id": project_id,
                    "chunks": len(chunks),
                },
            )

        return doc_ids

    async def index_directory(
        self,
        directory: str,
        project_id: str,
        patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> dict[str, int]:
        """
        Index an entire directory.

        Args:
            directory: Root directory to index
            project_id: Project identifier
            patterns: Glob patterns to include
            exclude_patterns: Glob patterns to exclude

        Returns:
            Statistics dict
        """
        import fnmatch

        if patterns is None:
            patterns = [
                "*.py", "*.js", "*.ts", "*.tsx", "*.jsx",
                "*.md", "*.rst", "*.txt",
                "*.java", "*.go", "*.rs", "*.rb",
                "*.yaml", "*.yml", "*.json", "*.toml",
            ]

        if exclude_patterns is None:
            exclude_patterns = [
                "node_modules/*", ".git/*", "venv/*", "__pycache__/*",
                "dist/*", "build/*", ".tox/*", "*.egg-info/*",
            ]

        stats = {"indexed": 0, "skipped": 0, "errors": 0}
        root = Path(directory)

        for pattern in patterns:
            for file_path in root.rglob(pattern):
                # Check exclusions
                rel_path = str(file_path.relative_to(root))
                if any(fnmatch.fnmatch(rel_path, ex) for ex in exclude_patterns):
                    stats["skipped"] += 1
                    continue

                try:
                    ids = await self.index_file(str(file_path), project_id)
                    if ids:
                        stats["indexed"] += 1
                    else:
                        stats["skipped"] += 1
                except Exception as e:
                    logger.warning(f"Failed to index {file_path}: {e}")
                    stats["errors"] += 1

        logger.info(
            f"Indexed directory {directory}: "
            f"{stats['indexed']} files, {stats['skipped']} skipped, {stats['errors']} errors"
        )
        return stats

    async def search(
        self,
        query: str,
        project_id: str,
        limit: int = 10,
        source_types: list[SourceType] | None = None,
        min_similarity: float = 0.5,
    ) -> list[SearchResult]:
        """
        Search knowledge base for relevant content.

        Args:
            query: Search query
            project_id: Project to search within
            limit: Maximum results
            source_types: Filter by source types
            min_similarity: Minimum similarity threshold

        Returns:
            List of SearchResult ordered by relevance
        """
        if not self._collection:
            return []

        # Build filter
        where_filter: dict[str, Any] = {"project_id": project_id}

        if source_types:
            where_filter["source_type"] = {"$in": [st.value for st in source_types]}

        # Search
        results = self._collection.query(
            query_texts=[query],
            n_results=limit,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        # Convert to SearchResult
        search_results = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                # ChromaDB returns distance, convert to similarity
                distance = results["distances"][0][i] if results["distances"] else 0
                similarity = 1 - distance  # Cosine distance to similarity

                if similarity < min_similarity:
                    continue

                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                content = results["documents"][0][i] if results["documents"] else ""

                chunk = DocumentChunk(
                    doc_id=doc_id,
                    content=content,
                    project_id=metadata.get("project_id", project_id),
                    source_type=SourceType(metadata.get("source_type", "code")),
                    file_path=metadata.get("file_path"),
                    chunk_index=metadata.get("chunk_index", 0),
                    total_chunks=metadata.get("total_chunks", 1),
                    language=metadata.get("language", "natural"),
                    importance_score=metadata.get("importance_score", 0.5),
                    metadata=metadata,
                )

                search_results.append(SearchResult(chunk=chunk, similarity=similarity))

        return search_results

    async def get_project_context(
        self,
        project_id: str,
        max_tokens: int = 4000,
    ) -> str:
        """
        Get aggregated project context.

        Combines:
        - CLAUDE.md content (highest priority)
        - High-importance indexed documents
        - Recent insights

        Returns:
            Formatted context string
        """
        context_parts = []
        current_tokens = 0

        # Get CLAUDE.md first
        claude_md_results = await self.search(
            query="project context configuration guidelines",
            project_id=project_id,
            limit=1,
            source_types=[SourceType.CLAUDE_MD],
        )

        if claude_md_results:
            content = claude_md_results[0].chunk.content
            tokens = len(content) // 4
            if current_tokens + tokens < max_tokens:
                context_parts.append(f"## Project Guidelines\n{content}")
                current_tokens += tokens

        # Get high-importance code/docs
        important_results = await self.search(
            query="important core functionality main entry",
            project_id=project_id,
            limit=5,
        )

        for result in important_results:
            if result.chunk.importance_score < 0.7:
                continue
            tokens = len(result.chunk.content) // 4
            if current_tokens + tokens < max_tokens:
                header = result.chunk.file_path or "Knowledge"
                context_parts.append(f"## {header}\n{result.chunk.content}")
                current_tokens += tokens

        return "\n\n".join(context_parts)

    async def delete_project(self, project_id: str) -> int:
        """Delete all documents for a project."""
        if not self._collection:
            return 0

        try:
            # Get all IDs for project
            results = self._collection.get(
                where={"project_id": project_id},
            )
            if results["ids"]:
                self._collection.delete(ids=results["ids"])
                return len(results["ids"])
        except Exception as e:
            logger.error(f"Failed to delete project {project_id}: {e}")

        return 0

    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".php": "php",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".md": "markdown",
            ".rst": "restructuredtext",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".toml": "toml",
        }
        ext = Path(file_path).suffix.lower()
        return ext_map.get(ext, "natural")

    def _infer_source_type(self, file_path: str) -> SourceType:
        """Infer source type from file path."""
        path_lower = file_path.lower()

        if "claude.md" in path_lower:
            return SourceType.CLAUDE_MD
        if any(doc in path_lower for doc in ["readme", "docs/", "documentation"]):
            return SourceType.DOCUMENTATION
        if path_lower.endswith((".md", ".rst", ".txt")):
            return SourceType.DOCUMENTATION

        return SourceType.CODE

    def _calculate_importance(
        self,
        file_path: str,
        source_type: SourceType,
    ) -> float:
        """Calculate importance score for a document."""
        score = 0.5
        path_lower = file_path.lower()

        # Boost by source type
        if source_type == SourceType.CLAUDE_MD:
            score = 1.0
        elif source_type == SourceType.DOCUMENTATION:
            score = 0.7

        # Boost important file names
        important_names = [
            "readme", "claude", "main", "index", "app",
            "config", "settings", "setup", "init",
        ]
        if any(name in path_lower for name in important_names):
            score = min(1.0, score + 0.2)

        # Boost root-level files
        if "/" not in file_path or file_path.count("/") == 1:
            score = min(1.0, score + 0.1)

        return score


class DocumentChunker:
    """Splits documents into chunks for embedding."""

    def __init__(
        self,
        chunk_size: int = 1000,
        overlap: int = 200,
    ) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, content: str, language: str = "natural") -> list[str]:
        """
        Split content into overlapping chunks.

        Uses language-aware splitting when possible.
        """
        if language in ("python", "javascript", "typescript", "java", "go", "rust"):
            return self._chunk_code(content)
        return self._chunk_text(content)

    def _chunk_code(self, content: str) -> list[str]:
        """Split code respecting function/class boundaries."""
        # Split by double newlines (paragraph-like blocks)
        blocks = content.split("\n\n")
        chunks = []
        current_chunk: list[str] = []
        current_size = 0

        for block in blocks:
            block_size = len(block)

            if current_size + block_size > self.chunk_size and current_chunk:
                chunks.append("\n\n".join(current_chunk))

                # Keep overlap
                overlap_blocks: list[str] = []
                overlap_size = 0
                for b in reversed(current_chunk):
                    if overlap_size + len(b) < self.overlap:
                        overlap_blocks.insert(0, b)
                        overlap_size += len(b)
                    else:
                        break

                current_chunk = overlap_blocks
                current_size = overlap_size

            current_chunk.append(block)
            current_size += block_size

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks if chunks else [content]

    def _chunk_text(self, content: str) -> list[str]:
        """Split text by paragraphs."""
        paragraphs = content.split("\n\n")
        chunks = []
        current_chunk: list[str] = []
        current_size = 0

        for para in paragraphs:
            para_size = len(para)

            if current_size + para_size > self.chunk_size and current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_size = 0

            current_chunk.append(para)
            current_size += para_size

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks if chunks else [content]
