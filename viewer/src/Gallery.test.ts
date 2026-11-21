// @vitest-environment jsdom
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Gallery from './Gallery.svelte'

const photos = [
  { name: '20260102-090000-000_180_LR.jpg', url: '/photos/20260102-090000-000_180_LR.jpg' },
  { name: '20260101-090000-000_180_LR.jpg', url: '/photos/20260101-090000-000_180_LR.jpg' },
]
let component: ReturnType<typeof mount> | undefined

function render(props: { photos: typeof photos; onselect?: (index: number) => void }) {
  component = mount(Gallery, { target: document.body, props: { onselect: () => {}, ...props } })
  flushSync()
}

afterEach(() => {
  if (component) unmount(component)
  component = undefined
  document.body.innerHTML = ''
})

describe('Gallery', () => {
  it('shows each photo as a thumbnail with its name, in the given order', () => {
    render({ photos })

    const items = Array.from(document.querySelectorAll('li'))
    expect(items.map((li) => li.querySelector('img')?.getAttribute('src'))).toEqual(photos.map((p) => p.url))
    expect(items.map((li) => li.textContent?.trim())).toEqual(photos.map((p) => p.name))
  })

  it('reports the index of the chosen photo', () => {
    const onselect = vi.fn()
    render({ photos, onselect })

    document.querySelectorAll('button')[1].click()

    expect(onselect).toHaveBeenCalledWith(1)
  })

  it('says there are no photos when the list is empty', () => {
    render({ photos: [] })

    expect(document.querySelector('li')).toBeNull()
    expect(document.body.textContent).toContain('書き出した写真がありません')
  })
})
