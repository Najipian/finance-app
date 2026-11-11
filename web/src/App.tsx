import { Navigate, Route, Routes } from "react-router";

import { useAuth } from "./auth/context";
import { Layout } from "./components/Layout";
import { AccountsPage } from "./pages/AccountsPage";
import { AuthPage } from "./pages/AuthPage";
import { BanksPage, ConnectionResultPage } from "./pages/BanksPage";
import { BudgetsPage } from "./pages/BudgetsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { TransactionsPage } from "./pages/TransactionsPage";

function Protected() {
  const { signedIn } = useAuth();
  return signedIn ? <Layout /> : <Navigate to="/login" replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/register" element={<AuthPage mode="register" />} />
      <Route element={<Protected />}>
        <Route index element={<DashboardPage />} />
        <Route path="accounts" element={<AccountsPage />} />
        <Route path="transactions" element={<TransactionsPage />} />
        <Route path="budgets" element={<BudgetsPage />} />
        <Route path="banks" element={<BanksPage />} />
        <Route path="connections/result" element={<ConnectionResultPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
