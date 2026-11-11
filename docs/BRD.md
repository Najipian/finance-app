# Onesum — Business Requirements (BRD)

Version 0.1 draft · Owner: Amr Najip · 2026-11-08

## Document control

This BRD defines what the MVP of Onesum must do, for whom, and how success is judged. The technical design lives in `technical-design.md`.

| Field | Value |
| --- | --- |
| Product | Onesum (named 2026-11-11; "Finance App" was the working name) |
| Version | 0.1 draft |
| Owner | Amr Najip |
| Type | Portfolio project, open source on GitHub |
| Banking data | UK/EU Open Banking sandbox (Yapily) |
| Target delivery | MVP in 6 weeks |

## Executive summary and objectives

Onesum lets a user connect several bank accounts through Open Banking, see all balances and transactions in one place, and track spending against monthly budgets. Its business purpose is to prove production-grade fintech skills to employers in the UK, Europe, Australia and New Zealand.

| ID | Objective | Measure of success |
| --- | --- | --- |
| OBJ-1 | Show real Open Banking integration | Live sandbox connection to 2+ test banks, consent flow end to end |
| OBJ-2 | Show a modern cloud-native stack | Python + FastAPI, Docker, CI, deployed on AWS |
| OBJ-3 | Show banking-grade engineering | Encrypted tokens, idempotent sync, audit log, tests |
| OBJ-4 | Be easy to evaluate | Public repo, README, architecture diagram, demo video under 3 minutes |
| OBJ-5 | Support the job search | Linked from the CV and used as an interview talking point |

## Scope

The MVP covers read-only account information (AIS). Moving money (payment initiation) is out of scope.

**In scope (MVP)**

- User sign-up, login and profile
- Connect bank accounts through the Open Banking consent flow, including consent renewal and revocation
- Aggregated view of accounts and balances across banks
- Scheduled transaction sync with deduplication
- Rule-based auto-categorization, with manual re-categorization
- Monthly budgets per category, with alerts when nearing or over the limit
- Dashboard with spending charts by category and month
- Installable PWA that works on mobile and desktop

**Out of scope (later phases)**

- Payments, transfers or Variable Recurring Payments
- Real customers or production banking licence
- Native iOS/Android apps
- ML-based categorization, savings goals, shared household accounts
- Gulf banks (no consumer Open Banking sandbox used for now)

## Stakeholders and personas

| Stakeholder | Interest | What they need from the app |
| --- | --- | --- |
| Amr Najip (owner, developer) | Portfolio and interview material | Clean, finished scope in 6 weeks |
| Hiring managers and recruiters | Judge skills in minutes | Live demo, README, diagram, short video |
| Technical interviewers | Probe design decisions | Readable code, tests, documented trade-offs |
| End user (persona below) | Understand their money | Simple setup, accurate data, clear charts |
| Open Banking provider (Yapily) | Correct API use | Respect consent and rate limits |

**Persona: Sara, 32, salaried professional in London**

- Has a current account, a savings account and a credit card at three banks
- Checks three apps to know where her money went each month
- Wants one view, automatic categories, and a warning before she overspends on eating out

## Business requirements

Twelve requirements make up the MVP; nine are Must-haves. Priority uses MoSCoW.

| ID | Requirement | Module | Priority |
| --- | --- | --- | --- |
| BR-01 | A user can register and log in securely | Auth | Must |
| BR-02 | A user can connect a bank account by giving consent at the bank | Connections | Must |
| BR-03 | The app warns before consent expires and lets the user renew it | Connections | Must |
| BR-04 | A user can disconnect a bank and have its data deleted | Connections | Must |
| BR-05 | The app shows all accounts and balances across banks in one view | Accounts | Must |
| BR-06 | Transactions sync automatically and never appear twice | Transactions | Must |
| BR-07 | Transactions are categorized automatically | Categories | Must |
| BR-08 | A user can change a category and create their own rules | Categories | Should |
| BR-09 | A user can set a monthly budget per category | Budgets | Must |
| BR-10 | The app alerts at 80% and 100% of a budget | Budgets | Should |
| BR-11 | A dashboard shows spending by category and by month | Dashboard | Must |
| BR-12 | A user can export transactions to CSV | Transactions | Could |

## User stories and acceptance criteria

**US-01 Connect a bank (BR-02)** — As Sara, I want to connect my bank so I can see my accounts here.

- Given I pick a bank, when I approve consent at the bank, then I return to the app and its accounts appear within 60 seconds
- Given I cancel at the bank, then no data is stored and I see a clear message

**US-02 Renew consent (BR-03)** — As Sara, I want a reminder before access expires so my data stays current.

- Given consent expires in 7 days or less, then the dashboard shows a renew banner
- Given consent has expired, then sync stops and the bank is marked "Needs renewal"

**US-03 Disconnect a bank (BR-04)** — As Sara, I want to remove a bank and know its data is gone.

- Given I disconnect, then consent is revoked at the provider and that bank's accounts and transactions are deleted

**US-04 See everything in one place (BR-05)** — As Sara, I want one view of all balances so I know my position.

- Given 2+ banks are connected, then I see each account and a total per currency

**US-05 No duplicate transactions (BR-06)** — As Sara, I want each transaction once, even after repeated syncs.

- Given the same transaction arrives twice, then it is stored once
- Given a pending transaction later books, then it updates in place

**US-06 Automatic categories (BR-07, BR-08)** — As Sara, I want spending sorted for me, and to fix mistakes.

- Given a new transaction, then a category is assigned by rules, or "Uncategorized"
- Given I change a category and tick "apply to similar", then a rule is saved and used for future transactions

**US-07 Budgets and alerts (BR-09, BR-10)** — As Sara, I want a warning before I overspend.

- Given a budget of 300 GBP for Eating out, when spending reaches 240 GBP, then I get an 80% alert, and at 300 GBP a 100% alert

**US-08 Dashboard (BR-11)** — As Sara, I want charts so I can see trends at a glance.

- Given 3+ months of data, then I see spending by category this month and a 6-month trend

## Non-functional requirements

| ID | Area | Requirement |
| --- | --- | --- |
| NFR-01 | Security | Bank access tokens encrypted at rest (AES-256-GCM); keys outside the database |
| NFR-02 | Security | HTTPS only; passwords hashed with Argon2id; JWT with short expiry and refresh |
| NFR-03 | Security | OWASP Top 10 reviewed; dependency scanning in CI |
| NFR-04 | Privacy | GDPR-style rights: export my data, delete my account and all bank data |
| NFR-05 | Privacy | Store only data needed for the features; no card numbers |
| NFR-06 | Auditability | Every consent, sync and deletion written to an audit log |
| NFR-07 | Reliability | Sync jobs idempotent, retried with backoff, failures visible to the user |
| NFR-08 | Performance | Dashboard loads in under 2 seconds with 12 months of data |
| NFR-09 | Availability | Demo environment up during job-application periods; no formal SLA |
| NFR-10 | Quality | 70%+ test coverage on backend services; API documented in OpenAPI |
| NFR-11 | Usability | Responsive from 360 px wide; WCAG 2.1 AA contrast; English UI |
| NFR-12 | Portability | Runs locally with one command (Docker Compose) |

## Assumptions, constraints and dependencies

**Assumptions**

- Sandbox data is enough to demonstrate every feature; no real customers are needed
- The owner works on the project part time, about 10–15 hours a week, alongside a full-time job
- Reviewers will spend 5–10 minutes on the repo, so the README and demo carry most of the impact

**Constraints**

- Production Open Banking access needs a licensed provider and paid tier, so the app stays on sandbox
- Budget near zero: free tiers for hosting where possible (one small AWS instance)
- 6-week timebox for the MVP

**Dependencies**

| Dependency | Used for | Fallback |
| --- | --- | --- |
| Yapily sandbox | Bank connections, accounts, transactions | TrueLayer sandbox behind the same adapter |
| AWS | Hosting the demo | Any VPS |
| GitHub + GitHub Actions | Code and CI | — |
| Email provider (free tier) | Budget alerts | In-app notifications only |

GoCardless Bank Account Data (ex-Nordigen) is not an option: it is closed to new signups.

## Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Learning curve on the chosen stack slows weeks 1–2 | Schedule slips | Week 1 is set aside for foundations and learning |
| Sandbox data is thin or unrealistic | Charts look empty in the demo | Seed script that generates 12 months of realistic transactions |
| Provider changes or limits sandbox access | Integration blocked | Adapter pattern; TrueLayer as second provider |
| Scope creep (payments, ML, mobile) | MVP never ships | Strict Won't list; ship first, add later |
| Security weakness found by a reviewer | Hurts credibility | Encryption, OWASP checklist, dependency scanning, security note in README |
| Demo environment down when a recruiter clicks | Lost chance | Health check alert; demo video as backup |

## Milestones and success metrics

The MVP is done when every Must requirement passes its acceptance criteria and OBJ-1 to OBJ-4 are met.

| Week | Milestone | Covers |
| --- | --- | --- |
| 1 | Foundations | Repo, Docker, CI skeleton, auth (BR-01) |
| 2 | Bank connection | Provider adapter, sandbox consent, accounts (BR-02, BR-05) |
| 3 | Transactions | Sync, dedup, consent renewal, disconnect (BR-03, BR-04, BR-06) |
| 4 | Categories and budgets | Rules, re-categorize, budgets, alerts (BR-07 to BR-10) |
| 5 | Dashboard, hardening | PWA charts, token encryption, tests, audit log (BR-11) |
| 6 | Ship | AWS deploy, README, diagram, demo video, CV link |
| Gate | MVP live | Every Must requirement passes its acceptance criteria |

If week 1 runs long, BR-12 (CSV export) is the first item to drop.

## Glossary

| Term | Meaning |
| --- | --- |
| Open Banking | Regulated access to bank data and payments through APIs, with the customer's consent |
| AIS | Account Information Service: reading balances and transactions (this app) |
| PIS | Payment Initiation Service: starting payments (out of scope) |
| ASPSP | The bank that holds the account |
| AISP | The licensed provider allowed to read account data (here, Yapily) |
| Consent | The customer's permission, given at their bank, for a set time |
| PSD2 | The EU directive behind Open Banking in Europe |
| Sandbox | Test environment with fake banks and data |
| MoSCoW | Must, Should, Could, Won't priority scale |

## Sources

- [Free and indie Open Banking APIs — Open Banking Tracker](https://openbankingtracker.com/guides/free-open-banking-apis)
- [Open Banking sandbox comparison — Finexer](https://blog.finexer.com/open-banking-sandbox/)
