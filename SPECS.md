# Omeka S Python client

## Purpose

Build an independent Python library for the Omeka S REST API. Publish the library on the Python Package Index (PyPI).

`sgb-data-validator` uses the library to read, create, and update Omeka records. `omeka2dsp` uses it to read Omeka records and download files. Both tools can read the same metadata snapshots.

The proposed distribution name is `omeka-s-client`. The proposed import name is `omeka_s_client`. The first release contains a synchronous library for Python 3.11 and later. A command-line interface or Model Context Protocol (MCP) server can use the same library in a later release.

## Package boundaries

| Library responsibility | Responsibility of the calling tool |
| --- | --- |
| HTTP requests, authentication, pagination, and errors | Configuration from environment variables and files |
| JSON-LD records, property filters, and resource relationships | SGB metadata rules, vocabularies, reports, and text cleanup |
| Metadata snapshot capture and file format | Edit previews, backups with files, and recovery |
| Multipart uploads and streamed downloads | Placeholder rules, destination permissions, and DSP mapping |

The library supports Omeka S. Support for Omeka Classic is outside the first release. The library supports standard API resources and custom resource names. Custom names must identify a single endpoint under the API root.

## Public Python API

A record is a JSON object from Omeka S. JSON-LD means JavaScript Object Notation for Linked Data. Use typed signatures for functions and result objects. Preserve unknown record keys and value types.

| Operation | Contract |
| --- | --- |
| `OmekaClient(base_url, *, key_identity=None, key_credential=None, timeout=...)` | Open a reusable HTTP client. Provide `close()` and support the context manager protocol. |
| `get(resource, id)` | Read one record by ID. |
| `list(resource, *, filters=None, per_page=50, verify=False, expected_ids=None)` | Return all records in page order. An expected ID set always enables verification. |
| `create(resource, payload, *, files=None)` | Send JSON or multipart data. Return the created record. |
| `patch(resource, id, payload, *, replace_rdf_values=False)` | Send a partial update. Return the updated record. |
| `download(url, destination)` | Stream a file to a new local path. Return its byte count and SHA-256 digest. |
| `capture_snapshot(client, item_set_id)` | Read an item set, its items, and their media. Return a `Snapshot`. |
| `read_snapshot(directory)` | Load a snapshot from disk. |
| `write_snapshot(directory, snapshot)` | Write a snapshot to a new directory. |

Expose a helper that builds Omeka property filters from a caller-supplied property term or ID, comparison type, and value. Allow bracketed keys and repeated query keys. Retain all matches so callers can detect duplicate identifiers.

The public API uses library types and standard Python types. Use one HTTP dependency. Keep its request and response types private. Provide an injectable transport for offline tests.

## HTTP and authentication

- Accept the installation URL or its `/api` URL. Preserve installation paths such as `/collections`.
- Accept public requests without credentials. Require both keys when the caller supplies credentials.
- Add Omeka keys only to requests under the configured API root. Remove keys from logs and exceptions.
- Reject redirects that leave the API root. Validate pagination links against the same rule.
- Use a separate request path for original files. These requests carry no API keys, including when a file server redirects them.
- Set a finite timeout on every request. Keep TLS certificate verification on.
- Retry transient read failures within a fixed limit. Apply the limit to connection failures and temporary HTTP failures.
- Send each write once. If the response is lost, report that the outcome is unknown.
- Report HTTP status, resource, and operation through library errors. Give invalid responses and incomplete listings distinct error types.

[Omeka S REST API](https://omeka.org/s/docs/developer/api/rest_api/) · [Omeka S API reference](https://omeka.org/s/docs/developer/api/api_reference/)

## Pagination and verified reads

Follow `Link: rel="next"` when the server provides it. Preserve the caller's filters and send credentials only to the configured API root. Use page numbers for verified listings when the server omits next links and more records are expected.

Use stable ID order for verified listings. Check the number of unique IDs against `Omeka-S-Total-Results` when the header is present. If the caller supplies expected IDs, require an exact match. A verified listing requires a valid count or expected IDs.

Detect duplicate IDs, repeated page links, and inconsistent counts. If verification fails, retry the entire read within a fixed limit. Return an error if the failure repeats. Return results only after all pages succeed.

When capturing an item set, confirm item membership with a second read in reverse ID order. Verify media against the item references when Omeka supplies them. Check that each media record belongs to the expected parent. Report any mismatch before returning the snapshot. These checks detect some concurrent changes. They cannot establish a single point in time across requests.

## JSON-LD, writes, and files

Keep each property term and its full list of values. Preserve literals, URI values, resource references, language tags, and module fields. Leave Dublin Core selection and application-specific validation to the calling tool.

For multipart requests, send the JSON payload in the `data` field. Use `file[0]`, `file[1]`, and further indexed fields for media. Let the caller supply matching `file_index` values. Support the unindexed `file` field for assets.

**Caution.** Omeka S treats the RDF values of a record as one field during a patch. A payload with RDF values can remove values that the caller omits.

Require explicit `replace_rdf_values=True` for a patch that contains RDF properties or `clear_property_values`. The caller supplies the complete set of values to retain. Direct create and patch calls perform real writes. The calling tool controls previews, conflict checks, and verification after a write. Deletion and full replacement with PUT are outside the first release.

Stream downloads to a private temporary file. Publish the destination only after the download succeeds. Reject an existing destination. Remove the temporary file if the download fails. Return the actual byte count and SHA-256 digest to the caller for optional integrity checks.

[Omeka S REST API write semantics](https://omeka.org/s/docs/developer/api/rest_api/) · [Omeka S JSON-LD values](https://omeka.org/s/docs/developer/api/rest_api_reference/)

## Snapshot format

A snapshot contains an item set record, item records, media records, and the source installation URL. The format covers metadata. Original files and recovery manifests belong to the calling tool.

Write `item_set.json`, `items.json`, `media.json`, and `snapshot.json`. Use UTF-8. Store items and media as arrays. Put the source URL, item set ID, and counts in the manifest. Use owner-only permissions where supported. Make the directory available at its final path only after all files succeed.

Read existing files with the `_transformed`, plain, and `_raw` suffixes, in that order for each record group. Accept an absent item set file in a legacy snapshot. Accept a single object in a legacy item or media file. Check counts in `snapshot.json`, `transformation_metadata.json`, and `download_metadata.json` when present. Reject missing item or media files and invalid record shapes.

## Consumer adoption

1. Replace the validator's HTTP client with the shared client.
2. Compare live and offline validation results on the same fixtures.
3. Replace the validator's snapshot capture and snapshot file access with the shared functions.
4. Replace the sync tool's Omeka reads and snapshot reader with the shared functions.
5. Compare DSP dry-run plans for the same live records and snapshots.
6. Keep each application's write controls and privacy checks in its existing workflow.

Each consumer chooses a release range. The shared package has no dependency on either consumer. Preserve the public Python API and snapshot compatibility across patch releases.

## Acceptance checks

- Read a public installation and an installation that uses both Omeka keys.
- Test a subdirectory installation, relative and absolute next links, and a failed page.
- Confirm that cross-origin links, redirects, logs, and errors cannot disclose keys.
- Test missing counts, repeated IDs, changing membership, and an incorrect media parent.
- Round-trip custom JSON-LD values and read legacy snapshots from both consumers.
- Reject incomplete snapshots and verify that failed writes leave no final directory.
- Test JSON writes, multipart uploads, and the explicit RDF replacement option.
- Confirm that a failed write request does not trigger a retry.
- Test streamed downloads, digest accuracy, and cleanup after a failed download.
- Build a wheel and a source distribution. Install the wheel in a clean environment.
- Run the consumer regression tests against that installed wheel.

Run the default test suite against a mock transport. Check real pagination and write semantics on a disposable Omeka S instance before release. Document the tested Omeka S and Python versions. Confirm the PyPI name and license before publication. Both source repositories identify their code as AGPL-3.0. Review license obligations before copying code.

## Implementation references

| Requirement | Existing implementation and tests |
| --- | --- |
| Omeka requests and credentials | [Validator API](../sgb-data-validator/sgb_validator/api.py) · [API tests](../sgb-data-validator/test/test_api.py) |
| Pagination and completeness | [Validator listing](../sgb-data-validator/sgb_validator/api.py#L107) · [Listing tests](../sgb-data-validator/test/test_fetch_items.py) · [DSP sync reader](../omeka2dsp_sgb/src/omeka2dsp/omeka.py) · [DSP reader tests](../omeka2dsp_sgb/test/test_omeka.py) |
| Snapshots and media relationships | [Validator snapshots](../sgb-data-validator/sgb_validator/snapshots.py) · [Offline workflow tests](../sgb-data-validator/test/test_offline_workflow.py) · [DSP sync caller](../omeka2dsp_sgb/src/omeka2dsp/sync.py#L59) |
| JSON-LD values and application models | [Validator models](../sgb-data-validator/sgb_validator/models.py) · [DSP value conversion](../omeka2dsp_sgb/src/omeka2dsp/values.py) |
| Write payloads and caller safeguards | [Validator write workflow](../sgb-data-validator/sgb_validator/writes.py) · [Validator change helpers](../sgb-data-validator/sgb_validator/changes.py) · [Write tests](../sgb-data-validator/test/test_creation.py) |
| File transfer and placeholder policy | [Validator streaming download](../sgb-data-validator/sgb_validator/recovery.py#L138) · [DSP download and ingest](../omeka2dsp_sgb/src/omeka2dsp/dsp.py#L168) · [DSP placeholder checks](../omeka2dsp_sgb/src/omeka2dsp/media.py#L54) |
| Rules that stay with the applications | [SGB validation](../sgb-data-validator/sgb_validator/validation.py) · [SGB transformations](../sgb-data-validator/sgb_validator/transformations.py) · [DSP field mapping](../omeka2dsp_sgb/src/omeka2dsp/fields.py) · [DSP preflight](../omeka2dsp_sgb/src/omeka2dsp/preflight.py) |
