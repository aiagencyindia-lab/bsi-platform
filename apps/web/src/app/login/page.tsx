"use client";

import { useActionState } from "react";
import { login } from "./actions";

export default function Login() {
  const [error, action, pending] = useActionState(login, undefined);
  return (
    <form action={action} className="card" style={{ maxWidth: 420 }}>
      <h1>Sign in</h1>
      <label>
        API key
        <input name="key" type="password" required autoFocus />
      </label>
      {error && <p className="error">{error}</p>}
      <p>
        <button className="primary" disabled={pending}>
          Sign in
        </button>
      </p>
    </form>
  );
}
