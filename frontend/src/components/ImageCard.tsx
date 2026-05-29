import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { ImageRecord } from '../types/api'
import s from '../styles/ImageCard.module.css'

const STATUS_COLOR: Record<string, string> = {
  ACTIVE: '#52c41a',
  SCANNING: '#faad14',
  PENDING: '#faad14',
  PENDING_FINALIZE: '#faad14',
  QUARANTINE: '#f5222d',
  ABORTED: '#999',
  DELETED: '#999',
}

export default function ImageCard({ image, onDelete }: { image: ImageRecord; onDelete: () => void }) {
  const navigate = useNavigate()
  const [deleting, setDeleting] = useState(false)

  async function handleDownload(e: React.MouseEvent) {
    e.stopPropagation()
    const { download_url } = await api.getDownloadUrl(image.image_id)
    window.open(download_url, '_blank')
  }

  async function handleDelete(e: React.MouseEvent) {
    e.stopPropagation()
    if (!confirm('Delete this image?')) return
    setDeleting(true)
    try {
      await api.deleteImage(image.image_id)
      onDelete()
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className={s.card} onClick={() => navigate(`/images/${image.image_id}`)}>
      <div className={s.thumb}>
        {image.thumbnail_url
          ? <img src={image.thumbnail_url} alt={image.title} />
          : <span className={s.thumbIcon}>🖼</span>
        }
      </div>
      <div className={s.body}>
        <div className={s.title}>{image.title}</div>
        <div className={s.meta}>
          <span
            className={s.status}
            style={{ '--status-color': STATUS_COLOR[image.status] } as React.CSSProperties}
          >
            {image.status}
          </span>
          <span className={s.size}>{Math.round(image.size_bytes / 1024)} KB</span>
        </div>
        <div className={s.actions}>
          <button onClick={handleDownload} className={s.btn}>Download</button>
          <button onClick={handleDelete} disabled={deleting} className={`${s.btn} ${s.btnDelete}`}>
            {deleting ? '...' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  )
}
