// Plain Vite config -- this app previously depended on a third-party hosted-
// platform config wrapper. This file replicates, for our self-hosted setup,
// exactly the plugin stack and options that wrapper supplied under the hood:
// tailwindcss, tsconfig-paths, tanstackStart (with its default importProtection
// + our server.entry override), nitro at build time (cloudflare-module preset,
// matching what was already deployed), @vitejs/plugin-react, VITE_* env
// injection into import.meta.env, the '@' -> src alias, React/TanStack dedupe,
// and dev-server prebundling hints. Dropped deliberately: pieces that only did
// anything inside that platform's own hosted sandbox (an asset proxy, an HMR
// gate, a dev-server bridge, and build-error/SSR/server-fn diagnostics that fed
// its hosted editor's error overlay) -- none of those do anything here.
import { defineConfig, loadEnv, type UserConfig } from "vite";
import viteReact from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import tsConfigPaths from "vite-tsconfig-paths";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";

export default defineConfig(async ({ command, mode }) => {
  const plugins = [
    tailwindcss(),
    tsConfigPaths({ projects: ["./tsconfig.json"] }),
    tanstackStart({
      importProtection: {
        behavior: "error",
        client: { files: ["**/server/**"], specifiers: ["server-only"] },
      },
      // Redirect TanStack Start's bundled server entry to src/server.ts (our
      // SSR error wrapper). nitro/vite builds from this.
      server: { entry: "server" },
    }),
    viteReact(),
  ];

  if (command === "build") {
    const { nitro } = await import("nitro/vite");
    plugins.push(nitro({ defaultPreset: "cloudflare-module" }));
  }

  // VITE_*-prefixed vars from .env -> statically replaced into
  // import.meta.env.VITE_X at build/dev time (see src/vite-env.d.ts for why
  // they're also declared as typed properties rather than read via bracket
  // access).
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const envDefine: Record<string, string> = {};
  for (const [key, value] of Object.entries(env)) {
    envDefine[`import.meta.env.${key}`] = JSON.stringify(value);
  }

  return {
    define: envDefine,
    css: { transformer: "lightningcss" as const },
    resolve: {
      alias: { "@": `${process.cwd()}/src` },
      dedupe: [
        "react",
        "react-dom",
        "react/jsx-runtime",
        "react/jsx-dev-runtime",
        "@tanstack/react-query",
        "@tanstack/query-core",
      ],
    },
    optimizeDeps: {
      include: [
        "react",
        "react-dom",
        "react-dom/client",
        "react/jsx-runtime",
        "react/jsx-dev-runtime",
      ],
      ignoreOutdatedRequests: true,
    },
    plugins,
    server: {
      host: "::",
      // Port 3000 so the browser origin matches the FastAPI backend's CORS
      // allow_origins (http://localhost:3000) -- keeps the backend untouched.
      // strictPort: without it, a stale process squatting on 3000 makes Vite
      // silently drift to 3001+, which then fails CORS with no obvious cause.
      port: 3000,
      strictPort: true,
    },
  } satisfies UserConfig;
});
