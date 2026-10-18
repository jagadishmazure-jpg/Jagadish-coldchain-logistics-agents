"""RAG over the bundled cold-chain compliance SOPs.

Chunking is per markdown header section; retrieval is hand-rolled TF-IDF
with cosine similarity (stdlib only, fully deterministic). Every answer
cites its sources as "<doc> § <section>". When nothing relevant is found
the tool says so explicitly instead of guessing.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HEADER_RE = re.compile(r"^##\s+(.*)")
_TITLE_RE = re.compile(r"^#\s+(.*)")


@dataclass
class Chunk:
    doc: str
    section: str
    text: str


@dataclass
class SopAnswer:
    text: str
    sources: list[str] = field(default_factory=list)
    found: bool = False


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def load_sops(sop_dir: str | Path) -> list[Chunk]:
    """Chunk every docs/sops/*.md file by its ## sections."""
    chunks: list[Chunk] = []
    for path in sorted(Path(sop_dir).glob("*.md")):
        title = path.stem
        section = "Overview"
        buffer: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            title_match = _TITLE_RE.match(line)
            if title_match:
                title = title_match.group(1).strip()
                continue
            header_match = _HEADER_RE.match(line)
            if header_match:
                if buffer:
                    chunks.append(Chunk(path.name, section,
                                        "\n".join(buffer).strip()))
                    buffer = []
                section = header_match.group(1).strip()
            else:
                buffer.append(line)
        if buffer:
            chunks.append(Chunk(path.name, section, "\n".join(buffer).strip()))
    return [c for c in chunks if c.text]


class SopIndex:
    """Deterministic TF-IDF index over SOP chunks."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self._doc_freq: dict[str, int] = {}
        self._vectors: list[dict[str, float]] = []
        self._norms: list[float] = []
        for chunk in chunks:
            tokens = tokenize(chunk.text)
            counts: dict[str, int] = {}
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
            for token in set(tokens):
                self._doc_freq[token] = self._doc_freq.get(token, 0) + 1
            self._vectors.append(counts)
        n = max(1, len(chunks))
        self._idf = {t: math.log(n / df) for t, df in self._doc_freq.items()}
        for counts in self._vectors:
            weights = {t: (c * self._idf[t]) for t, c in counts.items()}
            self._norms.append(math.sqrt(sum(w * w for w in weights.values())))

    def search(self, query: str, top_k: int = 3) -> list[tuple[Chunk, float]]:
        query_counts: dict[str, int] = {}
        for token in tokenize(query):
            if token in self._idf:
                query_counts[token] = query_counts.get(token, 0) + 1
        if not query_counts:
            return []
        query_weights = {t: c * self._idf[t]
                         for t, c in query_counts.items()}
        query_norm = math.sqrt(sum(w * w for w in query_weights.values()))
        scored: list[tuple[Chunk, float]] = []
        for chunk, counts, norm in zip(self.chunks, self._vectors,
                                       self._norms):
            if norm == 0 or query_norm == 0:
                continue
            dot = sum(query_weights[t] * counts.get(t, 0) * self._idf[t]
                      for t in query_weights)
            score = dot / (query_norm * norm)
            if score > 0:
                scored.append((chunk, score))
        # Deterministic tie-break: score desc, then doc, then section.
        scored.sort(key=lambda item: (-item[1], item[0].doc, item[0].section))
        return scored[:top_k]


def cite(chunk: Chunk) -> str:
    return f"{chunk.doc} § {chunk.section}"


def answer_question(query: str, index: SopIndex,
                    top_k: int = 3) -> SopAnswer:
    """Answer from the SOPs with citations, or say so when not found."""
    hits = index.search(query, top_k=top_k)
    if not hits:
        return SopAnswer(
            text=("I could not find anything about this in the bundled "
                  "cold-chain SOPs, so I will not guess. Please rephrase "
                  "or ask about temperature control, breach protocol, "
                  "port diversion, or escalation tiers."),
            sources=[],
            found=False,
        )
    lines = ["Based on the cold-chain SOPs:"]
    for chunk, _score in hits:
        excerpt = chunk.text.strip().split("\n")[0][:220]
        lines.append(f"- {excerpt} [{cite(chunk)}]")
    return SopAnswer(
        text="\n".join(lines),
        sources=[cite(chunk) for chunk, _ in hits],
        found=True,
    )
