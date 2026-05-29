import ImageCard from './ImageCard'
import type { ImageRecord } from '../types/api'
import s from '../styles/ImageGrid.module.css'

interface Props {
  images: ImageRecord[]
  loading: boolean
  hasMore: boolean
  error: string | null
  onLoadMore: () => void
  onDelete: (imageId: string) => void
}

export default function ImageGrid({ images, loading, hasMore, error, onLoadMore, onDelete }: Props) {
  if (error) return <div className={s.error}>{error}</div>
  if (!loading && images.length === 0) return <div className={s.empty}>No images yet. Upload one to get started.</div>

  return (
    <div>
      <div className={s.grid}>
        {images.map(img => (
          <ImageCard key={img.image_id} image={img} onDelete={() => onDelete(img.image_id)} />
        ))}
      </div>
      {hasMore && (
        <div className={s.loadMore}>
          <button onClick={onLoadMore} disabled={loading} className={s.loadMoreBtn}>
            {loading ? 'Loading...' : 'Load more'}
          </button>
        </div>
      )}
      {loading && images.length === 0 && <div className={s.loading}>Loading...</div>}
    </div>
  )
}
