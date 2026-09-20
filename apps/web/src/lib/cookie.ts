/** Name of the cookie holding the API key. In its own module, without
 * `import "server-only"`, so middleware — which runs in the edge bundle,
 * outside the server/client split that pragma enforces — can depend on
 * just this constant instead of pulling in api.ts's fetch/redirect logic
 * (today that tree-shakes fine, but a future addition to api.ts could
 * silently break the edge build). */
export const COOKIE = "bsi_key";
