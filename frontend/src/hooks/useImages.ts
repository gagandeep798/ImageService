import { useState, useCallback } from 'react'
import { api } from '../lib/api'
import type { ImageRecord } from '../types/api'

export function useImages() {
  const [images, setImages] = useState<ImageRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [nextToken, setNextToken] = useState<string | undefined>()
  const [hasMore, setHasMore] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (reset = false) => {
    setLoading(true)
    setError(null)
    try {
      const token = reset ? undefined : nextToken
      const res = await api.listImages(20, token)
      setImages(prev => reset ? res.items : [...prev, ...res.items])
      setNextToken(res.next_cursor)
      setHasMore(!!res.next_cursor)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load images')
    } finally {
      setLoading(false)
    }
  }, [nextToken])

  const refresh = useCallback(() => load(true), [load])

  const removeImage = useCallback((imageId: string) => {
    setImages(prev => prev.filter(img => img.image_id !== imageId))
  }, [])

  const prependImage = useCallback((image: ImageRecord) => {
    setImages(prev => [image, ...prev])
  }, [])

  return { images, loading, hasMore, error, load, refresh, removeImage, prependImage }
}
