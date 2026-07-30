import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ReviewForm from './ReviewForm.vue'

describe('ReviewForm', () => {
  it('submits a GitHub pull request without a local repository path', async () => {
    const wrapper = mount(ReviewForm, { props: { loading: false } })
    await wrapper
      .get('[aria-label="GitHub PR URL 或本地 Diff 路径"] input')
      .setValue('https://github.com/owner/repo/pull/42')

    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([
      ['https://github.com/owner/repo/pull/42', '', false],
    ])
  })

  it('trims an explicit repository path before submission', async () => {
    const wrapper = mount(ReviewForm, { props: { loading: false } })
    await wrapper
      .get('[aria-label="GitHub PR URL 或本地 Diff 路径"] input')
      .setValue(' /tmp/change.diff ')
    await wrapper
      .get('[aria-label="本地仓库绝对路径（可选）"] input')
      .setValue(' /workspace/repo ')

    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([
      ['/tmp/change.diff', '/workspace/repo', false],
    ])
  })

  it('allows a GitHub PR to be added while capacity remains', async () => {
    const wrapper = mount(ReviewForm, {
      props: { loading: false, benchmarkCount: 2, benchmarkCapacity: 5 },
    })
    await wrapper
      .get('[aria-label="GitHub PR URL 或本地 Diff 路径"] input')
      .setValue('https://github.com/owner/repo/pull/42')
    await wrapper.get('.benchmark-option [role="checkbox"]').trigger('click')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('submit')).toEqual([
      ['https://github.com/owner/repo/pull/42', '', true],
    ])
  })
})
