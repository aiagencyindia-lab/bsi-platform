import { defineConfig } from "vitest/config";

// tsconfig has jsx: "preserve" (Next's setting); TSX tests need the
// automatic runtime to compile.
export default defineConfig({ esbuild: { jsx: "automatic" } });
