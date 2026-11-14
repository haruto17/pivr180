import { renderApp } from './app'
import { renderPreview } from './preview'

const root = document.querySelector<HTMLElement>('#app')
if (root === null) {
  throw new Error('#app not found')
}
renderApp(root)
const preview = document.createElement('section')
root.append(preview)
renderPreview(preview)
