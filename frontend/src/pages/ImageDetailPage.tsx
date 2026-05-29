import { useEffect, useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import { api } from '../lib/api'
import type { ImageRecord, ImageStatus } from '../types/api'
import s from '../styles/ImageDetailPage.module.css'

const TERMINAL: ImageStatus[] = ['ACTIVE', 'QUARANTINE', 'ABORTED', 'DELETED']

export default function ImageDetailPage() {
  const { imageId } = useParams<{ imageId: string }>()
  const navigate = useNavigate()
  const [image, setImage] = useState<ImageRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function fetchImage() {
    if (!imageId) return
    try {
      const img = await api.getImage(imageId)
      setImage(img)
      if (TERMINAL.includes(img.status) && intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load image')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchImage()
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [imageId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (image && !TERMINAL.includes(image.status)) {
      intervalRef.current = setInterval(fetchImage, 5000)
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [image?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleDownload() {
    if (!imageId) return
    const { download_url } = await api.getDownloadUrl(imageId)
    window.open(download_url, '_blank')
  }

  async function handleDelete() {
    if (!imageId || !confirm('Delete this image?')) return
    await api.deleteImage(imageId)
    navigate('/')
  }

  if (loading) return <AppLayout><div className={s.stateMsg}>Loading...</div></AppLayout>
  if (error) return <AppLayout><div className={s.stateError}>{error}</div></AppLayout>
  if (!image) return null

  const rows: [string, string][] = [
    ['Status', image.status],
    ['Type', image.content_type],
    ['Size', `${Math.round(image.size_bytes / 1024)} KB`],
    ['Created', new Date(image.created_at).toLocaleString()],
    ['Updated', new Date(image.updated_at).toLocaleString()],
    ['ID', image.image_id],
  ]

  return (
    <AppLayout>
      <button onClick={() => navigate('/')} className={s.back}>← Back</button>
      <div className={s.card}>
        <h2>{image.title}</h2>
        {image.thumbnail_url && (
          <img src={image.thumbnail_url} alt={image.title} className={s.thumbnail} />
        )}
        <table className={s.table}>
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <td>{k}</td>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className={s.actions}>
          <button onClick={handleDownload} disabled={image.status !== 'ACTIVE'} className={s.btnPrimary}>Download</button>
          <button onClick={handleDelete} className={s.btnDanger}>Delete</button>
        </div>
      </div>
    </AppLayout>
  )
}
