import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken } from "../api/client";

export default function Layout() {
  const navigate = useNavigate();

  function logout() {
    clearToken();
    navigate("/login");
  }

  return (
    <div className="layout">
      <nav className="sidebar">
        <strong style={{ padding: "0 0.75rem 1rem" }}>Story Scraper</strong>
        <NavLink to="/jobs">Jobs</NavLink>
        <NavLink to="/jobs/new">New job</NavLink>
        <NavLink to="/templates">Templates</NavLink>
        <NavLink to="/settings">Settings</NavLink>
        <button onClick={logout} style={{ marginTop: "auto" }}>
          Log out
        </button>
      </nav>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
