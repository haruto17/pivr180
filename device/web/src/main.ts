import { renderApp } from './app'
import { renderCaptures } from './captures'

const root = document.querySelector<HTMLElement>('#app')
if (root === null) {
  throw new Error('#app not found')
}
renderApp(root)

const captures = document.createElement('section')
root.append(captures)
void renderCaptures(captures)
