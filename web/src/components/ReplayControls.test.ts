import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ReplayControls from '@/components/ReplayControls.vue'

describe('ReplayControls', () => {
  it('emits manual navigation and displays progress', async () => {
    const wrapper = mount(ReplayControls, {
      props: { index: 3, total: 10, playing: false, speed: 1, live: false },
    })

    await wrapper.get('[data-testid="replay-next"]').trigger('click')
    await wrapper.get('[data-testid="replay-previous"]').trigger('click')

    expect(wrapper.emitted('next')).toHaveLength(1)
    expect(wrapper.emitted('previous')).toHaveLength(1)
    expect(wrapper.text()).toContain('3 / 10')
  })

  it('disables replay controls while following a live run', () => {
    const wrapper = mount(ReplayControls, {
      props: { index: 4, total: 4, playing: false, speed: 1, live: true },
    })

    expect(wrapper.text()).toContain('实时追踪')
    expect(wrapper.get('[data-testid="replay-next"]').attributes('disabled')).toBeDefined()
  })
})
