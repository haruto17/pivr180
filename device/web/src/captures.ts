import './captures.css'

export interface CaptureSummary {
  id: string
  complete: boolean
  sync_warning: boolean | null
}

export interface CapturesDeps {
  fetch?: (input: string, init?: RequestInit) => Promise<Response>
  confirm?: (message: string) => boolean
}

const API = '/api/captures'
const CAPTURE_ID = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})-\d{3}$/
const SIDES = [
  ['left', '左'],
  ['right', '右'],
] as const

export function captureTime(id: string): Date | null {
  const match = CAPTURE_ID.exec(id)
  if (match === null) {
    return null
  }
  const [year, month, day, hour, minute, second] = match.slice(1).map(Number)
  return new Date(Date.UTC(year, month - 1, day, hour, minute, second))
}

export function thumbnailUrl(id: string, side: 'left' | 'right'): string {
  return `${API}/${encodeURIComponent(id)}/thumbnails/${side}`
}

export async function renderCaptures(
  root: HTMLElement,
  deps: CapturesDeps = {},
): Promise<void> {
  const request = deps.fetch ?? ((input, init) => fetch(input, init))
  const ask = deps.confirm ?? ((message) => window.confirm(message))

  const heading = document.createElement('h2')
  heading.textContent = '撮影データ'
  const status = document.createElement('p')
  status.className = 'captures-status'
  status.textContent = '読み込み中…'
  const list = document.createElement('ul')
  list.className = 'captures'
  root.replaceChildren(heading, status, list)

  let captures: CaptureSummary[]
  try {
    const response = await request(API)
    if (!response.ok) {
      throw new Error(`GET ${API}: ${response.status}`)
    }
    captures = (await response.json()) as CaptureSummary[]
  } catch {
    status.textContent = '撮影データを読み込めませんでした。'
    return
  }

  const showCount = (): void => {
    const count = list.children.length
    status.textContent =
      count === 0 ? '撮影データはありません。' : `${count} 件（新しい順）`
  }

  const remove = async (
    capture: CaptureSummary,
    item: HTMLLIElement,
    button: HTMLButtonElement,
  ): Promise<void> => {
    if (!ask(`${label(capture.id)} の撮影データを削除しますか？元に戻せません。`)) {
      return
    }
    button.disabled = true
    try {
      const response = await request(`${API}/${encodeURIComponent(capture.id)}`, {
        method: 'DELETE',
      })
      // Not treated as a failure: 404 means another phone already deleted it.
      if (!response.ok && response.status !== 404) {
        throw new Error(`DELETE ${capture.id}: ${response.status}`)
      }
    } catch {
      button.disabled = false
      status.textContent = `${label(capture.id)} を削除できませんでした。`
      return
    }
    item.remove()
    showCount()
  }

  for (const capture of captures) {
    const item = renderItem(capture)
    const button = item.querySelector('button')!
    button.addEventListener('click', () => {
      void remove(capture, item, button)
    })
    list.append(item)
  }
  showCount()
}

function label(id: string): string {
  return captureTime(id)?.toLocaleString('ja-JP') ?? id
}

function renderItem(capture: CaptureSummary): HTMLLIElement {
  const item = document.createElement('li')
  item.className = 'capture'
  item.dataset.id = capture.id

  const header = document.createElement('div')
  header.className = 'capture-header'
  const time = document.createElement('time')
  const taken = captureTime(capture.id)
  if (taken !== null) {
    time.dateTime = taken.toISOString()
  }
  time.textContent = label(capture.id)
  const id = document.createElement('span')
  id.className = 'capture-id'
  id.textContent = capture.id
  header.append(time, id)
  if (capture.sync_warning === true) {
    header.append(badge('同期警告'))
  }
  if (!capture.complete) {
    header.append(badge('不完全'))
  }

  const images = document.createElement('div')
  images.className = 'capture-images'
  for (const [side, name] of SIDES) {
    const image = document.createElement('img')
    image.src = thumbnailUrl(capture.id, side)
    image.alt = name
    image.loading = 'lazy'
    image.width = 480
    image.height = 360
    images.append(image)
  }

  const button = document.createElement('button')
  button.type = 'button'
  button.textContent = '削除'

  item.append(header, images, button)
  return item
}

function badge(text: string): HTMLSpanElement {
  const element = document.createElement('span')
  element.className = 'capture-badge'
  element.textContent = text
  return element
}
