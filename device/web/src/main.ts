import { renderApp } from './app'
import { renderCaptures } from './captures'
import { renderPreview } from './preview'
import { renderSettings } from './settings'

const root = document.querySelector<HTMLElement>('#app')
if (root === null) {
  throw new Error('#app not found')
}
renderApp(root)
const preview = document.createElement('section')
root.append(preview)
renderPreview(preview)

const settings = document.createElement('section')
root.append(settings)
void renderSettings(settings)

const captures = document.createElement('section')
root.append(captures)
void renderCaptures(captures)
