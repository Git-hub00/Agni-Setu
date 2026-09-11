/** Service-worker update signalling (docs/09 s.3). The worker is registered from `src/pwa.ts`
 *  in production builds only; the shell listens for this event and offers a safe reload. The
 *  event carries the function that activates the waiting worker. Kept free of the
 *  `virtual:pwa-register` import so the shell stays testable under vitest. */

export const SW_UPDATE_EVENT = "agni:service-worker-update";

export interface ServiceWorkerUpdateDetail {
  /** Activates the waiting worker and reloads the page. */
  apply: () => void;
}

export function announceServiceWorkerUpdate(apply: () => void): void {
  window.dispatchEvent(
    new CustomEvent<ServiceWorkerUpdateDetail>(SW_UPDATE_EVENT, { detail: { apply } }),
  );
}
