export const PREVIEW_URL = '/api/preview.mjpg'
export const RETRY_MS = 3000

export function renderPreview(root: HTMLElement, retryMs = RETRY_MS): void {
  const heading = document.createElement('h2')
  heading.textContent = 'プレビュー'
  const image = document.createElement('img')
  image.alt = '左右のカメラのプレビュー'
  image.style.width = '100%'
  const status = document.createElement('p')
  status.hidden = true
  image.addEventListener('load', () => {
    status.hidden = true
  })
  image.addEventListener('error', () => {
    status.textContent = 'カメラの準備ができていません。再接続します…'
    status.hidden = false
    window.setTimeout(() => {
      // Not the same URL: assigning an unchanged src does not make the
      // browser request the stream again.
      image.src = `${PREVIEW_URL}?retry=${Date.now()}`
    }, retryMs)
  })
  image.src = PREVIEW_URL
  root.replaceChildren(heading, image, status)
}
