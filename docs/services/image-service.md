# Image Service

Handles metadata retrieval, paginated listing, and downloads for images that have completed the upload pipeline.

## Endpoints

### GET /images/{image_id} — Get metadata

Returns the public metadata for a single image. Uses a strongly-consistent DynamoDB read so callers polling immediately after upload see the latest status.

**Auth**: JWT required.

**Response 200**:
```json
{
  "data": {
    "image_id": "img_01HZ...",
    "user_id": "usr_abc",
    "title": "Sunset",
    "description": "Golden hour on the coast",
    "tags": ["nature", "sunset"],
    "status": "ACTIVE",
    "size_bytes": 2048000,
    "content_type": "image/jpeg",
    "width": 1920,
    "height": 1080,
    "thumbnail_keys": {
      "128.jpg": "thumbnails/img_01HZ.../128.jpg",
      "400.jpg": "thumbnails/img_01HZ.../400.jpg",
      "1200.jpg": "thumbnails/img_01HZ.../1200.jpg"
    },
    "created_at": "2026-05-21T10:00:00Z",
    "updated_at": "2026-05-21T10:01:00Z"
  }
}
```

**Error responses**:
- `404` — image not found or soft-deleted

---

### GET /images — List images (paginated)

**Auth**: JWT required.

**Query parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `user_id` | string | — | Filter by owner (uses `UserImagesIndex` GSI) |
| `status` | string | `ACTIVE` | Filter by status |
| `tag` | string | — | Filter by a single tag |
| `limit` | integer | `20` | Page size (max 100) |
| `cursor` | string | — | Base64-encoded pagination token from previous response |

**Response 200**:
```json
{
  "data": {
    "items": [...],
    "next_cursor": "eyJpbWFnZV9pZCI6Ii4uLiJ9",
    "count": 20
  }
}
```

When `next_cursor` is `null`, you have reached the last page. Results are always newest-first.

**Query routing**:
- `user_id` provided → queries `UserImagesIndex` GSI directly (efficient, single partition)
- `user_id` omitted → scatter-gather across all `StatusIndex` shards, merged in-memory

**Tag filtering** is applied as a DynamoDB `FilterExpression` after the index query. It is a secondary filter — the primary key narrows the result set first.

---

### DELETE /images/{image_id} — Soft delete

Sets `status = DELETED`, records `deleted_at`, and sets a 7-day TTL. The S3 object is removed asynchronously after TTL expiry via DynamoDB Streams.

**Auth**: JWT required. Caller must own the image (admins can delete any image).

**Response 200**:
```json
{"data": {"image_id": "img_01HZ...", "status": "DELETED"}}
```

**Error responses**:
- `403` — caller does not own the image
- `404` — image not found or already deleted

---

### GET /images/{image_id}/download — Download redirect

Returns a `302` redirect to a time-limited download URL. The binary never flows through Lambda.

**Auth**: JWT required.

**Response 302** with `Location` header:
- **Production**: CloudFront signed URL (1-hour TTL, edge-cached)
- **Local dev**: S3 presigned GET URL (1-hour TTL)

**Error responses**:
- `404` — image is not in `ACTIVE` status

## DynamoDB Access Patterns

| Operation | Table / Index | Key condition |
|-----------|--------------|---------------|
| Get by ID | Primary table | `PK = IMG#<id>` |
| List by user | `UserImagesIndex` | `GSI1PK = USER#<user_id>` |
| List by status | `StatusIndex` (all shards) | `GSI2PK = STATUS#<status>#<shard>` |

The `StatusIndex` uses write-sharding: the GSI partition key is `STATUS#<status>#<shard>` where `shard = MD5(image_id) % DYNAMO_GSI2_SHARD_COUNT`. Global listing fans out across all shards in parallel and merges results. See [Infrastructure](infrastructure.md) for the full schema.

## Handlers

| Handler | File |
|---------|------|
| Get | [src/handlers/get_image.py](../../src/handlers/get_image.py) |
| List | [src/handlers/list_images.py](../../src/handlers/list_images.py) |
| Delete | [src/handlers/delete_image.py](../../src/handlers/delete_image.py) |
| Download | [src/handlers/download.py](../../src/handlers/download.py) |
