/** Friendly aliases for the generated OpenAPI types (src/api/schema.d.ts). */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type User = Schemas["UserRead"];
export type Institution = Schemas["InstitutionRead"];
export type Connection = Schemas["ConnectionDetail"];
export type ConnectionStarted = Schemas["ConnectionStarted"];
export type AccountsOverview = Schemas["AccountsOverview"];
export type Account = Schemas["AccountRead"];
export type Transaction = Schemas["TransactionRead"];
export type TransactionPage = Schemas["TransactionPage"];
export type RecategorizeResult = Schemas["RecategorizeResult"];
export type Category = Schemas["CategoryRead"];
export type Budget = Schemas["BudgetRead"];
export type Notification = Schemas["NotificationRead"];
export type DashboardSummary = Schemas["DashboardSummary"];
export type CurrencySummary = Schemas["CurrencySummary"];
