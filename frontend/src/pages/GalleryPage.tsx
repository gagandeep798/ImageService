import { useEffect, useState } from 'react'
import AppLayout from '../components/AppLayout'
import ImageGrid from '../components/ImageGrid'
import ImageUpload from '../components/ImageUpload'
import { useImages } from '../hooks/useImages'
import type { ImageRecord } from '../types/api'
import s from '../styles/GalleryPage.module.css'

export default function GalleryPage() {
  const { images, loading, hasMore, error, load, refresh, removeImage, prependImage } = useImages()
  const [showUpload, setShowUpload] = useState(false)

  useEffect(() => { load(true) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function handleUploadSuccess(image: ImageRecord) {
    prependImage(image)
    setShowUpload(false)
  }

  return (
    <AppLayout>
      <div className={s.toolbar}>
        <h2>My Images</h2>
        <div className={s.actions}>
          <button onClick={refresh} className={s.btnSecondary}>Refresh</button>
          <button onClick={() => setShowUpload(true)} className={s.btnPrimary}>Upload</button>
        </div>
      </div>
      <ImageGrid
        images={images}
        loading={loading}
        hasMore={hasMore}
        error={error}
        onLoadMore={() => load(false)}
        onDelete={removeImage}
      />
      {showUpload && <ImageUpload onSuccess={handleUploadSuccess} onClose={() => setShowUpload(false)} />}
    </AppLayout>
  )
}
