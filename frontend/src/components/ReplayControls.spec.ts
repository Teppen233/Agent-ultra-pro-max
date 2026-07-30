import { describe, expect, it } from 'vitest'

import type { PipelineEvent } from '@/contracts'
import { createReplayController, createReplayElapsedClock, supportedReplaySpeeds } from '@/api/client'

const events = (timestamps = [0, 1_000, 2_000, 3_000]): PipelineEvent[] => timestamps.map((milliseconds, index) => ({
  id: `evt-${index + 1}`,
  run_id: 'run-replay',
  sequence: index + 1,
  timestamp: new Date(milliseconds).toISOString(),
  type: index === timestamps.length - 1 ? 'review.completed' : 'stage.started',
  data: {},
}))

describe('ReplayController', () => {
  it('播放中从 1 倍切到 8 倍仍只应用每个序号一次', async () => {
    const applied: number[] = []
    const controller = createReplayController(events([0, 0, 0, 0]), (event) => applied.push(event.sequence), {
      wait: async () => undefined,
    })

    controller.play()
    controller.setSpeed(8)
    await controller.finished

    expect(applied).toEqual([1, 2, 3, 4])
  })

  it('仅提供 0.5、1、2、4、8 倍速，并拒绝其他本地速度', () => {
    const controller = createReplayController(events(), () => undefined)

    expect(supportedReplaySpeeds).toEqual([0.5, 1, 2, 4, 8])
    for (const speed of supportedReplaySpeeds) expect(() => controller.setSpeed(speed)).not.toThrow()
    expect(() => controller.setSpeed(3)).toThrow('回放速度仅支持')
  })

  it('暂停后不会继续应用事件，继续后从当前位置播放', async () => {
    const applied: number[] = []
    let releaseWait: (() => void) | undefined
    let markWaitStarted: (() => void) | undefined
    const waitStarted = new Promise<void>((resolve) => { markWaitStarted = resolve })
    const controller = createReplayController(events([0, 2_000]), (event) => applied.push(event.sequence), {
      wait: async () => {
        markWaitStarted?.()
        await new Promise<void>((resolve) => { releaseWait = resolve })
      },
    })

    controller.play()
    await waitStarted
    controller.pause()
    releaseWait?.()
    await Promise.resolve()
    expect(applied).toEqual([1])

    controller.play()
    await controller.finished
    expect(applied).toEqual([1, 2])
  })

  it('跳过空闲时间会把超过一秒的间隔压缩为一秒', async () => {
    const waits: number[] = []
    const controller = createReplayController(events([0, 5_000]), () => undefined, {
      wait: async (milliseconds) => { waits.push(milliseconds) },
    })

    controller.skipIdle = true
    controller.play()
    await controller.finished

    expect(waits).toEqual([1_000])
  })

  it('在等待下一事件时重新开始会取消旧循环，并从首事件重播一次', async () => {
    const applied: number[] = []
    let releaseOldWait: (() => void) | undefined
    let markOldWaitStarted: (() => void) | undefined
    const oldWaitStarted = new Promise<void>((resolve) => { markOldWaitStarted = resolve })
    let waits = 0
    const controller = createReplayController(events([0, 2_000]), (event) => applied.push(event.sequence), {
      wait: async () => {
        waits += 1
        if (waits === 1) {
          markOldWaitStarted?.()
          await new Promise<void>((resolve) => { releaseOldWait = resolve })
        }
      },
    })

    controller.play()
    await oldWaitStarted
    applied.length = 0
    controller.restart()
    releaseOldWait?.()
    await controller.finished

    expect(applied).toEqual([1, 2])
  })

  it('释放控制器会取消等待、阻止后续事件并使 finished 完成', async () => {
    const applied: number[] = []
    let releaseWait: (() => void) | undefined
    let markWaitStarted: (() => void) | undefined
    const waitStarted = new Promise<void>((resolve) => { markWaitStarted = resolve })
    const controller = createReplayController(events([0, 2_000]), (event) => applied.push(event.sequence), {
      wait: async () => {
        markWaitStarted?.()
        await new Promise<void>((resolve) => { releaseWait = resolve })
      },
    })

    controller.play()
    await waitStarted
    controller.dispose()
    await controller.finished
    releaseWait?.()
    await Promise.resolve()

    expect(applied).toEqual([1])
  })

  it('暂停和完成时冻结回放耗时，继续后才恢复增长', () => {
    let now = 0
    const elapsed = createReplayElapsedClock(() => now)

    elapsed.start()
    now = 500
    expect(elapsed.value()).toBe(500)
    elapsed.pause()
    now = 1_500
    expect(elapsed.value()).toBe(500)
    elapsed.resume()
    now = 2_000
    expect(elapsed.value()).toBe(1_000)
    elapsed.finish()
    now = 4_000
    expect(elapsed.value()).toBe(1_000)
  })
})
