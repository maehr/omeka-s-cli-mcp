# Snapshot format

A snapshot holds JSON-LD metadata and a manifest. It does not hold the original media files. Original files belong in a separate download.

**Caution.** A snapshot is not a complete backup. It holds only the records that the client can read. An anonymous client reads only public records. Use API keys for private records. The user permissions still limit the records. Other users can change records while the capture runs. The capture checks detect some of these changes, but not all of them.

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

## Publish a snapshot directory

Create the parent directory before you write a snapshot. Choose a new directory name for each writer. The writer synchronizes the files before it renames the temporary directory. On Unix it also synchronizes the temporary directory. It uses owner-only permissions where the file system supports them.

On POSIX, a competing process can create an empty directory between the destination check and rename. Use unique destination names when processes share a parent directory.
