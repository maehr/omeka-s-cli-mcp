# Command line

Install the `[cli]` extra. [Installation](../README.md#install-the-prototype)

Set `OMEKA_URL` to your Omeka S installation URL. For authenticated reads and writes, set `OMEKA_KEY_IDENTITY` and `OMEKA_KEY_CREDENTIAL`. Set `OMEKA_TIMEOUT` to change the 30-second timeout.

Use `--env-file PATH` to load a settings file. Put global options before the command. Use `--key-credential-file PATH` when the credential is in a separate file. Keep that file private.

```sh
omeka-s --url https://example.org resources
omeka-s get items 1
omeka-s list items --filter item_set_id=7 --verify
omeka-s list items --property dcterms:identifier eq abc --jsonl --output items.jsonl
omeka-s page media --page 2 --per-page 10 --filter item_id=1
omeka-s download https://example.org/files/original/example.png example.png
omeka-s snapshot capture 7 snapshot-7 --variant raw
omeka-s snapshot check snapshot-7
```

Repeat `--filter` or `--property` to pass more conditions. Supply a JSON array of integer IDs to `--expected-ids FILE`. This option enables verification. Use `--jsonl` to write one JSON record per line.

## Write commands

Review a preview before you send the request. Run the command with `--dry-run` to get the preview.

```sh
omeka-s create items --payload item.json --file image.png --dry-run
omeka-s create assets --payload asset.json --asset-file image.png --dry-run
omeka-s patch items 1 --payload replacement.json --replace-rdf-values --dry-run
```

Each payload file holds one JSON object. The CLI uses the same RDF replacement rules as the Python API. [Python API](usage.md#write-records)

## Output and exit codes

The CLI prints results to standard output. It prints errors to standard error.

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Omeka operation error |
| 2 | Invalid option, settings, or input |
| 3 | Incomplete verified listing |
| 4 | Write outcome unknown |

Use `omeka-s --help` for the command list. Use `omeka-s COMMAND --help` for command options.
