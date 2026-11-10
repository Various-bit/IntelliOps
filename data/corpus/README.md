# Corpus files

- [Source catalog](../../docs/corpus.md) lists the publisher links, rights, verification dates, and corresponding notes.
- `notes/` contains one Markdown summary per source. Use this directory as the initial retrieval corpus. The note filename is the source ID.
- `originals/` holds local PDF and HTML downloads named by source ID. Git ignores this directory because it can contain large files and materials with redistribution restrictions.

The VNB001 local PDF is ifm's product sheet. The PN7094 local PDF is the US-English datasheet supplied by a distributor. The catalog links to both downloaded editions and the manufacturer's full GB-English datasheets.

To rebuild the local collection after cloning, follow the source links in the catalog. Save each PDF or HTML page under `originals/` using its note filename stem and the corresponding `.pdf` or `.html` extension. Use the linked local editions for the two ifm documents.
