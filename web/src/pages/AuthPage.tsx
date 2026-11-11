import { type FormEvent, useState } from "react";
import { Link, Navigate } from "react-router";

import { useAuth } from "../auth/context";
import { ErrorMessage } from "../components/ui";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { signedIn, login, register } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (signedIn) return <Navigate to="/" replace />;

  const isLogin = mode === "login";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (isLogin ? login(email, password) : register(email, password));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <div className="card w-full max-w-sm">
        <p className="text-sm font-semibold text-brand-700">Onesum</p>
        <h1 className="mb-4 text-2xl font-bold">{isLogin ? "Sign in" : "Create your account"}</h1>
        <form onSubmit={(e) => void submit(e)} className="space-y-4" noValidate={false}>
          <div>
            <label htmlFor="email" className="label">
              Email
            </label>
            <input id="email" type="email" autoComplete="email" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label htmlFor="password" className="label">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete={isLogin ? "current-password" : "new-password"}
              required
              minLength={isLogin ? undefined : 12}
              maxLength={128}
              aria-describedby={isLogin ? undefined : "password-help"}
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {!isLogin && (
              <p id="password-help" className="mt-1 text-xs text-muted">
                At least 12 characters.
              </p>
            )}
          </div>
          <ErrorMessage error={error} />
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? "Please wait…" : isLogin ? "Sign in" : "Create account"}
          </button>
        </form>
        <p className="mt-4 text-center text-sm text-muted">
          {isLogin ? "New here? " : "Already have an account? "}
          <Link to={isLogin ? "/register" : "/login"} className="font-semibold text-brand-700 underline-offset-4 hover:underline">
            {isLogin ? "Create an account" : "Sign in"}
          </Link>
        </p>
      </div>
    </main>
  );
}
