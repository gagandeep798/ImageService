# Processing Pipeline

After an upload completes, the image passes through a three-stage async pipeline before becoming visible via the API.

## Pipeline Overview

```
S3 ObjectCreated
      │
      ▼
SQS FinalizeQueue (max 3 attempts → FinalizeDLQ)
      │
      ▼
finalize_upload Lambda
  - Read file size and dimensions via S3 HeadObject + Pillow
  - Transition: PENDING_FINALIZE → SCANNING
  - Increment user image_count
      │
      ▼
SQS ScanQueue (max 3 attempts → ScanDLQ)
      │
      ▼
scan_complete Lambda
  ├── CLEAN  → status = ACTIVE
  └── THREAT → move object to quarantine bucket → status = QUARANTINE
      │
      ▼ (ACTIVE only)
SQS ThumbnailQueue
      │
      ▼
generate_thumbnails Lambda
  - Generate 128px, 400px, 1200px JPEG variants
  - Strip EXIF metadata (GPS, camera info)
  - Upload to thumbnails bucket
  - Store thumbnail_keys on DynamoDB record
```

## Stage 1 — Finalize Upload

**Trigger**: S3 `ObjectCreated` event → SQS `FinalizeQueue`

**Handler**: [src/handlers/finalize_upload.py](../../src/handlers/finalize_upload.py)

**What it does**:
1. Parses `image_id` from the S3 object key (`originals/{user_id}/{year}/{month}/{image_id}/{filename}`)
2. Calls `S3.HeadObject` to get `ContentLength` and `ContentType`
3. Downloads the first 64 KB with a Range request and passes it to Pillow to extract `width` and `height`
4. Updates DynamoDB: `status = SCANNING`, `size_bytes`, `width`, `height`
5. Increments the owner's `image_count`

**On failure**: Re-raises the exception so SQS retries. After 3 attempts the message moves to `FinalizeDLQ` and triggers a CloudWatch alarm.

---

## Stage 2 — Virus / Malware Scan

**Trigger**: SQS `ScanQueue`

**Handler**: [src/handlers/scan_complete.py](../../src/handlers/scan_complete.py)

The scan result message contains `{image_id, result}` where `result` is `CLEAN` or `THREAT`.

**CLEAN path**:
- `status = ACTIVE`
- Image becomes visible via the API

**THREAT path**:
- S3 object is copied to `image-service-quarantine` bucket (SSE-KMS encrypted, separate key)
- Original object deleted from `image-service-originals`
- `status = QUARANTINE`
- CloudWatch `scan.threat_detected` metric fires immediately → SNS → PagerDuty

> The scan Lambda processes the *result* of an external scanner (e.g., Amazon GuardDuty Malware Protection, ClamAV Lambda layer). Plugging in a specific scanner requires publishing to `ScanQueue` with `{image_id, result}` on scan completion.

---

## Stage 3 — Thumbnail Generation

**Trigger**: EventBridge rule on `status = ACTIVE` → SQS `ThumbnailQueue`

**Handler**: [src/handlers/generate_thumbnails.py](../../src/handlers/generate_thumbnails.py)

**Variants generated**:

| Variant | Max dimensions | Key pattern |
|---------|---------------|-------------|
| `128.jpg` | 128 × 128 | `thumbnails/{image_id}/128.jpg` |
| `400.jpg` | 400 × 400 | `thumbnails/{image_id}/400.jpg` |
| `1200.jpg` | 1200 × 900 | `thumbnails/{image_id}/1200.jpg` |

**EXIF stripping**: Pillow's `ImageOps.exif_transpose` corrects orientation, then the image is re-saved as JPEG without the EXIF segment. This removes GPS coordinates, camera make/model, and owner metadata before the thumbnails are stored.

**Cache headers**: Thumbnails are uploaded with `Cache-Control: public, max-age=86400` so CloudFront caches them for 24 hours.

---

## SQS Configuration

| Queue | Visibility timeout | Max attempts | DLQ |
|-------|--------------------|--------------|-----|
| `FinalizeQueue` | 60 s | 3 | `FinalizeDLQ` |
| `ScanQueue` | 120 s | 3 | `ScanDLQ` |
| `ThumbnailQueue` | 120 s | — | — |

Both DLQs have a CloudWatch alarm on `ApproximateNumberOfMessagesVisible > 0`.

See [Incident Response](../activities/incident-response.md) for what to do when a DLQ has messages.

## Image Status Reference

| Status | Meaning |
|--------|---------|
| `PENDING` | Upload initiated; parts not yet uploaded |
| `PENDING_FINALIZE` | All parts uploaded; S3 assembled the object |
| `SCANNING` | Object received by finalize Lambda; awaiting scan result |
| `ACTIVE` | Clean scan; visible via API |
| `QUARANTINE` | Threat detected; object moved to quarantine bucket |
| `DELETED` | Soft-deleted; TTL set for 7-day async cleanup |
| `ABORTED` | Upload aborted by client or operator |
