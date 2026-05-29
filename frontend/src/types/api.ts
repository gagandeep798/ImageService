export interface ApiResponse<T> {
  data: T | null
  error: { code: string; message: string } | null
  meta: { request_id: string; timestamp: string }
}

export type ImageStatus =
  | 'PENDING'
  | 'PENDING_FINALIZE'
  | 'SCANNING'
  | 'ACTIVE'
  | 'QUARANTINE'
  | 'ABORTED'
  | 'DELETED'

export interface ImageRecord {
  image_id: string
  user_id: string
  title: string
  status: ImageStatus
  content_type: string
  size_bytes: number
  s3_key: string
  created_at: string
  updated_at: string
  thumbnail_url?: string
}

export interface ListImagesResponse {
  images: ImageRecord[]
  next_token?: string
  total: number
}

export interface InitiateUploadResponse {
  image_id: string
  upload_id: string
  s3_key: string
  chunk_size_bytes: number
}

export interface PartUrlResponse {
  upload_url: string
  part_number: number
}

export interface DownloadUrlResponse {
  download_url: string
  expires_at: string
}
