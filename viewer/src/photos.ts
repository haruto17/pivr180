export type Photo = { name: string; url: string }

function isPhoto(value: unknown): value is Photo {
  if (typeof value !== 'object' || value === null) return false
  const { name, url } = value as Record<string, unknown>
  return typeof name === 'string' && typeof url === 'string'
}

export async function fetchPhotos(fetchFn: typeof fetch = fetch): Promise<Photo[]> {
  const response = await fetchFn('/api/photos')
  if (!response.ok) throw new Error(`写真一覧を取得できませんでした（HTTP ${response.status}）`)
  const body: unknown = await response.json().catch(() => undefined)
  if (!Array.isArray(body) || !body.every(isPhoto)) throw new Error('写真一覧の形式が正しくありません')
  return body
}
