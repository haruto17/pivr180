export const SETTINGS_URL = '/api/settings'

export const WHITE_BALANCES = [
  ['auto', '自動'],
  ['incandescent', '白熱灯'],
  ['tungsten', 'タングステン'],
  ['fluorescent', '蛍光灯'],
  ['indoor', '室内'],
  ['daylight', '晴天'],
  ['cloudy', '曇天'],
] as const

export type WhiteBalance = (typeof WHITE_BALANCES)[number][0]

export interface CameraSettings {
  exposure_value: number
  white_balance: WhiteBalance
  contrast: number
}

export interface SettingsDeps {
  fetch: (url: string, init?: RequestInit) => Promise<Response>
}

const browserDeps: SettingsDeps = {
  fetch: (url, init) => window.fetch(url, init),
}

interface Range {
  input: HTMLInputElement
  output: HTMLOutputElement
}

export function formatExposureValue(value: number): string {
  const text = value.toFixed(1)
  return value > 0 ? `+${text}` : text
}

export function formatContrast(value: number): string {
  return value.toFixed(1)
}

export async function renderSettings(
  root: HTMLElement,
  deps: SettingsDeps = browserDeps,
): Promise<void> {
  const heading = document.createElement('h2')
  heading.textContent = '撮影設定'
  const exposure = createRange('露出補正', 'exposure_value', -2, 2, 0.1, formatExposureValue)
  const whiteBalance = createWhiteBalance()
  const contrast = createRange('コントラスト', 'contrast', 0, 2, 0.1, formatContrast)
  const status = document.createElement('p')
  status.setAttribute('role', 'status')
  status.textContent = '読み込み中…'
  root.replaceChildren(heading, exposure.label, whiteBalance.label, contrast.label, status)

  const inputs = [exposure.input, whiteBalance.select, contrast.input]
  const setDisabled = (disabled: boolean): void => {
    for (const input of inputs) {
      input.disabled = disabled
    }
  }
  const show = (settings: CameraSettings): void => {
    setRange(exposure, settings.exposure_value, formatExposureValue)
    whiteBalance.select.value = settings.white_balance
    setRange(contrast, settings.contrast, formatContrast)
  }
  setDisabled(true)

  let applied: CameraSettings
  try {
    applied = await readSettings(await deps.fetch(SETTINGS_URL))
  } catch {
    status.textContent = '撮影設定を読み込めませんでした。'
    return
  }
  show(applied)
  setDisabled(false)
  status.textContent = ''

  const change = async (): Promise<void> => {
    const requested: CameraSettings = {
      exposure_value: Number(exposure.input.value),
      white_balance: whiteBalance.select.value as WhiteBalance,
      contrast: Number(contrast.input.value),
    }
    setDisabled(true)
    status.textContent = '変更しています…'
    try {
      const response = await deps.fetch(SETTINGS_URL, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requested),
      })
      if (response.status === 503) {
        status.textContent = 'カメラの準備ができていないため、設定を変更できませんでした。'
      } else {
        applied = await readSettings(response)
        status.textContent = ''
      }
    } catch {
      status.textContent = '設定を変更できませんでした。'
    }
    show(applied)
    setDisabled(false)
  }
  for (const input of inputs) {
    input.addEventListener('change', () => {
      void change()
    })
  }
}

async function readSettings(response: Response): Promise<CameraSettings> {
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
  return (await response.json()) as CameraSettings
}

function createRange(
  text: string,
  name: string,
  min: number,
  max: number,
  step: number,
  format: (value: number) => string,
): Range & { label: HTMLLabelElement } {
  const input = document.createElement('input')
  input.type = 'range'
  input.name = name
  input.min = String(min)
  input.max = String(max)
  input.step = String(step)
  const output = document.createElement('output')
  input.addEventListener('input', () => {
    output.textContent = format(Number(input.value))
  })
  const label = document.createElement('label')
  label.append(`${text} `, output, input)
  label.style.display = 'block'
  return { input, output, label }
}

function setRange(range: Range, value: number, format: (value: number) => string): void {
  range.input.value = String(value)
  range.output.textContent = format(value)
}

function createWhiteBalance(): { select: HTMLSelectElement; label: HTMLLabelElement } {
  const select = document.createElement('select')
  select.name = 'white_balance'
  for (const [value, text] of WHITE_BALANCES) {
    const option = document.createElement('option')
    option.value = value
    option.textContent = text
    select.append(option)
  }
  const label = document.createElement('label')
  label.append('ホワイトバランス ', select)
  label.style.display = 'block'
  return { select, label }
}
