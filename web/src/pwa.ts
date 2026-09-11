import { registerSW } from "virtual:pwa-register";

import { announceServiceWorkerUpdate } from "./offline/serviceWorker";

/** Registers the static-shell service worker in production builds. Updates are never applied
 *  silently (docs/09 s.3): the shell shows a prompt and the user chooses when to reload. Unsent
 *  work lives in IndexedDB and survives the reload; the worker caches no API data. */
export function registerServiceWorker(): void {
  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) {
    return;
  }
  const updateServiceWorker = registerSW({
    immediate: true,
    onNeedRefresh() {
      announceServiceWorkerUpdate(() => {
        void updateServiceWorker(true);
      });
    },
  });
}
