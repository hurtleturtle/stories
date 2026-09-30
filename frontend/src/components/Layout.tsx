import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken } from "../api/client";
import { useMe } from "../hooks/useMe";
import { type ThemePreference, useTheme } from "../hooks/useTheme";

const THEME_OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export default function Layout() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const [menuOpen, setMenuOpen] = useState(false);
  const [theme, setTheme] = useTheme();

  // The mobile menu covers the page: stop the page behind it scrolling, and let Esc close it.
  useEffect(() => {
    if (!menuOpen) return;
    document.body.classList.add("menu-open");
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.classList.remove("menu-open");
      window.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

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
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((v) => !v)}
        >
          {menuOpen ? "✕" : "☰"}
        </button>
      </header>

      <nav className={menuOpen ? "sidebar open" : "sidebar"}>
        <strong className="sidebar-title">Story Scraper</strong>
        <NavLink to="/jobs" end onClick={closeMenu}>
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
        <div className="sidebar-footer">
          <div className="theme-switch" role="group" aria-label="Theme">
            {THEME_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                aria-pressed={theme === opt.value}
                onClick={() => setTheme(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <button type="button" className="logout" onClick={logout}>
            Log out
          </button>
        </div>
      </nav>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
