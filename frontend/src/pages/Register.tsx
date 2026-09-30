import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { LuUserPlus } from "react-icons/lu";
import { Link, useNavigate } from "react-router-dom";
import {
  getRegistrationOpen,
  login as loginRequest,
  register as registerRequest,
} from "../api/endpoints";
import { setToken } from "../api/client";

export default function Register() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { data: open } = useQuery({ queryKey: ["registration-open"], queryFn: getRegistrationOpen });

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await registerRequest(email, password);
      const token = await loginRequest(email, password);
      setToken(token);
      navigate("/jobs");
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Could not register.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  if (open === false) {
    return (
      <div className="content auth-page">
        <h1>Register</h1>
        <p>Registration is closed. Ask an admin to reopen it.</p>
        <p>
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </div>
    );
  }

  return (
    <div className="content auth-page">
      <h1>Register</h1>
      <form onSubmit={onSubmit}>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
        </label>
        {error && <span className="error">{error}</span>}
        <button className="primary" type="submit" disabled={loading}>
          <LuUserPlus />
          {loading ? "Creating account..." : "Register"}
        </button>
      </form>
      <p>
        Already have an account? <Link to="/login">Log in</Link>
      </p>
    </div>
  );
}
