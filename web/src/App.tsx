/**
 * B00 hello-world shell. Proves that the locked React/TypeScript/Vite/Tailwind toolchain
 * compiles. The real application shell, router and seven workspaces start at B01
 * (docs/03_UI_UX_SPECIFICATION.md). This is not a product screen.
 */
export function App() {
  return (
    <main className="min-h-screen bg-surface text-on-surface p-8">
      <h1 className="text-2xl font-semibold">Agni Setu</h1>
      <p className="mt-2">
        Development scaffold (B00). No application features are available yet.
      </p>
    </main>
  );
}
