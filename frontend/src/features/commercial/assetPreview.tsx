/**
 * 素材预览组件：鉴权 blob 加载（图片缩略 / 音频试听 / 视频播放）。
 * 走 GET /api/commercial/assets/{id}/download + Bearer，不公开私有存储；
 * 加载失败显示占位（不伪造缩略图）。
 */
import { useEffect, useState } from 'react'
import { API_BASE } from '../../api/client'

export function useAssetBlobUrl(assetId: number | null | undefined) {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    setUrl(null); setFailed(false)
    if (!assetId) return
    let revoke: string | null = null
    fetch(`${API_BASE}/api/commercial/assets/${assetId}/download`, {
      headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
    })
      .then(r => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then(blob => {
        revoke = URL.createObjectURL(blob)
        setUrl(revoke)
      })
      .catch(() => setFailed(true))
    return () => { if (revoke) URL.revokeObjectURL(revoke) }
  }, [assetId])
  return { url, failed }
}

export function AssetImage({ assetId, alt, size = 72 }: { assetId: number | null | undefined; alt: string; size?: number }) {
  const { url, failed } = useAssetBlobUrl(assetId)
  if (!assetId) return null
  if (failed) {
    return (
      <div className="cv-thumb" style={{ width: size, height: size, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, color: 'var(--pf-muted)' }}>
        预览失败
      </div>
    )
  }
  if (!url) {
    return <div className="cv-thumb" style={{ width: size, height: size, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, color: 'var(--pf-muted)' }}>加载中…</div>
  }
  return <img className="cv-thumb" src={url} alt={alt} style={{ width: size, height: size }} />
}

export function AssetAudio({ assetId }: { assetId: number | null | undefined }) {
  const { url, failed } = useAssetBlobUrl(assetId)
  if (!assetId) return null
  if (failed) return <span className="pf-muted" style={{ fontSize: 12 }}>试听加载失败</span>
  if (!url) return <span className="pf-muted" style={{ fontSize: 12 }}>试听加载中…</span>
  return <audio controls preload="none" src={url} style={{ height: 32, maxWidth: 260 }} />
}
