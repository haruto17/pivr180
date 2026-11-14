export const SHUTDOWN_URL = '/api/shutdown'
export const CONFIRM_MESSAGE =
  'pivr180 をシャットダウンしますか？撮影中の場合は、その撮影を保存してから電源を切ります。'

export interface ShutdownDeps {
  confirm: (message: string) => boolean
  fetch: (url: string, init: RequestInit) => Promise<Response>
}

const browserDeps: ShutdownDeps = {
  confirm: (message) => window.confirm(message),
  fetch: (url, init) => window.fetch(url, init),
}

export function createShutdownSection(deps: ShutdownDeps = browserDeps): HTMLElement {
  const heading = document.createElement('h2')
  heading.textContent = '電源'
  const button = document.createElement('button')
  button.type = 'button'
  button.textContent = 'シャットダウン'
  const status = document.createElement('p')
  status.setAttribute('role', 'status')
  button.addEventListener('click', () => {
    void requestShutdown(button, status, deps)
  })
  const section = document.createElement('section')
  section.append(heading, button, status)
  return section
}

async function requestShutdown(
  button: HTMLButtonElement,
  status: HTMLElement,
  deps: ShutdownDeps,
): Promise<void> {
  if (!deps.confirm(CONFIRM_MESSAGE)) {
    return
  }
  button.disabled = true
  status.textContent = 'シャットダウンを要求しています…'
  try {
    const response = await deps.fetch(SHUTDOWN_URL, { method: 'POST' })
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
  } catch {
    button.disabled = false
    status.textContent =
      'シャットダウンを要求できませんでした。もう一度試すか、本体のボタンを 3 秒押し続けてください。'
    return
  }
  status.textContent =
    'シャットダウンを受け付けました。撮影中の場合は、その撮影を保存してから電源が切れます。'
}
