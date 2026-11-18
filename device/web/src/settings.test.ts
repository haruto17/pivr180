import { describe, expect, it, vi } from 'vitest'
import {
  formatContrast,
  formatExposureValue,
  renderSettings,
  SETTINGS_URL,
  type CameraSettings,
} from './settings'

const DEFAULTS: CameraSettings = { exposure_value: 0, white_balance: 'auto', contrast: 1 }
const CHANGED: CameraSettings = { exposure_value: -1.5, white_balance: 'daylight', contrast: 1.2 }

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function api(put: (body: CameraSettings) => Promise<Response>) {
  return vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') {
      return put(JSON.parse(String(init.body)) as CameraSettings)
    }
    return json(DEFAULTS)
  })
}

function controls(root: HTMLElement) {
  const exposure = root.querySelector<HTMLInputElement>('input[name="exposure_value"]')
  const whiteBalance = root.querySelector<HTMLSelectElement>('select[name="white_balance"]')
  const contrast = root.querySelector<HTMLInputElement>('input[name="contrast"]')
  const status = root.querySelector('[role="status"]')
  if (exposure === null || whiteBalance === null || contrast === null || status === null) {
    throw new Error('settings controls not rendered')
  }
  return { exposure, whiteBalance, contrast, status }
}

function shown(root: HTMLElement): string[] {
  return [...root.querySelectorAll('output')].map((output) => output.textContent ?? '')
}

function change(input: HTMLInputElement | HTMLSelectElement, value: string): void {
  input.value = value
  input.dispatchEvent(new Event('change'))
}

describe('formatExposureValue', () => {
  it('shows the sign of positive values and one decimal place', () => {
    expect(formatExposureValue(0.5)).toBe('+0.5')
    expect(formatExposureValue(-2)).toBe('-2.0')
    expect(formatExposureValue(0)).toBe('0.0')
  })
})

describe('formatContrast', () => {
  it('shows one decimal place', () => {
    expect(formatContrast(1)).toBe('1.0')
    expect(formatContrast(0.3)).toBe('0.3')
  })
})

describe('renderSettings', () => {
  it('shows the current settings from the device', async () => {
    const root = document.createElement('section')
    const fetch = api(async (body) => json(body))

    await renderSettings(root, { fetch })

    const { exposure, whiteBalance, contrast, status } = controls(root)
    expect(root.querySelector('h2')?.textContent).toBe('撮影設定')
    expect(fetch).toHaveBeenCalledWith(SETTINGS_URL)
    expect(exposure.value).toBe('0')
    expect(whiteBalance.value).toBe('auto')
    expect(contrast.value).toBe('1')
    expect(shown(root)).toEqual(['0.0', '1.0'])
    expect(exposure.disabled).toBe(false)
    expect(status.textContent).toBe('')
  })

  it('offers the white balance modes with Japanese labels', async () => {
    const root = document.createElement('section')

    await renderSettings(root, { fetch: api(async (body) => json(body)) })

    const options = [...controls(root).whiteBalance.options].map((option) => [
      option.value,
      option.text,
    ])
    expect(options).toEqual([
      ['auto', '自動'],
      ['incandescent', '白熱灯'],
      ['tungsten', 'タングステン'],
      ['fluorescent', '蛍光灯'],
      ['indoor', '室内'],
      ['daylight', '晴天'],
      ['cloudy', '曇天'],
    ])
  })

  it('limits the exposure value to -2..2 and the contrast to 0..2', async () => {
    const root = document.createElement('section')

    await renderSettings(root, { fetch: api(async (body) => json(body)) })

    const { exposure, contrast } = controls(root)
    expect([exposure.min, exposure.max, exposure.step]).toEqual(['-2', '2', '0.1'])
    expect([contrast.min, contrast.max, contrast.step]).toEqual(['0', '2', '0.1'])
  })

  it('reports settings that cannot be loaded and keeps the controls disabled', async () => {
    const root = document.createElement('section')

    await renderSettings(root, { fetch: vi.fn(async () => new Response(null, { status: 500 })) })

    const { exposure, whiteBalance, contrast, status } = controls(root)
    expect(status.textContent).toContain('読み込めませんでした')
    expect([exposure.disabled, whiteBalance.disabled, contrast.disabled]).toEqual([
      true,
      true,
      true,
    ])
  })

  it('updates the shown value while a slider moves', async () => {
    const root = document.createElement('section')
    await renderSettings(root, { fetch: api(async (body) => json(body)) })
    const { exposure } = controls(root)

    exposure.value = '1.3'
    exposure.dispatchEvent(new Event('input'))

    expect(shown(root)).toEqual(['+1.3', '1.0'])
  })

  it('sends all settings as JSON when one of them changes', async () => {
    const root = document.createElement('section')
    const fetch = api(async (body) => json(body))
    await renderSettings(root, { fetch })
    const { exposure, whiteBalance, contrast } = controls(root)
    exposure.value = '-1.5'
    contrast.value = '1.2'

    change(whiteBalance, 'daylight')

    expect(fetch).toHaveBeenLastCalledWith(SETTINGS_URL, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(CHANGED),
    })
  })

  it('disables the controls while a change is in flight', async () => {
    const root = document.createElement('section')
    await renderSettings(root, { fetch: api(() => new Promise<Response>(() => {})) })
    const { exposure, whiteBalance, contrast } = controls(root)

    change(contrast, '1.5')

    expect([exposure.disabled, whiteBalance.disabled, contrast.disabled]).toEqual([
      true,
      true,
      true,
    ])
  })

  it('shows the settings the device applied', async () => {
    const root = document.createElement('section')
    await renderSettings(root, { fetch: api(async () => json(CHANGED)) })
    const { exposure, whiteBalance, contrast, status } = controls(root)

    change(exposure, '-1.5')

    await vi.waitFor(() => expect(exposure.disabled).toBe(false))
    expect(exposure.value).toBe('-1.5')
    expect(whiteBalance.value).toBe('daylight')
    expect(contrast.value).toBe('1.2')
    expect(shown(root)).toEqual(['-1.5', '1.2'])
    expect(status.textContent).toBe('')
  })

  it('reports cameras that are not ready and goes back to the applied settings', async () => {
    const root = document.createElement('section')
    await renderSettings(root, {
      fetch: api(async () => json({ detail: 'cameras are not ready' }, 503)),
    })
    const { exposure, status } = controls(root)

    change(exposure, '1.5')

    await vi.waitFor(() => expect(exposure.disabled).toBe(false))
    expect(status.textContent).toContain('カメラの準備ができていない')
    expect(exposure.value).toBe('0')
    expect(shown(root)).toEqual(['0.0', '1.0'])
  })

  it('reports a rejected change and goes back to the applied settings', async () => {
    const root = document.createElement('section')
    await renderSettings(root, { fetch: api(async () => json({ detail: [] }, 422)) })
    const { whiteBalance, status } = controls(root)

    change(whiteBalance, 'cloudy')

    await vi.waitFor(() => expect(whiteBalance.disabled).toBe(false))
    expect(status.textContent).toContain('設定を変更できませんでした')
    expect(whiteBalance.value).toBe('auto')
  })

  it('reports an unreachable device and lets the user try again', async () => {
    const root = document.createElement('section')
    await renderSettings(root, {
      fetch: api(async () => {
        throw new TypeError('Failed to fetch')
      }),
    })
    const { contrast, status } = controls(root)

    change(contrast, '0.5')

    await vi.waitFor(() => expect(contrast.disabled).toBe(false))
    expect(status.textContent).toContain('設定を変更できませんでした')
    expect(contrast.value).toBe('1')
  })
})
