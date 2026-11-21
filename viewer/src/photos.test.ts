import { describe, expect, it, vi } from 'vitest'
import { fetchPhotos } from './photos'

function respond(body: unknown, status = 200) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status }))
}

describe('fetchPhotos', () => {
  it('returns the photos listed by the photo list API', async () => {
    const photos = [{ name: 'a_180_LR.jpg', url: '/photos/a_180_LR.jpg' }]
    const fetchFn = respond(photos)

    await expect(fetchPhotos(fetchFn)).resolves.toEqual(photos)
    expect(fetchFn).toHaveBeenCalledWith('/api/photos')
  })

  it('returns an empty list when there are no photos', async () => {
    await expect(fetchPhotos(respond([]))).resolves.toEqual([])
  })

  it('fails with the HTTP status when the API responds with an error', async () => {
    await expect(fetchPhotos(respond('oops', 500))).rejects.toThrow('HTTP 500')
  })

  it.each([{}, null, [{ name: 'a_180_LR.jpg' }], [{ name: 1, url: '/photos/a_180_LR.jpg' }], [null]])(
    'fails when the response is not a list of photos: %j',
    async (body) => {
      await expect(fetchPhotos(respond(body))).rejects.toThrow('形式が正しくありません')
    },
  )
})
