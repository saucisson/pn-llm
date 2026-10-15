# 15. A canonical JSON net document; PNML by content negotiation; identity by canonical hash

Status: proposed (review before any code). Supersedes the identity rule of ADR 0005 and amends
ADR 0013 (points 1 and 5).

## Context
Nets arrive as PNML files, but a file is a poor identity: two files describing the same net (other
element order, whitespace, comments, namespace prefixes) would get different ids. PNML is also
awkward for APIs, tests and a future graph view. We want one internal representation that keeps all
the information that matters (pages, tool-specific data, graphics, P/T and colored nets), and the
freedom to speak PNML or JSON on the wire.

## Decision
1. **The canonical representation of a net is a JSON `NetDocument`** (`docs/net-document.md`).
   A net uploaded as PNML or as JSON is converted to it in every case; that document is what is
   stored. The original file bytes are not kept.
2. **No semantic information is lost in conversion**: pages and their hierarchy, reference places
   and transitions, graphics, tool-specific data, annotations, unknown extension elements, colored
   declarations and terms, for P/T and colored nets. What is dropped is lexical (comments, white
   space, attribute and element order, namespace prefixes, XML declaration), and the document says
   so explicitly.
3. **Identity is the hash of the canonical document**, not of a file. The canonical form fixes key
   order, omits absent and default values, sorts children by id in each container, keeps names and
   ids byte for byte (no Unicode normalization, `CLAUDE.md` rule 7). `net_id` is the first 32 hex
   characters of its SHA-256. Two files of the same net give the same id; changing a name, a
   graphic or a tool-specific entry gives another id.
4. **Content negotiation, JSON by default.** `POST /v1/nets` accepts `Content-Type:
   application/json` (a `NetDocument`) or `application/pnml+xml` (also `application/xml` and
   `text/xml`). `GET /v1/nets/{id}` returns the `NetDocument` by default and the canonical PNML
   with `Accept: application/pnml+xml`. Other types give 415 or 406.
5. **PNML is a serialization of the net, no longer the representation.** Engines receive a PNML
   rendered deterministically from the document; a reduction's `reduced.pnml` is imported back
   through the same hardened importer, hashed, and stored as a new net (ADR 0005 parent link).
6. **The LLM never receives the net document, in either format.** It learns about a net through
   inspection tools (ADR 0013); `GET /v1/nets/{id}` is excluded from its tools. This replaces
   "never reads PNML" by the stronger "never reads the net itself".
7. **Safety**: the PNML importer uses hardened parsing (no DTD, no entities); both formats are
   validated alike (unique ids, arcs between existing nodes of opposite kinds, references that
   resolve) and bounded (size, depth, element counts).
8. **Evolution**: additive only. New optional fields are omitted when absent, so existing ids stay
   valid. A breaking change needs a new ADR and a migration that creates new nets and records the
   old id.

## Consequences
- Identical nets are deduplicated across formats and tools; caches and results are shared.
- Round-trips are semantic, not byte-exact: PNML to JSON to PNML to JSON is a fixed point, checked
  on the MCC corpus; the PNML we emit differs textually from the one received.
- A multi-net PNML file is rejected (one net per document); a batch importer can split it later.
- Graphics and tool-specific data take part in the identity: the same model with another layout is
  another net. A secondary behaviour hash, ignoring them, is possible later for deduplication in
  evaluation.
- Colored nets are kept losslessly from day one through a generic tree for declarations and terms;
  a typed vocabulary is added on top in milestone M3 without changing identities.
- Size: documents are large for large nets; they are stored compressed.
