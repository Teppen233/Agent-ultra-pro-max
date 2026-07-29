import { describe, expect, it } from 'vitest'

import config from './vite.config'

describe('Vite 开发服务', () => {
  it('把同源 /api 请求代理到本地 FastAPI', () => {
    expect(config.server?.proxy?.['/api']).toBe('http://127.0.0.1:8000')
  })
})
