import { Link, useSearchParams } from "react-router";

import { useConnectionAction, useConnections, useInstitutions, useStartConsent } from "../api/hooks";
import { Empty, ErrorMessage, Loading, PageHeader } from "../components/ui";
import { formatDate } from "../lib/format";

const STATUS_LABEL: Record<string, string> = {
  active: "Connected",
  needs_renewal: "Needs renewal",
  revoked: "Revoked",
  pending: "Pending",
};

export function BanksPage() {
  const connections = useConnections();
  const institutions = useInstitutions();
  const start = useStartConsent();
  const action = useConnectionAction();

  return (
    <div className="space-y-6">
      <PageHeader title="Banks" />
      <ErrorMessage error={start.error ?? action.error} />
      <section aria-label="Connected banks" className="space-y-3">
        {connections.isPending && <Loading />}
        {connections.data?.length === 0 && <Empty title="No banks connected yet" />}
        {connections.data?.map((c) => (
          <div key={c.id} className="card flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="font-semibold">{c.institution_name}</p>
              <p className="text-sm text-muted">
                {STATUS_LABEL[c.status] ?? c.status}
                {c.last_synced_at && ` · synced ${formatDate(c.last_synced_at)}`}
                {c.last_sync_status === "failed" && <span className="font-semibold text-danger"> · sync failed</span>}
                {c.last_sync_status === "retrying" && " · retrying sync"}
                {c.days_until_expiry !== null && c.status === "active" && ` · access for ${c.days_until_expiry} more days`}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {c.status === "active" && (
                <button type="button" className="btn-secondary" disabled={action.isPending} onClick={() => action.mutate({ id: c.id, action: "sync" })}>
                  Sync now
                </button>
              )}
              {(c.renewal_due || c.status === "needs_renewal") && (
                <button type="button" className="btn-primary" disabled={start.isPending} onClick={() => start.mutate({ renew: c.id })}>
                  Renew
                </button>
              )}
              <button
                type="button"
                className="btn-danger"
                disabled={action.isPending}
                onClick={() => {
                  if (window.confirm(`Disconnect ${c.institution_name}? Its accounts and transactions will be deleted.`)) {
                    action.mutate({ id: c.id, action: "disconnect" });
                  }
                }}
              >
                Disconnect
              </button>
            </div>
          </div>
        ))}
      </section>
      <section aria-labelledby="connect-heading" className="card">
        <h2 id="connect-heading" className="mb-1 font-semibold">
          Connect a bank
        </h2>
        <p className="mb-3 text-sm text-muted">You approve read-only access at your bank. We can never move money.</p>
        {institutions.isPending && <Loading label="Loading banks…" />}
        <ul className="grid gap-2 sm:grid-cols-2">
          {institutions.data?.map((i) => (
            <li key={i.id}>
              <button
                type="button"
                className="btn-secondary w-full justify-start"
                disabled={start.isPending}
                onClick={() => start.mutate({ institution_id: i.id })}
              >
                {i.logo_url && <img src={i.logo_url} alt="" className="size-5" />}
                {i.name}
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

const RESULT_MESSAGES: Record<string, { title: string; body: string }> = {
  connected: { title: "Bank connected", body: "Your accounts will appear in a few seconds." },
  cancelled: { title: "Connection cancelled", body: "Nothing was shared or stored." },
  error: { title: "Something went wrong", body: "The bank connection couldn't be completed. Please try again." },
  invalid_state: { title: "Link expired", body: "This connection link is no longer valid. Please start again." },
};

/** Where the API's consent callback sends the browser (?status=...). */
export function ConnectionResultPage() {
  const [params] = useSearchParams();
  const message = RESULT_MESSAGES[params.get("status") ?? ""] ?? RESULT_MESSAGES.error;
  return (
    <div className="mx-auto max-w-md">
      <div className="card text-center" role="status">
        <h1 className="text-xl font-bold">{message.title}</h1>
        <p className="mt-2 text-sm text-muted">{message.body}</p>
        <div className="mt-4 flex justify-center gap-2">
          <Link to="/" className="btn-primary">
            Go to dashboard
          </Link>
          <Link to="/banks" className="btn-secondary">
            Banks
          </Link>
        </div>
      </div>
    </div>
  );
}
