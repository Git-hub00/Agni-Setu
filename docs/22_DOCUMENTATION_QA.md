# Documentation validation and delivery checks

**Agni Setu implementation baseline 2.0.0 | 2026-09-09**  
**Status:** build specification; not evidence of a completed implementation or government approval.

## 1. What was actually checked

The checks below were executed against the generated Markdown pack, its central requirement/contract registries and the mounted reference prototype. They are documentation-integrity checks, not execution of the future Django/React product. JavaScript syntax parsing was used to inventory prototype action keys; the prototype's complete UI flows were not re-executed during this delivery.

| Check | Result | Evidence |
| --- | --- | --- |
| Required document set | PASS | 25 numbered documents plus root/agent/reference instructions are present. |
| UTF-8 readability | PASS | 29 Markdown files decoded successfully. |
| Local Markdown links | PASS | 179 relative file links checked; no missing target files. Heading-anchor rendering is not included. |
| Requirement IDs | PASS | 30 entries, all unique. |
| Screen IDs | PASS | 28 entries, all unique. |
| Transition IDs | PASS | 15 entries, all unique. |
| API IDs | PASS | 123 entries, all unique. |
| Error codes | PASS | 51 entries, all unique. |
| Build-phase IDs | PASS | 21 entries, all unique. |
| Core acceptance IDs | PASS | 180 entries, all unique. |
| Entity names | PASS | 66 entries, all unique. |
| API method/path uniqueness | PASS | 123 method/path pairs, no duplicate contracts. |
| API catalogue materialized | PASS | Every registered endpoint ID is present in the delivered API document. |
| Named input schema coverage | PASS | Every API input names None or one of 78 defined schema/query headings. |
| Prototype action coverage | PASS | All 94 parsed named action handlers have an explicit disposition; no unclassified handler. |
| Prototype form coverage | PASS | All 20 generated form IDs are mapped. |
| No unresolved action mapping | PASS | All mapped actions have named API or explicit client/demo disposition. |
| Source reference integrity | PASS | Pack HTML is byte-for-byte identical to the reviewed mounted prototype. |
| JSON example syntax | PASS | 7 JSON fenced examples parsed; shape/business acceptance remains implementation work. |
| YAML example syntax | PASS | 0 YAML fenced examples parsed where present. |
| Fixture and state inventory | PASS | 28 literal prototype fixtures span all eleven states; 27 received,20 open received,5 completed,1 rejected,1 withdrawn at baseline. |
| New-build status not fabricated | PASS | New application phases and core tests retain initial unexecuted labels. |
| Offline visit preservation | PASS | Report and failed-visit operation variants are explicitly specified. |
| No unbound demo policy start | PASS | Demo policy starts before ordinary baseline receipts; historical expired fixture uses a separately scoped archived profile. |
| All30 requirement trace rows | PASS | Each maps to a known screen, API, build phase and six core tests. |
| Code fence pairing | PASS | All 29 Markdown files have balanced triple-backtick fences. |

## 2. Inventory at delivery

The pack contains25 numbered specification documents, three root Markdown entrypoints and one reference README: **29 Markdown files**. It also includes the unchanged single-file HTML visual reference and a SHA-256 manifest. There are30 functional requirements,28 UI screen specifications,15 application-transition contracts,123 API method/path contracts,51 stable error codes,21 build phases and180 core acceptance cases plus explicitly named additional fault tests. The test plan also defines broader fault, access, performance and recovery matrices.

There are4 Mermaid code blocks for architecture/workflow/data/sequence visualization. They are editable diagram source, not raster screenshots. Markdown/Mermaid renderer-specific layout has not been validated in every editor.

## 3. Manual consistency review performed

Reviewed the selected stack change against the prior architecture and recorded it explicitly rather than claiming it came from the original Flask/MongoDB blueprint. Checked the actual source action inventory, including actions on the same source line that a line-start search would miss. Preserved offline failed visits; distinguished the source Return to review command from the new clarification/reinspection route. Specified stable new manifests for conflict rebase, canonical issuance recovery, encrypted verification-token recovery, explicit stage identities and candidate-bound policy simulation.

Checked fixture receipt totals and scope partitions rather than copying chart values. Separated historical expired-certificate test data from current-profile validity. Kept API/query input definitions aligned and fixed the draft-save mapping to PATCH /applications/{id}/draft. These are specification review checks, not proof that an eventual implementation will enforce them.

## 4. What remains unverified

No backend/frontend application code was built in this deliverable. Dependency installation, image compatibility, migrations, database concurrency, file scanning, OIDC, message delivery, signing, browser sync, accessibility, performance, recovery drills and all declared acceptance tests must still be executed during their build phases. No security audit or agency/legal approval is claimed.

Static checks cannot prove semantic completeness or absence of contradictions. If an implementation uncovers an ambiguous rule or an unlisted failure, record it, resolve it with the owner where needed, update the contract and add a regression test. Do not bypass a safety invariant to make a test pass.

## 5. Delivery verification

The ZIP is assembled from the actual pack directory and its CRC integrity is checked after creation. MANIFEST.sha256 records the delivered content hashes other than itself. No font files, dependency binaries, credentials or source PDFs are included. The reference HTML contains labelled fictional demo behavior and must not be used with real confidential data.

---
[Documentation index](../README.md) | [Source register](20_SOURCE_REGISTER_AND_GLOSSARY.md) | [Implementation status](21_IMPLEMENTATION_STATUS.md)
