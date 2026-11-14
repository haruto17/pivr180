import { renderApp } from './app'

const root = document.querySelector<HTMLElement>('#app')
if (root === null) {
  throw new Error('#app not found')
}
renderApp(root)
