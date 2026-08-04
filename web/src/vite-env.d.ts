/// <reference types="vite/client" />

/**
 * Declares the app's client-exposed env vars as known properties.
 *
 * Without this they resolve through `ImportMetaEnv`'s index signature, which
 * tsconfig's `noPropertyAccessFromIndexSignature` rejects for dot access
 * (TS4111). Bracket access would satisfy the compiler but break the build:
 * vite.config.ts injects these via Vite `define`, which only substitutes the
 * literal `import.meta.env.VITE_X` member expression -- a dynamic
 * `import.meta.env["VITE_X"]` is left unreplaced. So the declaration, not the
 * access style, is the right fix.
 */
interface ImportMetaEnv {
  /** Base URL of the Clio FastAPI backend, e.g. http://localhost:8000.
   *  Optional: unset is handled with a clear runtime error in src/lib/vault.ts. */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
