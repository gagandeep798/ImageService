import { useState, useRef } from 'react'
import { api } from '../lib/api'
import type { ImageRecord } from '../types/api'
import s from '../styles/ImageUpload.module.css'

type Phase = 'idle' | 'uploading' | 'done' | 'error'

interface Props {
  onSuccess: (image: ImageRecord) => void
  onClose: () => void
}

async function putChunk(presignedUrl: string, chunk: Blob): Promise<string> {
  const res = await fetch(presignedUrl, { method: 'PUT', body: chunk })
  if (!res.ok) throw new Error(`S3 upload failed: ${res.status}`)
  const etag = res.headers.get('ETag')
  if (!etag) throw new Error('No ETag in S3 response')
  return etag.replace(/"/g, '')
}

export default function ImageUpload({ onSuccess, onClose }: Props) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<{ imageId: string; uploadId: string } | null>(null)

  const maxBytes = Number(import.meta.env.VITE_MAX_IMAGE_SIZE_BYTES) || 20 * 1024 * 1024
  const chunkBytes = Number(import.meta.env.VITE_CHUNK_SIZE_BYTES) || 5 * 1024 * 1024

  async function upload(file: File) {
    if (file.size > maxBytes) {
      setError(`File too large. Max ${Math.round(maxBytes / 1024 / 1024)} MB.`)
      return
    }
    setPhase('uploading')
    setProgress(0)
    setError(null)
    try {
      const init = await api.initiateUpload(file.name, file.type, file.size)
      abortRef.current = { imageId: init.image_id, uploadId: init.upload_id }
      const totalChunks = Math.ceil(file.size / chunkBytes)
      const parts: { part_number: number; etag: string }[] = []
      for (let i = 0; i < totalChunks; i++) {
        const chunk = file.slice(i * chunkBytes, (i + 1) * chunkBytes)
        const { upload_url } = await api.getPartUrl(init.image_id, i + 1, init.upload_id)
        const etag = await putChunk(upload_url, chunk)
        parts.push({ part_number: i + 1, etag })
        setProgress(Math.round(((i + 1) / totalChunks) * 100))
      }
      await api.completeUpload(init.image_id, init.upload_id, parts)
      abortRef.current = null
      const image = await api.getImage(init.image_id)
      setPhase('done')
      onSuccess(image)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
      setPhase('error')
      if (abortRef.current) {
        api.abortUpload(abortRef.current.imageId, abortRef.current.uploadId).catch(() => {})
        abortRef.current = null
      }
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) upload(file)
  }

  return (
    <div className={s.overlay}>
      <div className={s.modal}>
        <div className={s.header}>
          <h2>Upload image</h2>
          <button onClick={onClose} className={s.closeBtn}>×</button>
        </div>

        {(phase === 'idle' || phase === 'error') && (
          <div
            className={s.dropzone}
            data-dragover={dragOver}
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
          >
            <div className={s.dropIcon}>📁</div>
            <div className={s.dropText}>Drop an image here or <span className={s.dropLink}>browse</span></div>
            <div className={s.dropHint}>Max {Math.round(maxBytes / 1024 / 1024)} MB</div>
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              className={s.fileInput}
              onChange={e => { const f = e.target.files?.[0]; if (f) upload(f) }}
            />
          </div>
        )}

        {phase === 'uploading' && (
          <div>
            <div className={s.progressLabel}>Uploading... {progress}%</div>
            <div className={s.progressTrack}>
              <div className={s.progressFill} style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}

        {phase === 'done' && <div className={s.done}>✓ Upload complete</div>}
        {error && <div className={s.errorMsg}>{error}</div>}
      </div>
    </div>
  )
}
