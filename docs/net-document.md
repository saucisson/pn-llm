# Net document

The canonical representation of a net (ADR 0015). A `NetDocument` is a frozen pydantic model in
`app/domain`; its JSON Schema is exported from it and committed. PNML is a serialization of the
same net, chosen with HTTP content negotiation.

## Formats and negotiation
| Direction | Header | Value | Result |
|---|---|---|---|
| `POST /v1/nets` | `Content-Type` | `application/json` (default) | body is a `NetDocument` |
| | | `application/pnml+xml`, `application/xml`, `text/xml` | body is PNML, converted |
| | | anything else | 415 |
| `GET /v1/nets/{id}` | `Accept` | `application/json` or absent (default) | the `NetDocument` |
| | | `application/pnml+xml` | canonical PNML, rendered from the document |
| | | anything else | 406 |

`application/pnml+xml` is the media type chosen by this project for PNML. `POST` answers in JSON
(`net_id`, whether it was created, a summary) with a `Location` header; `GET` carries `ETag` equal
to the net id and `Cache-Control: immutable`, because nets never change. Invalid input gives 422
`application/problem+json` pointing at the fault (a JSON pointer, or a line for PNML). A file with
more than one `<net>` is rejected. `GET /v1/nets/{id}` is never offered to the LLM.

## Shape
The net and every page are containers with the same content fields; elements may sit directly in
the net or in nested pages, as in PNML, and their place in the page tree is kept. Absent and
default fields are omitted.
```json
{
  "schema_version": "1.0",
  "source_id": "mutex",
  "type_uri": "http://www.pnml.org/version-2009/grammar/ptnet",
  "kind": "pt",
  "pages": [{
    "id": "p",
    "places": [
      {"id": "idle1",
       "name": {"text": "idle1", "graphics": {"offset": {"x": -10, "y": 20}}},
       "initial_marking": {"text": "1"},
       "graphics": {"position": {"x": 40, "y": 60}, "dimension": {"x": 20, "y": 20}},
       "tool_specific": [{"tool": "example", "version": "1.0",
                          "content": [{"name": "note", "content": ["kept as is"]}]}]},
      {"id": "crit1", "name": {"text": "crit1"}}
    ],
    "transitions": [{"id": "enter1", "name": {"text": "enter1"}}],
    "arcs": [{"id": "a1", "source": "idle1", "target": "enter1",
              "inscription": {"text": "2"},
              "graphics": {"positions": [{"x": 50, "y": 70}]}}]
  }]
}
```

### Types
- `Annotation`: `text` (as written), optional `structure` (colored terms), optional `graphics`
  (offset, fill, line, font), optional `tool_specific`. Used for names, initial markings,
  inscriptions, place types, guards and declarations.
- `NodeGraphics`: position, dimension, fill, line. `ArcGraphics`: intermediate positions, line.
- `ToolSpecific`: `tool`, `version`, `content` (a list of `XmlNode`). Opaque and kept in order.
- `XmlNode`: `name` (qualified by namespace URI when it has one), `attributes`, `content` (a list
  of text and `XmlNode`, which keeps mixed content). Used for tool-specific payloads, unknown
  extension elements (`extensions` on every object) and, for now, colored declarations and terms.
- Reference places and transitions (`ref_places`, `ref_transitions`) keep their `ref` target.
- Typed values are **derived**, not stored twice: the integer of a P/T marking or inscription is
  parsed from `text` on import (a non-integer is rejected). An absent marking means 0 and an absent
  inscription means 1, as in PNML, and stay absent in the document.

## Mapping from PNML
| PNML | Document |
|---|---|
| `net` `id`, `type` | `source_id`, `type_uri`; `kind` derived (`pt`, `symmetric`, `hlpn`, `core`, `other`) |
| `name`, `text` | `name.text` |
| `page`, nested `page` | `pages[]`, recursively |
| `place`, `transition`, `arc` | `places[]`, `transitions[]`, `arcs[]` |
| `referencePlace`, `referenceTransition` | `ref_places[]`, `ref_transitions[]` |
| `initialMarking`, `inscription` | `initial_marking`, `inscription` annotations |
| `graphics` | `graphics` (node, arc or annotation variant) |
| `toolspecific` | `tool_specific[]` |
| declarations, place `type`, transition `condition`, `structure` | annotations with `structure` as `XmlNode` trees |
| any other element or attribute | `extensions[]`, `extra_attributes` |

## Colored nets
Declarations (sorts, variables, operators) and terms (markings, inscriptions, guards) are kept as
`XmlNode` trees: nothing is lost, and the same document round-trips. Milestone M3 adds a typed
vocabulary of sorts and terms on top, used by summaries, unfolding and engines, without changing
stored documents or ids.

## What is kept and what is not
Kept: everything above, names and ids exactly, tool-specific and unknown content in order.
Not kept (lexical only): the XML declaration and encoding, comments and processing instructions,
white space between elements, attribute order, element order (children are sorted by id inside each
container), namespace prefixes (namespaces are resolved, and rendered with fixed prefixes), CDATA
versus escaped text. DTDs and entities are refused, not interpreted. A file with several nets is
refused.

## Rendered PNML
`render_pnml` writes UTF-8, structural elements without a namespace, indentation only where the
content is not mixed, attribute white space as character references so that it is not normalized.
A name in a namespace gets a prefix declared on its own element (`ns0` for the element, `ns1`...
for its attributes, in sorted order of namespace URI). The root `pnml` element carries no
attribute. Characters that XML 1.0 cannot carry are refused. High-level nets (`symmetric`, `hlpn`)
use `hlinitialMarking` and `hlinscription`; the others use `initialMarking` and `inscription`.

## Canonical form and identity
1. Build the document; omit absent, null and default values.
2. Sort the children of each container by id; keep `tool_specific` and `content` order.
3. Serialize as JSON Canonicalization Scheme (RFC 8785): sorted keys, no white space, UTF-8.
4. `net_id` = first 32 hex characters of the SHA-256 of those bytes.

`schema_version` is not part of the hash. Evolution is additive (ADR 0015), so a stored id never
changes; golden hashes of a fixed corpus are tested.

## Limits
Maximum upload size, maximum depth of `XmlNode` trees and of pages, maximum numbers of elements and
string lengths come from `Settings`; exceeding one gives 413 or 422, never a crash. Documents are
stored compressed.

## Tests required
- PNML to document to PNML to document is a fixed point on the MCC corpus; JSON upload and PNML
  upload of the same net give the same id.
- Permuting elements or renaming prefixes keeps the id; changing a name, a graphic or a
  tool-specific entry changes it.
- Engines give the same verdicts on the original and on the rendered PNML (known-verdict nets).
- Hostile input (entities, deep nesting, huge counts, duplicate ids, dangling arcs) is refused.
- The Accept and Content-Type matrix, including 406 and 415.
