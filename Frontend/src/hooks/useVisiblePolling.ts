import { useEffect } from 'react';

export function useVisiblePolling(load: (signal: AbortSignal) => Promise<void>, interval: number, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    let timer: number | undefined;
    let current: AbortController | undefined;

    async function poll() {
      if (!active || document.hidden || current) return;
      const controller = new AbortController();
      current = controller;
      try {
        await load(controller.signal);
      } finally {
        current = undefined;
        if (active && !document.hidden) timer = window.setTimeout(poll, interval);
      }
    }

    function onVisibilityChange() {
      window.clearTimeout(timer);
      if (!document.hidden) void poll();
    }

    document.addEventListener('visibilitychange', onVisibilityChange);
    void poll();
    return () => {
      active = false;
      window.clearTimeout(timer);
      current?.abort();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [enabled, interval, load]);
}
