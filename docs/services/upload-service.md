# Upload Service

Handles the full lifecycle of a chunked multipart image upload. Binary data never flows through Lambda — the client uploads directly to S3 using presigned URLs.

## Three-Step Flow

```
Client                   Lambda                  DynamoDB        S3
  │                         │                       │             │
  │  POST /images ──────────►                       │             │
  │  {filename, content_type, total_size_bytes}      │             │
  │                         │  1. Validate metadata  │             │
  │                         │  2. Check quota ───────►             │
  │                         │  3. Write PENDING ──────►            │
  │                         │  4. CreateMultipartUpload ──────────►│
  │  ◄── 202 {image_id, upload_id, s3_key} ─────────│             │
  │                                                  │             │
  │  POST /images/{id}/parts ───────────────────────►│             │
  │  {upload_id, part_number, size_bytes}             │             │
  │                         │  5. Generate presigned UploadPart URL│
  │  ◄── 200 {presigned_part_url} ───────────────────│             │
  │                                                  │             │
  │  PUT <presigned_part_url> (binary) ─────────────────────────►│
  │  ◄── 200 ETag ──────────────────────────────────────────────◄│
  │  (repeat for each chunk)                                       │
  │                                                  │             │
  │  POST /images/{id}/complete ────────────────────►│             │
  │  {upload_id, parts: [{part_number, etag}]}        │             │
  │                         │  6. CompleteMultipartUpload ────────►│
  │                         │  7. Set PENDING_FINALIZE ──────────►│
  │  ◄── 200 {status: "PROCESSING"} ────────────────│             │
  │                                                               │
  │          S3 ObjectCreated event ──► SQS ──► finalize Lambda   │
```

## Endpoints

### POST /images — Initiate upload

**Auth**: JWT required. `user_id` in the body must match the JWT `sub` claim.

**Request body**:
```json
{
  "user_id": "usr_01HZ...",
  "filename": "photo.jpg",
  "content_type": "image/jpeg",
  "total_size_bytes": 10485760,
  "title": "Sunset",
  "description": "Optional description",
  "tags": ["nature", "travel"]
}
```

**Allowed content types**: `image/jpeg`, `image/png`, `image/webp`, `image/gif`

**Response 202**:
```json
{
  "data": {
    "image_id": "img_01HZ...",
    "upload_id": "s3-multipart-upload-id",
    "s3_key": "originals/usr_01HZ.../2026/05/img_01HZ.../photo.jpg",
    "chunk_size_bytes": 5242880,
    "status": "PENDING"
  }
}
```

**Error responses**:
- `400` — invalid content type, missing fields, file exceeds 20 MB limit
- `402` — storage quota exceeded
- `403` — `user_id` does not match JWT `sub`

---

### POST /images/{image_id}/parts — Upload a chunk

**Request body**:
```json
{
  "upload_id": "s3-multipart-upload-id",
  "part_number": 1,
  "size_bytes": 5242880
}
```

**Response 200**:
```json
{
  "data": {
    "presigned_part_url": "https://s3.amazonaws.com/...",
    "part_number": 1
  }
}
```

The client PUTs the chunk binary directly to `presigned_part_url` and stores the returned `ETag` for the complete call. Minimum part size: 5 MB (S3 requirement), except the last part.

---

### POST /images/{image_id}/complete — Finalise upload

**Request body**:
```json
{
  "upload_id": "s3-multipart-upload-id",
  "parts": [
    {"part_number": 1, "etag": "\"abc123\""},
    {"part_number": 2, "etag": "\"def456\""}
  ]
}
```

**Response 200**:
```json
{"data": {"image_id": "img_01HZ...", "status": "PROCESSING"}}
```

After this returns, the image enters the [processing pipeline](processing-pipeline.md).

---

### DELETE /images/{image_id}/upload — Abort upload

Cancels the S3 multipart session, releases reserved quota, and marks the record `ABORTED`.

**Response 200**:
```json
{"data": {"image_id": "img_01HZ...", "status": "ABORTED"}}
```

## Resume After Crash

If the client crashes mid-upload, it can resume without re-uploading completed parts:

1. Call `POST /images/{id}/parts` with the same `upload_id` — the server returns the presigned URL
2. The handler checks the `parts` map in DynamoDB; already-completed parts have their ETag stored
3. The client skips parts that already have an ETag and uploads only the remaining ones
4. Call `POST /images/{id}/complete` with all parts (including already-uploaded ones)

## Image Status State Machine

```
PENDING → PENDING_FINALIZE → SCANNING → ACTIVE
                                      → QUARANTINE
        → ABORTED   (upload aborted)
ACTIVE  → DELETED   (soft delete)
```

## Quota Enforcement

`upload_initiate` performs an atomic DynamoDB conditional `UpdateItem`:

```
storage_used_bytes + new_size <= storage_quota_bytes  AND  status = ACTIVE
```

If the condition fails a `402 Quota Exceeded` is returned. The quota is released if the upload is aborted or the image is deleted.

Default quota: **10 GB** per user. Adjust via the `storage_quota_bytes` field on the user record.

## Handlers

| Handler | File |
|---------|------|
| Initiate | [src/handlers/upload_initiate.py](../../src/handlers/upload_initiate.py) |
| Part URL | [src/handlers/upload_part.py](../../src/handlers/upload_part.py) |
| Complete | [src/handlers/upload_complete.py](../../src/handlers/upload_complete.py) |
| Abort | [src/handlers/upload_abort.py](../../src/handlers/upload_abort.py) |
| Finalize (async) | [src/handlers/finalize_upload.py](../../src/handlers/finalize_upload.py) |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_IMAGE_SIZE_BYTES` | `20971520` | Maximum file size (20 MB) |
| `CHUNK_SIZE_BYTES` | `5242880` | Recommended chunk size returned to client (5 MB) |
| `UPLOAD_URL_TTL_SECONDS` | `900` | Presigned part URL validity (15 min) |
