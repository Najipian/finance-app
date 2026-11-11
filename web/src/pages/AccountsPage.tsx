import { Link } from "react-router";

import { useAccounts } from "../api/hooks";
import type { Account } from "../api/types";
import { Empty, ErrorMessage, Loading, Money, PageHeader } from "../components/ui";

export function AccountsPage() {
  const { data, isPending, error } = useAccounts();
  const byBank = new Map<string, Account[]>();
  for (const account of data?.accounts ?? []) {
    byBank.set(account.institution_name, [...(byBank.get(account.institution_name) ?? []), account]);
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Accounts" />
      {isPending && <Loading />}
      <ErrorMessage error={error} />
      {data && data.accounts.length === 0 && (
        <Empty title="No accounts yet">
          <Link to="/banks" className="btn-primary mt-3">
            Connect a bank
          </Link>
        </Empty>
      )}
      {data && data.totals.length > 0 && (
        <section aria-label="Totals" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {data.totals.map((t) => (
            <div key={t.currency} className="card">
              <p className="text-sm text-muted">
                Total {t.currency} · {t.account_count} account{t.account_count > 1 ? "s" : ""}
              </p>
              <p className="text-2xl font-bold">
                <Money amount={t.amount} currency={t.currency} />
              </p>
            </div>
          ))}
        </section>
      )}
      {[...byBank.entries()].map(([bank, accounts]) => (
        <section key={bank} className="card" aria-label={bank}>
          <h2 className="mb-2 font-semibold">{bank}</h2>
          <ul className="divide-y divide-black/5">
            {accounts.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-3 py-3">
                <div>
                  <p className="font-medium">{a.name}</p>
                  <p className="text-xs text-muted">
                    {a.type.replaceAll("_", " ").toLowerCase()} {a.account_number_masked && `· ${a.account_number_masked}`}
                    {a.connection_status === "needs_renewal" && " · needs renewal"}
                  </p>
                </div>
                <p className="text-right font-semibold">
                  {a.balance ? <Money amount={a.balance.amount} currency={a.balance.currency} /> : <span className="text-muted">–</span>}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
