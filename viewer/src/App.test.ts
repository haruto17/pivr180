import { render } from 'svelte/server'
import { describe, expect, it } from 'vitest'
import App from './App.svelte'

describe('App', () => {
  it('renders the viewer heading', () => {
    const { body } = render(App)

    expect(body).toContain('<h1>pivr180 viewer</h1>')
  })

  it('asks for a photo URL when ?photo= is not given', () => {
    const { body } = render(App)

    expect(body).toContain('?photo=')
    expect(body).not.toContain('<canvas')
  })
})
