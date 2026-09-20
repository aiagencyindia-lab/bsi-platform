import { NotFoundBody } from "../not-found";

// login/layout.tsx already wraps children in <main>; reuse the root's
// content without its extra <main> wrap (login has no nav to add).
export default NotFoundBody;
