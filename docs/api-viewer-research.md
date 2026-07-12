# Proxmox VE API Viewer research

Research was performed on 2026-07-12 against the official documentation hosted
by Proxmox Server Solutions GmbH.

## Discovered source

The HTML application at
[`https://pve.proxmox.com/pve-docs/api-viewer/`](https://pve.proxmox.com/pve-docs/api-viewer/)
loads ExtJS and one application resource, `apidoc.js`. The machine-readable API
tree is not fetched from a separate JSON endpoint: it is embedded at the start
of [`apidoc.js`](https://pve.proxmox.com/pve-docs/api-viewer/apidoc.js) as a
JavaScript declaration named `apiSchema`. The remainder of that file renders the
tree and method documentation.

At retrieval, the artifact was 4,277,440 bytes with SHA-256
`f2b77b57c71f3781a0993cc5062940ef31e0843fd9a6bcfdb4de4dd2001d6d9e`.
The server reported `Last-Modified: Fri, 03 Jul 2026 09:08:20 GMT` and ETag
`"4144c0-655b144140900"`.

The adjacent official documentation index identifies the generated
documentation as Proxmox VE `9.2.3`, dated `Fri Jul 3 11:08:20 CEST 2026`. Its
timestamp matches the artifact's HTTP last-modified time after timezone
conversion. This is strong evidence that the current unversioned viewer belongs
to that documentation build, but the artifact does not contain a dedicated
top-level snapshot-version field. Importers must therefore record the index
version and HTTP metadata as provenance rather than infer a version from an API
method schema.

## Format and limitations

`apiSchema` is a nested tree of path nodes. Nodes may contain `children`, an
`info` mapping keyed by HTTP method, `path`, `text`, and `leaf`. Method objects
contain parameter and return schemas, permissions, descriptions, and flags.
The schema resembles JSON Schema but is a Proxmox-specific dialect and includes
fields such as `typetext`, `format_description`, `instance-types`, and numeric
booleans. Unknown fields must be retained.

The artifact is executable JavaScript, not JSON. A parser must extract only the
declaration value without evaluating the downloaded program. The URL is
unversioned and changes in place. Formatting, declaration syntax, variable name,
tree shape, or bundling may change without notice. Documentation describes the
declared contract; it does not prove runtime behavior or exact error text for a
particular installed cluster.

## Offline fallback and sample

The repository stores an extracted, otherwise semantically unmodified `/version`
node at
[`tests/fixtures/api-viewer/pve-9.2.3-version.json`](../tests/fixtures/api-viewer/pve-9.2.3-version.json).
It is deliberately small enough for deterministic parser tests and retains all
fields from that source node. Its checksum is recorded in the companion
provenance file. Network retrieval is research/import functionality only; the
default test suite must use this checked-in fixture.

The fixture is not a complete snapshot and must never be used to claim broad
Proxmox compatibility. Full imports should preserve the immutable raw
`apidoc.js`, response metadata, retrieval timestamp, and checksum outside the
small test-fixture path.

## Parser boundary

`app.contracts.source.ApiViewerParser` accepts either the saved JSON sample or
the official JavaScript wrapper. It locates the exact `const apiSchema`
assignment, scans the balanced JSON value while respecting escaped strings, and
decodes only that value; no downloaded JavaScript is evaluated. Recoverable
tree variations produce structured warnings and unknown node fields remain in
the parsed dictionaries. `SourceImporter` and `LocalFileImporter` keep artifact
retrieval separate from parsing so later remote imports can enforce their own
network policy.
