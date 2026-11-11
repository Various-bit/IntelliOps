"""Build the local Chroma collection from the Knowledge Agent corpus."""

import argparse
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import chromadb
from bs4 import BeautifulSoup
from pypdf import PdfReader

from agent.config import load_settings

COLLECTION_NAME = "knowledge"
CHUNK_WORDS = 100
OVERLAP_WORDS = 15
BATCH_SIZE = 64
FORMATS = {".md", ".pdf", ".html"}
MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
HTML_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    metadata: dict[str, str | int]


def sections(blocks: Iterable[tuple[bool, str]], title: str) -> Iterator[tuple[str, str]]:
    section = title
    body = []
    for is_heading, text in blocks:
        if is_heading:
            if body:
                yield section, "\n".join(body)
                body = []
            section = text
        elif text.strip():
            body.append(text)
    if body:
        yield section, "\n".join(body)


def read_sections(path: Path) -> Iterator[tuple[int, str, str]]:
    if path.suffix.lower() == ".pdf":
        pdf = PdfReader(path)
        section = ""
        bookmarks = {}

        def collect_bookmarks(items):
            for item in items:
                if isinstance(item, list):
                    collect_bookmarks(item)
                else:
                    page = pdf.get_destination_page_number(item)
                    if page is not None:
                        bookmarks.setdefault(page, item.title)

        collect_bookmarks(pdf.outline)
        for page, content in enumerate(pdf.pages):
            section = bookmarks.get(page, section)
            yield page + 1, section or f"Page {page + 1}", content.extract_text() or ""
        return

    if path.suffix.lower() == ".md":
        content = path.read_text(encoding="utf-8")
        blocks = []
        for line in content.splitlines():
            if line.startswith("[Original source]("):
                continue
            heading = MARKDOWN_HEADING.match(line)
            blocks.append((bool(heading), heading[1] if heading else line))
    else:
        soup = BeautifulSoup(path.read_bytes(), "html.parser")
        for tag in soup.find_all(["header", "nav", "footer", "aside", "script", "style"]):
            tag.decompose()
        article = soup.find("main") or soup.find("article") or soup.body or soup
        blocks = [
            (tag.name in HTML_HEADINGS, tag.get_text(" ", strip=True))
            for tag in article.find_all([*HTML_HEADINGS, "p", "li", "pre", "table"])
            if tag.find_parent(["li", "pre", "table"]) is None
        ]
    for section, body in sections(blocks, path.stem):
        yield 0, section, body


def chunks_for(path: Path) -> Iterator[Chunk]:
    ordinal = 0
    for page, section, body in read_sections(path):
        words = list(re.finditer(r"\S+", body))
        for start in range(0, len(words), CHUNK_WORDS - OVERLAP_WORDS):
            end = min(start + CHUNK_WORDS, len(words))
            ordinal += 1
            yield Chunk(
                id=f"{path.stem}:{ordinal}",
                text=body[words[start].start() : words[end - 1].end()],
                metadata={
                    "source_id": path.stem,
                    "source_file": path.name,
                    "source_kind": "note" if path.suffix.lower() == ".md" else "original",
                    "page": page,
                    "section": section,
                },
            )
            if end == len(words):
                break


def build_index(source_dir: Path, chroma_dir: Path) -> tuple[int, int]:
    files = sorted(path for path in source_dir.glob("*") if path.is_file() and path.suffix.lower() in FORMATS)
    if not files:
        raise ValueError(f"No Markdown, PDF or HTML documents found in {source_dir}")
    if len({path.stem for path in files}) != len(files):
        raise ValueError(f"Duplicate source IDs in {source_dir}")

    chunks = []
    skipped = []
    for path in files:
        document_chunks = list(chunks_for(path))
        if not document_chunks:
            skipped.append(path.name)
            continue
        chunks.extend(document_chunks)
    if skipped:
        print(f"WARNING: не извлечён текст из {len(skipped)} документов, пропущены: {', '.join(skipped)}")
    if not chunks:
        raise ValueError(f"No text found in any document of {source_dir}")
    return len(files) - len(skipped), len(chunks)

    client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = client.get_or_create_collection(COLLECTION_NAME)
    old_ids = set(collection.get(include=[])["ids"])
    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start : start + BATCH_SIZE]
        collection.upsert(
            ids=[chunk.id for chunk in batch],
            documents=[chunk.text for chunk in batch],
            metadatas=[chunk.metadata for chunk in batch],
        )
    stale_ids = sorted(old_ids - {chunk.id for chunk in chunks})
    for start in range(0, len(stale_ids), BATCH_SIZE):
        collection.delete(ids=stale_ids[start : start + BATCH_SIZE])
    return len(files), len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", action="store_true", help="Index downloaded PDFs and HTML instead of notes")
    args = parser.parse_args()
    settings = load_settings()
    source_dir = settings.corpus_dir / ("originals" if args.originals else "notes")
    try:
        files, chunks = build_index(source_dir, settings.chroma_dir)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    print(f"Indexed {files} documents and {chunks} chunks in {settings.chroma_dir}")
    if not args.originals:
        print(
            "ВНИМАНИЕ: агент Knowledge ищет только чанки первоисточников "
            "(source_kind='original'). Для рабочих цитат соберите индекс командой "
            "python -m rag.index --originals (оригиналы см. data/corpus/README.md)."
        )


if __name__ == "__main__":
    main()
