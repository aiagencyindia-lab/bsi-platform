import { NotFoundBody } from "../not-found";

// Keeps an unknown or revoked link's 404 under r/layout's neutral title.
export default function NotFound() {
  return (
    <main>
      <NotFoundBody />
    </main>
  );
}
