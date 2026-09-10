import { en, type MessageKey } from "./en";

/**
 * Tiny typed translation helper. A missing key is a type error, so no visible string can bypass
 * the locale table. Runtime locale switching arrives with reviewed Hindi copy (UI spec s.2).
 */
export function t(key: MessageKey): string {
  return en[key];
}

export type { MessageKey };
