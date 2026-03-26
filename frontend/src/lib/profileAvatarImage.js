/** Max edge length after resize; keeps localStorage usage reasonable. */
const MAX_EDGE_PX = 384
/** Target max encoded size (bytes) for JPEG blob. */
const MAX_BYTES = 280_000

/**
 * Resize and compress an image file to a JPEG data URL for local profile storage.
 * @param {File} file
 * @returns {Promise<string>}
 */
export function fileToProfileAvatarDataUrl(file) {
  if (!file || !file.type.startsWith('image/')) {
    return Promise.reject(new Error('Choose an image file.'))
  }

  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const src = reader.result
      if (typeof src !== 'string') {
        reject(new Error('Could not read file.'))
        return
      }
      const img = new Image()
      img.onload = () => {
        let { naturalWidth: w, naturalHeight: h } = img
        if (!w || !h) {
          reject(new Error('Invalid image.'))
          return
        }
        const scale = Math.min(1, MAX_EDGE_PX / Math.max(w, h))
        const cw = Math.max(1, Math.round(w * scale))
        const ch = Math.max(1, Math.round(h * scale))
        const canvas = document.createElement('canvas')
        canvas.width = cw
        canvas.height = ch
        const ctx = canvas.getContext('2d')
        if (!ctx) {
          reject(new Error('Could not process image.'))
          return
        }
        ctx.drawImage(img, 0, 0, cw, ch)

        const tryBlob = (q) =>
          new Promise((res) => {
            canvas.toBlob((blob) => res(blob), 'image/jpeg', q)
          })

        ;(async () => {
          for (let q = 0.9; q >= 0.45; q -= 0.05) {
            const blob = await tryBlob(q)
            if (blob && blob.size <= MAX_BYTES) {
              const r2 = new FileReader()
              r2.onload = () => {
                if (typeof r2.result === 'string') resolve(r2.result)
                else reject(new Error('Encode failed.'))
              }
              r2.onerror = () => reject(new Error('Encode failed.'))
              r2.readAsDataURL(blob)
              return
            }
          }
          reject(new Error('Image is still too large. Try a smaller or simpler image.'))
        })().catch(reject)
      }
      img.onerror = () => reject(new Error('Could not load image.'))
      img.src = src
    }
    reader.onerror = () => reject(new Error('Could not read file.'))
    reader.readAsDataURL(file)
  })
}
