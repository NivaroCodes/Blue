import { useEffect, useState } from 'react'
import { getMedia } from '../lib/api'
import type { Settings } from '../lib/model'

export function PrivateImage({ imageUrl, settings }: { imageUrl: string; settings: Settings }) {
  const [src, setSrc] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    let objectUrl = ''
    setSrc('')
    setError('')
    void getMedia(settings, imageUrl, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return
        objectUrl = URL.createObjectURL(blob)
        setSrc(objectUrl)
      })
      .catch(() => {
        if (!controller.signal.aborted) setError('Изображение пока недоступно.')
      })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [imageUrl, settings])

  if (error) return <p className="private-image-error">{error}</p>
  if (!src) return <p className="private-image-loading">Загружаем изображение…</p>
  return <img className="private-image" src={src} alt="Изображение из исходного сообщения" />
}
