import { Navigate, Route, Routes } from "react-router-dom";
import AdminRoute from "./components/AdminRoute";
import Layout from "./components/Layout";
import PrivateRoute from "./components/PrivateRoute";
import JobDetail from "./pages/JobDetail";
import AdminUsers from "./pages/AdminUsers";
import Jobs from "./pages/Jobs";
import Login from "./pages/Login";
import NewJob from "./pages/NewJob";
import Register from "./pages/Register";
import Settings from "./pages/Settings";
import TemplateForm from "./pages/TemplateForm";
import Templates from "./pages/Templates";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />

      <Route element={<PrivateRoute />}>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/jobs" replace />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/new" element={<NewJob />} />
          <Route path="/jobs/:id" element={<JobDetail />} />
          <Route path="/templates" element={<Templates />} />
          <Route path="/templates/new" element={<TemplateForm />} />
          <Route path="/templates/:id" element={<TemplateForm />} />
          <Route path="/settings" element={<Settings />} />
          <Route element={<AdminRoute />}>
            <Route path="/admin/users" element={<AdminUsers />} />
          </Route>
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/jobs" replace />} />
    </Routes>
  );
}
