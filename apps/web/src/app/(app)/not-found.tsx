import { NotFoundBody } from "../not-found";

// (app)/layout.tsx already wraps children in <nav> + <main>; reuse the
// root's content without its extra <main> wrap.
export default NotFoundBody;
