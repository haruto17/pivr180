import { svelte } from '@sveltejs/vite-plugin-svelte'
import process from 'node:process'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [svelte()],
  resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
})
