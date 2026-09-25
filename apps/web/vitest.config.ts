import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// tsconfig has jsx: "preserve" (Next's setting); TSX tests need the
// automatic runtime to compile.
export default defineConfig({
  esbuild: { jsx: "automatic" },
  // Mirrors tsconfig's "@/*" path so runtime "@/..." imports resolve in tests.
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
});
