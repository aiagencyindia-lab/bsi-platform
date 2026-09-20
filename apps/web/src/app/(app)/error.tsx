"use client";

import { ErrorBody } from "../error";

// (app)/layout.tsx already wraps children in <nav> + <main>; reuse the
// root's content without its extra <main> wrap.
export default ErrorBody;
