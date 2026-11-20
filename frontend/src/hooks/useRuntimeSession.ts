import { useEffect } from 'react'

type RuntimeStatus = { local_runtime: boolean; automatic_shutdown: boolean }

export function useRuntimeSession() {
  useEffect(() => {
    let disposed = false
    let enabled = false
    let socket: WebSocket | undefined
    let reconnectTimer: number | undefined
    let heartbeatTimer: number | undefined
    let reconnectDelay = 2000

    function clearTimers() {
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer)
        reconnectTimer = undefined
      }
      if (heartbeatTimer !== undefined) {
        window.clearInterval(heartbeatTimer)
        heartbeatTimer = undefined
      }
    }

    function scheduleReconnect() {
      if (disposed || !enabled || reconnectTimer !== undefined) return
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = undefined
        reconnectDelay = Math.min(reconnectDelay * 1.5, 10000)
        connect()
      }, reconnectDelay)
    }

    function connect() {
      if (disposed || !enabled) return
      if (socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) return

      try {
        const url = new URL('/api/runtime/session', window.location.href)
        url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        socket = new WebSocket(url)

        socket.addEventListener('open', () => {
          if (disposed) {
            socket?.close(1000, 'Component unmounted')
            return
          }
          reconnectDelay = 2000
          // Lightweight 30s heartbeat to maintain socket without CPU or event-loop thrashing
          heartbeatTimer = window.setInterval(() => {
            if (socket?.readyState === WebSocket.OPEN) {
              socket.send('ping')
            }
          }, 30000)
        })

        socket.addEventListener('close', (event) => {
          if (heartbeatTimer !== undefined) {
            window.clearInterval(heartbeatTimer)
            heartbeatTimer = undefined
          }
          socket = undefined
          // Code 1000 = Normal closure, 1008 = Forbidden policy. Don't spin reconnects on clean shutdown.
          if (!disposed && event.code !== 1008) {
            scheduleReconnect()
          }
        })

        socket.addEventListener('error', () => {
          socket?.close()
        })
      } catch {
        scheduleReconnect()
      }
    }

    fetch('/api/runtime/status', { cache: 'no-store' })
      .then((response) => (response.ok ? response.json() : null))
      .then((status: RuntimeStatus | null) => {
        if (!disposed && status?.local_runtime && status.automatic_shutdown) {
          enabled = true
          connect()
        }
      })
      .catch(() => {
        /* Standard UI handles offline state */
      })

    function handleVisibilityChange() {
      if (document.visibilityState === 'visible' && (!socket || socket.readyState === WebSocket.CLOSED)) {
        connect()
      }
    }

    function handlePageUnload() {
      if (socket && socket.readyState === WebSocket.OPEN) {
        // Fast teardown: notify server immediately on tab close
        socket.close(1000, 'Tab closed')
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    window.addEventListener('online', connect)
    window.addEventListener('pagehide', handlePageUnload)
    window.addEventListener('beforeunload', handlePageUnload)

    return () => {
      disposed = true
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      window.removeEventListener('online', connect)
      window.removeEventListener('pagehide', handlePageUnload)
      window.removeEventListener('beforeunload', handlePageUnload)
      clearTimers()
      if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        socket.close(1000, 'Dashboard closed')
      }
      socket = undefined
    }
  }, [])
}
