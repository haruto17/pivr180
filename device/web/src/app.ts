import { createShutdownSection } from './shutdown'

export function renderApp(root: HTMLElement): void {
  const heading = document.createElement('h1')
  heading.textContent = 'pivr180'
  const description = document.createElement('p')
  description.textContent = 'スマホから pivr180 を操作する画面です。'
  root.replaceChildren(heading, description, createShutdownSection())
}
