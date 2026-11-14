import { defineConfig } from 'vitest/config'

export default defineConfig({
  build: {
    outDir: '../src/pivr180_device/static',
    emptyOutDir: true,
  },
  test: {
    environment: 'happy-dom',
  },
})
