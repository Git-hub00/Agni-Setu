# Agni Setu web client

React 19 + TypeScript + Vite SPA/PWA. Package manager is pnpm via corepack; the exact
version is declared in `package.json` (`packageManager`) once resolved at B00.

```bash
cd web
pnpm install --frozen-lockfile
pnpm dev
pnpm build
```

`/api` is proxied to the host Django server on 127.0.0.1:8000 in development
(`vite.config.ts`).
