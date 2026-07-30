import { defineStore } from 'pinia'

import { createEventSubscription } from '@/api/client'
import { useReviewStore } from '@/stores/review'

type ConnectionState = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'closed' | 'error'
type EventSourceFactory = NonNullable<Parameters<typeof createEventSubscription>[2]>['factory']

const activeRunStorageKey = 'reviewcrew.activeRunId'

/** 建立页面级服务端历史回放，不占用或替换应用级真实运行订阅。 */
export const createServerReplaySubscription = (
  runId: string,
  handlers: Parameters<typeof createEventSubscription>[1],
  factory?: EventSourceFactory,
) => createEventSubscription(runId, handlers, {
  replay: true,
  speed: 2,
  ...(factory ? { factory } : {}),
})

/** 在无浏览器或受限存储环境中安全访问会话存储。 */
const activeRunStorage = (): Storage | undefined => {
  if (typeof window === 'undefined') return undefined
  try {
    return window.sessionStorage
  } catch {
    return undefined
  }
}

/**
 * 管理跨路由存活的实时审查订阅。
 * SSE 连接归应用所有，页面仅消费状态，避免组件卸载误停服务端审查。
 */
export const useRunsStore = defineStore('runs', {
  state: () => ({
    activeRunId: null as string | null,
    lastRunId: null as string | null,
    connection: 'idle' as ConnectionState,
    connectionMessage: '',
    subscription: undefined as ReturnType<typeof createEventSubscription> | undefined,
  }),
  actions: {
    /** 为指定运行建立唯一 SSE 订阅；同一运行重复调用不会重复连接。 */
    startSubscription(runId: string, factory?: EventSourceFactory): void {
      if (!runId || (this.activeRunId === runId && this.subscription)) return

      if (this.activeRunId) this.stopSubscription(this.activeRunId)

      const review = useReviewStore()
      if (review.runId && review.runId !== runId) review.reset()

      this.activeRunId = runId
      this.lastRunId = runId
      this.connection = 'connecting'
      this.connectionMessage = '正在建立实时事件连接…'
      activeRunStorage()?.setItem(activeRunStorageKey, runId)

      this.subscription = createEventSubscription(runId, {
        onEvent: (event) => {
          if (this.activeRunId === runId) review.applyEvent(event)
        },
        onOpen: () => {
          if (this.activeRunId !== runId) return
          this.connection = 'live'
          this.connectionMessage = '实时事件已连接'
        },
        onDisconnect: () => {
          if (this.activeRunId !== runId) return
          this.connection = 'reconnecting'
          this.connectionMessage = '连接中断，正在自动恢复…'
        },
        onError: (message) => {
          if (this.activeRunId !== runId) return
          this.connection = 'error'
          this.connectionMessage = message
        },
        onClosed: (type) => {
          if (this.activeRunId !== runId) return
          this.connection = 'closed'
          this.connectionMessage = type === 'review.failed'
            ? '审查已失败，事件连接已关闭'
            : '审查已完成，事件连接已关闭'
          this.stopSubscription(runId)
        },
      }, factory ? { factory } : undefined)
    },

    /** 显式停止指定运行的连接，并删除刷新恢复标识。 */
    stopSubscription(runId: string): void {
      if (this.activeRunId !== runId) return
      this.subscription?.close()
      this.subscription = undefined
      this.activeRunId = null
      if (this.connection !== 'error') this.connection = 'closed'
      activeRunStorage()?.removeItem(activeRunStorageKey)
    },

    /** 页面离开时刻意不关闭连接：服务端审查和全局订阅继续运行。 */
    leaveReviewPage(_runId: string): void {},

    /** 浏览器刷新后恢复会话中仍在进行的实时审查。 */
    restoreSubscription(factory?: EventSourceFactory): void {
      const runId = activeRunStorage()?.getItem(activeRunStorageKey)
      if (runId) this.startSubscription(runId, factory)
    },
  },
})
