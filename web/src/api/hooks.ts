/** TanStack Query hooks: one per API resource, so pages stay declarative. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  AccountsOverview,
  Budget,
  Category,
  Connection,
  ConnectionStarted,
  DashboardSummary,
  Institution,
  Notification,
  RecategorizeResult,
  TransactionPage,
} from "./types";

export const useDashboard = (month: string) =>
  useQuery({
    queryKey: ["dashboard", month],
    queryFn: () => api<DashboardSummary>("/dashboard/summary", { query: { month } }),
  });

export const useAccounts = () =>
  useQuery({ queryKey: ["accounts"], queryFn: () => api<AccountsOverview>("/accounts") });

export const useConnections = () =>
  useQuery({ queryKey: ["connections"], queryFn: () => api<Connection[]>("/connections") });

export const useInstitutions = (country = "GB") =>
  useQuery({
    queryKey: ["institutions", country],
    queryFn: () => api<Institution[]>("/institutions", { query: { country } }),
  });

export const useCategories = () =>
  useQuery({ queryKey: ["categories"], queryFn: () => api<Category[]>("/categories") });

export const useBudgets = (month: string) =>
  useQuery({
    queryKey: ["budgets", month],
    queryFn: () => api<Budget[]>("/budgets", { query: { month } }),
  });

export const useNotifications = () =>
  useQuery({
    queryKey: ["notifications"],
    queryFn: () => api<Notification[]>("/notifications", { query: { unread: true } }),
  });

export interface TransactionFilters {
  q?: string;
  account_id?: string;
  status?: string;
  limit: number;
  offset: number;
}

export const useTransactions = (filters: TransactionFilters) =>
  useQuery({
    queryKey: ["transactions", filters],
    queryFn: () => api<TransactionPage>("/transactions", { query: { ...filters } }),
    placeholderData: (previous) => previous,
  });

/** Data that changes when categories, transactions or budgets change. */
function useInvalidateMoney() {
  const client = useQueryClient();
  return () =>
    Promise.all(
      ["transactions", "dashboard", "budgets", "notifications"].map((key) =>
        client.invalidateQueries({ queryKey: [key] }),
      ),
    );
}

export function useRecategorize() {
  const invalidate = useInvalidateMoney();
  return useMutation({
    mutationFn: (input: { id: string; category_id: string | null; apply_to_similar: boolean }) =>
      api<RecategorizeResult>(`/transactions/${input.id}`, {
        method: "PATCH",
        body: { category_id: input.category_id, apply_to_similar: input.apply_to_similar },
      }),
    onSuccess: invalidate,
  });
}

export function useSetBudget() {
  const invalidate = useInvalidateMoney();
  return useMutation({
    mutationFn: (input: { category_id: string; month: string; limit_amount: string; currency: string }) =>
      api<Budget>("/budgets", { method: "PUT", body: input }),
    onSuccess: invalidate,
  });
}

export function useDeleteBudget() {
  const invalidate = useInvalidateMoney();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/budgets/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useMarkRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<Notification>(`/notifications/${id}/read`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

/** Start a bank connection or renewal, then hand the browser to the bank. */
export function useStartConsent() {
  return useMutation({
    mutationFn: (input: { institution_id: string } | { renew: string }) =>
      "renew" in input
        ? api<ConnectionStarted>(`/connections/${input.renew}/renew`, { method: "POST" })
        : api<ConnectionStarted>("/connections", { method: "POST", body: input }),
    onSuccess: (started) => window.location.assign(started.authorisation_url),
  });
}

export function useConnectionAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; action: "sync" | "disconnect" }) =>
      input.action === "sync"
        ? api(`/connections/${input.id}/sync`, { method: "POST" })
        : api(`/connections/${input.id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries(),
  });
}
