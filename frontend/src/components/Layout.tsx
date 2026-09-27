import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken } from "../api/client";
import { useMe } from "../hooks/useMe";

export default function Layout() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const [menuOpen, setMenuOpen] = useState(false);

  function logout() {
    clearToken();
    // Otherwise the next person to log in here would briefly see this user's data.
    queryClient.clear();
    navigate("/login");
  }

  function closeMenu() {
    setMenuOpen(false);
  }

  return (
    <div className="layout">
      <header className="topbar">
        <strong>Story Scraper</strong>
        <button
          className="menu-toggle"
          aria-label="Toggle menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((v) => !v)}
        >
          ☰
        </button>
      </header>

      {menuOpen && <div className="scrim" onClick={closeMenu} />}

      <nav className={menuOpen ? "sidebar open" : "sidebar"}>
        <strong className="sidebar-title">Story Scraper</strong>
        <NavLink to="/jobs" onClick={closeMenu}>
          Jobs
        </NavLink>
        <NavLink to="/jobs/new" onClick={closeMenu}>
          New job
        </NavLink>
        <NavLink to="/templates" onClick={closeMenu}>
          Templates
        </NavLink>
        <NavLink to="/settings" onClick={closeMenu}>
          Settings
        </NavLink>
        {me?.role === "admin" && (
          <NavLink to="/admin/users" onClick={closeMenu}>
            Users
          </NavLink>
        )}
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
