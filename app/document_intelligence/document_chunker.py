"""Chunking: heading-aware, paragraph packing with overlap and table safety.

Tables are kept whole so a value never loses its column header, and each chunk
remembers its page and section.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.core.constants import KnowledgeCategory

HEADING_RE = re.compile(r"^(#{1,6}\s+.+|[A-Z][A-Z0-9 ,&/\-]{6,80})$")


@dataclass
class Chunk:
    content: str
    page_number: int | None
    section_heading: str | None
    chunk_index: int

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    @property
    def token_estimate(self) -> int:
        return max(1, len(self.content) // 4)


class DocumentChunker:
    """Splits parsed pages into overlapping, section-aware chunks."""

    def __init__(self, *, target_chars: int = 900, overlap_chars: int = 150, max_chars: int = 1600) -> None:
        self.target_chars = max(200, target_chars)
        self.overlap_chars = max(0, min(overlap_chars, self.target_chars // 2))
        self.max_chars = max(self.target_chars, max_chars)

    def chunk_pages(self, pages: list, *, category: str | None = None) -> list[Chunk]:
        chunks: list[Chunk] = []
        index = 0
        for page in pages:
            text = (getattr(page, "text", "") or "").strip()
            if not text:
                continue
            for block, heading in self._blocks(text):
                for piece in self._pack(block):
                    chunks.append(
                        Chunk(
                            # The heading is part of the retrievable text: a clause
                            # only means something under its own heading.
                            content=f"{heading}\n{piece}" if heading and heading not in piece else piece,
                            page_number=getattr(page, "page_number", None),
                            section_heading=heading,
                            chunk_index=index,
                        )
                    )
                    index += 1
        return chunks

    # -- structure ---------------------------------------------------------
    def _blocks(self, text: str) -> list[tuple[str, str | None]]:
        """Split into (block, heading) pairs, keeping tables intact."""
        blocks: list[tuple[str, str | None]] = []
        heading: str | None = None
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                blocks.append(("\n\n".join(buffer).strip(), heading))
                buffer.clear()

        # Tables are extracted first so they are never split by paragraph logic.
        segments = re.split(r"(\[TABLE\].*?\[/TABLE\])", text, flags=re.DOTALL)
        for segment in segments:
            segment = segment.strip()
            if not segment:
                continue
            if segment.startswith("[TABLE]"):
                flush()
                blocks.append((segment, heading))
                continue
            for paragraph in re.split(r"\n\s*\n", segment):
                paragraph = paragraph.strip()
                if not paragraph:
                    continue
                first_line = paragraph.splitlines()[0].strip()
                if HEADING_RE.match(first_line) and len(first_line) < 120:
                    flush()
                    heading = first_line.lstrip("#").strip()
                    rest = "\n".join(paragraph.splitlines()[1:]).strip()
                    if rest:
                        buffer.append(rest)
                    continue
                buffer.append(paragraph)
        flush()
        return blocks

    def _pack(self, block: str) -> list[str]:
        block = block.strip()
        if not block:
            return []
        if len(block) <= self.target_chars:
            return [block]
        if block.startswith("[TABLE]"):
            # A table too large for one chunk is split by rows, repeating the header.
            return self._split_table(block)
        pieces: list[str] = []
        sentences = re.split(r"(?<=[.!?])\s+", block)
        current = ""
        for sentence in sentences:
            if not sentence:
                continue
            if len(current) + len(sentence) + 1 <= self.target_chars:
                current = f"{current} {sentence}".strip()
                continue
            if current:
                pieces.append(current)
                tail = current[-self.overlap_chars :] if self.overlap_chars else ""
                current = f"{tail} {sentence}".strip()
            else:
                # A single very long sentence is hard-split at the max length.
                for start in range(0, len(sentence), self.max_chars):
                    pieces.append(sentence[start : start + self.max_chars])
                current = ""
        if current:
            pieces.append(current)
        return [piece for piece in pieces if piece.strip()]

    def _split_table(self, block: str) -> list[str]:
        inner = block.replace("[TABLE]", "").replace("[/TABLE]", "").strip()
        rows = [row for row in inner.splitlines() if row.strip()]
        if len(rows) <= 2:
            return [block]
        header = rows[0]
        pieces: list[str] = []
        current_rows: list[str] = [header]
        current_len = len(header)
        for row in rows[1:]:
            if current_len + len(row) + 1 > self.target_chars and len(current_rows) > 1:
                pieces.append("[TABLE]\n" + "\n".join(current_rows) + "\n[/TABLE]")
                current_rows = [header, row]
                current_len = len(header) + len(row)
            else:
                current_rows.append(row)
                current_len += len(row) + 1
        if len(current_rows) > 1:
            pieces.append("[TABLE]\n" + "\n".join(current_rows) + "\n[/TABLE]")
        return pieces
