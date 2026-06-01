import { useState, useCallback, useRef } from 'react'
import { api } from '../lib/api'
import type { ImageRecord } from '../types/api'

export function useImages() {
  const [images, setImages] = useState<ImageRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [nextToken, setNextToken] = useState<string | undefined>()
  const [hasMore, setHasMore] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const locallyAddedIdsRef = useRef<Set<string>>(new Set())

  const mergeWithLocalUploads = useCallback((freshItems: ImageRecord[], previousItems: ImageRecord[]) => {
    const freshIds = new Set(freshItems.map(item => item.image_id))
    const retainedItems = previousItems.filter(item => {
      if (!locallyAddedIdsRef.current.has(item.image_id)) return false
      if (freshIds.has(item.image_id)) {
        locallyAddedIdsRef.current.delete(item.image_id)
        return false
      }
      return item.status !== 'DELETED' && item.status !== 'ABORTED'
    })

    return [...retainedItems, ...freshItems]
  }, [])

  const load = useCallback(async (reset = false) => {
    setLoading(true)
    setError(null)
    try {
      const token = reset ? undefined : nextToken
      const res = await api.listImages(20, token)
      setImages(prev => {
        if (reset) return mergeWithLocalUploads(res.items, prev)

        const seenIds = new Set(prev.map(item => item.image_id))
        res.items.forEach(item => locallyAddedIdsRef.current.delete(item.image_id))
        return [...prev, ...res.items.filter(item => !seenIds.has(item.image_id))]
      })
      setNextToken(res.next_cursor)
      setHasMore(!!res.next_cursor)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load images')
    } finally {
      setLoading(false)
    }
  }, [mergeWithLocalUploads, nextToken])

  const refresh = useCallback(() => load(true), [load])

  const removeImage = useCallback((imageId: string) => {
    locallyAddedIdsRef.current.delete(imageId)
    setImages(prev => prev.filter(img => img.image_id !== imageId))
  }, [])

  const prependImage = useCallback((image: ImageRecord) => {
    locallyAddedIdsRef.current.add(image.image_id)
    setImages(prev => [image, ...prev.filter(item => item.image_id !== image.image_id)])
  }, [])

  return { images, loading, hasMore, error, load, refresh, removeImage, prependImage }
}
