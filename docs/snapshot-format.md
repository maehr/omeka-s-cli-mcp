# Snapshot format

A snapshot holds JSON-LD metadata and a manifest. Original files belong in a separate download.

| Variant | Record files | Manifest |
| --- | --- | --- |
| Plain | `item_set.json`, `items.json`, `media.json` | `snapshot.json` |
| Raw | `item_set_raw.json`, `items_raw.json`, `media_raw.json` | `download_metadata.json` |
| Transformed | `item_set_transformed.json`, `items_transformed.json`, `media_transformed.json` | `transformation_metadata.json` |

The writer stores an item set object and arrays of item and media records. It omits the item set file when the snapshot has no item set. Each JSON file uses UTF-8, two-space indentation, and a final newline.

## Manifest version 1

| Field | Value |
| --- | --- |
| `format` | `omeka-s-snapshot` |
| `format_version` | `1` |
| `source` | Source installation URL |
| `item_set_id` | Item set ID or `null` |
| `items_count` | Number of item records |
| `media_count` | Number of media records |
| `created_at` | ISO 8601 timestamp in UTC |
| `files` | Map from record group to a path relative to the snapshot's parent directory |
| `status` | An empty string for plain, `raw`, or `transformed` |
| `timestamp` | UTC timestamp in `YYYYMMDD_HHMMSS` form |

Use `extra` for additional manifest fields. Reserve the fields in this table for the writer.

## Read a legacy snapshot

The reader selects the transformed, plain, or raw file for each group, in that order. The item set file is optional. The reader accepts a single item or media object and returns a list.

The reader checks the counts in each manifest. All manifest sources must agree. If a manifest does not supply a source, the reader derives it from the first record URL that contains `/api/`.

## Publish a snapshot directory

Create the parent directory before you write a snapshot. Choose a new directory name for each writer. The writer synchronizes the files before it renames the temporary directory. On Unix it also synchronizes the temporary directory. It uses owner-only permissions where the file system supports them.

On POSIX, a competing process can create an empty directory between the destination check and rename. Use unique destination names when processes share a parent directory.
