import { Navigate, Outlet } from "react-router-dom";
import { useMe } from "../hooks/useMe";

/** Keeps non-admins off admin pages. The API enforces this too; this only
 * saves them from a page full of 403s. */
export default function AdminRoute() {
  const { data: me, isLoading } = useMe();
  if (isLoading) return <p>Loading...</p>;
  return me?.role === "admin" ? <Outlet /> : <Navigate to="/jobs" replace />;
}
