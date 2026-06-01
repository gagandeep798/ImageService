import { getAccessToken } from './auth'
import type {
  ListImagesResponse,
  ImageRecord,
  InitiateUploadResponse,
  PartUrlResponse,
  DownloadUrlResponse,
  ApiResponse,
} from '../types/api'

export class ApiError extends Error {
  constructor(public code: string, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = await getAccessToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  const envelope: ApiResponse<T> = await res.json()
  if (envelope.error) throw new ApiError(envelope.error.code, envelope.error.message)
  return envelope.data as T
}

export const api = {
  initiateUpload(filename: string, contentType: string, sizeBytes: number) {
    return request<InitiateUploadResponse>('POST', '/images', {
      filename,
      content_type: contentType,
      total_size_bytes: sizeBytes,
    })
  },

  getPartUrl(imageId: string, partNumber: number, uploadId: string) {
    return request<PartUrlResponse>('POST', `/images/${imageId}/parts`, {
      part_number: partNumber,
      upload_id: uploadId,
    })
  },

  completeUpload(imageId: string, uploadId: string, parts: { part_number: number; etag: string }[]) {
    return request<void>('POST', `/images/${imageId}/complete`, { upload_id: uploadId, parts })
  },

  abortUpload(imageId: string, uploadId: string) {
    return request<void>('DELETE', `/images/${imageId}/upload`, { upload_id: uploadId })
  },

  listImages(limit = 20, nextToken?: string) {
    const params = new URLSearchParams({ limit: String(limit) })
    if (nextToken) params.set('cursor', nextToken)
    return request<ListImagesResponse>('GET', `/images?${params}`)
  },

  getImage(imageId: string) {
    return request<ImageRecord>('GET', `/images/${imageId}`)
  },

  getDownloadUrl(imageId: string) {
    return request<DownloadUrlResponse>('GET', `/images/${imageId}/download`)
  },

  deleteImage(imageId: string) {
    return request<void>('DELETE', `/images/${imageId}`)
  },

  deleteUser(userId: string) {
    return request<void>('DELETE', `/users/${userId}`)
  },
}
