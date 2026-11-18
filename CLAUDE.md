# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Internal web app that digitizes the company's purchase proposal and approval process (đề xuất mua sắm). It is a ground-up rewrite. The old system failed from over-engineering, so keep things simple: one Django process, one SQLite file, no frontend build step.

Sources of truth:
- **As-is doc:** https://claude.ai/artifact/2Xo6gEJGM3iJdvxzb1uX2T. This holds the business rules. Its "Quyết định cho bản viết lại" section lists what is in scope and what is deferred ("Để sau").
- **Old spec:** https://claude.ai/artifact/8A6xbF4srM7dEAViJrbFkP. Use it only as a feature catalog.

Do not add features the as-is doc defers, such as notifications, print templates, khảo giá or multi-supplier quotes.

Deployment:
- Runs on a single always-on Windows machine at `127.0.0.1:8100`.
- It is exposed through an existing Cloudflare Tunnel and must work on phones.
- Security hardening (django-axes and similar) and backups are deliberately deferred.

## Commands

The environment is Windows with Python 3.10 (kept on purpose) and a venv in `.venv`. Commands are written for PowerShell.

```powershell
.\dev.ps1                                   # dev server (DEBUG=1, autoreload) on 127.0.0.1:8100, runs migrate first
.\run.ps1                                   # production: migrate + collectstatic + waitress on 127.0.0.1:8100
.\.venv\Scripts\python.exe -m pytest -q     # all tests
.\.venv\Scripts\python.exe -m pytest tests/test_workflow.py::test_threshold_adds_chairman -q   # single test
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
$env:DEBUG="1"; .\.venv\Scripts\python.exe manage.py tao_du_lieu_mau   # 9 demo users, password 123456
```

Gotchas:
- **pytest is pinned `<9`.** pytest 9.2 crashes with pytest-django.
- **`runserver --noreload` caches templates.** Template edits do not show until you restart. `dev.ps1` uses autoreload, so it is fine.
- **Static files in production.** When `DEBUG` is off, static files go through WhiteNoise's manifest storage, so `collectstatic` must run first. `tests/conftest.py` overrides this, and also switches to the MD5 hasher so tests run fast.

Per-machine config lives in `.env`, which is gitignored and parsed by `config/settings.py`:
- `DEBUG=1`
- `HOSTS=localhost,127.0.0.1,<tunnel-domain>`

Non-local hosts are also added to `CSRF_TRUSTED_ORIGINS` as https.

All runtime data lives in `data/`, which is gitignored: `db.sqlite3` (WAL mode, IMMEDIATE transactions), `media/` and `secret_key.txt` (auto-generated).

## Architecture

The UI and all user-facing strings are in Vietnamese. Code identifiers are in English, and status and role codes are unaccented Vietnamese (`cho_truong_phong`, `giam_doc`, …). URLs are Vietnamese slugs (`/de-xuat/`, `/quan-tri/` for the admin).

**Apps**
- `accounts`: custom `User` (`AUTH_USER_MODEL = "accounts.User"`).
  - User fields: `department`, M2M `roles`, `manager` (the direct trưởng phòng), `must_change_password`, and bank-account fields for receiving money.
  - `Role` rows are fixed and seeded by migration `0002_seed_roles`. They are read-only in the admin, because approval rules depend on the role codes. Check roles with `user.has_role(Role.X, ...)`.
  - `ForcePasswordChangeMiddleware` locks a user onto `/doi-mat-khau/` until they change their password.
  - Only admins create accounts. Admin create and password reset set `must_change_password`. Note that `UserAdmin.save_model` makes `is_staff` mirror `is_superuser`.
- `core`: `AppSettings` singleton (`AppSettings.load()`, pk=1) holding `chairman_threshold` (default 10,000,000 đ), and `ReturnReason` (the quick-pick reasons for returning a proposal). Both are editable in the admin and seeded by migration.
- `proposals`: `Proposal`, `ProposalItem`, `PaymentRequest`, `Attachment` and `ApprovalLog`.
  - `ApprovalLog` rows for money steps carry both `proposal` and `payment`, so the proposal timeline also shows the money history.
  - Every `Attachment` belongs to a proposal (and optionally a payment). It is downloadable only through `views.attachment` (`/tep/<id>/`), which checks `visible_proposals`. There is no public media URL. Upload validation and image downscaling live in `proposals/attachments.py`.

**Rules live in two modules: `proposals/workflow.py` (proposal approval) and `proposals/payments.py` (money flow).**
- Views, templates and the nav context processor never check permissions themselves. They call:
  - `actions_for`
  - `pending_q` (the "Chờ tôi xử lý" query)
  - `visible_q` / `visible_proposals`
  - `can_create`
  - `timeline`
- Mutations go through `create` / `resubmit` / `approve` / `return_` / `cancel`. Each one:
  - runs in `transaction.atomic`;
  - re-reads the proposal inside the transaction (`_reload`), so two directors clicking at the same time cannot both approve;
  - raises `WorkflowError` (shown to the user as a flash message);
  - writes exactly one `ApprovalLog` row.
- `payments.py` mirrors the same pattern: `actions_for` / `pending_q` / `visible_payments` / `timeline`, and the mutations `create` / `resubmit` / `approve` / `return_` / `transfer` / `settle` / `cancel`. Approval steps are a table, `_APPROVAL_STEPS` (status → role, next status, return target).
- Change rules in these modules and cover them in `tests/test_workflow.py` / `tests/test_payments.py`.

**Flow**
1. Nhân viên creates the proposal.
2. It goes to the creator's `manager`. The manager is snapshotted onto the proposal at submit time.
3. Giám đốc approves. Any user with that role can do it, and one approval is enough.
4. Chủ tịch approves, only if `needs_chairman` (total ≥ threshold, computed at submit time).
5. The proposal reaches `da_duyet`. It shows in thu mua's "Chờ tôi xử lý" until a payment is opened.
6. When the payment reaches `hoan_tat`, the proposal becomes `hoan_thanh`.

Returning:
- Any approver can return the proposal. A reason is mandatory.
- The proposal goes back to the creator, who edits and resubmits. It then restarts at trưởng phòng with the total and `needs_chairman` recomputed, and keeps the same code.
- There is no limit on how many times this can happen.

Other rules:
- The creator can cancel while the proposal is returned or still at trưởng phòng.
- Codes are `MS-YYYYMM-NNNN`, never change, and are generated inside the create transaction.
- `Proposal` is view-only in the admin, so the history always stays consistent.

**Money flow** (`PaymentRequest`; one active, non-cancelled payment per proposal; codes `TU-…` / `TT-…`):
- **Tạm ứng (TU):** chủ tịch approves (even under the threshold) → kế toán `transfer` → `dang_mua` → thu mua `settle` (records `spent`; invoice optional) → chủ tịch approves → `hoan_tat`. If chủ tịch returns the settlement, it goes back to `dang_mua`, not `tt_tra_ve`.
- **Thanh toán tự ứng (TT):** an invoice is mandatory → kế toán approves → chủ tịch approves and refunds → `hoan_tat`.
- Money always goes to thu mua. The bank account is snapshotted from the user's profile, which users edit on `/tai-khoan/`. There is no direct-to-supplier payment.
- Over/under settlement (`difference` / `shortfall`) is shown on screen only. Multi-installment payment and detailed settlement are deferred.

**Frontend**
- Django templates plus HTMX and Alpine. Both libraries are vendored in `static/vendor/`; there is no Node.
- `static/js/app.js` loads before Alpine, so components register on `alpine:init`. It contains:
  - the `proposalForm` component (item rows, live total, route hint);
  - the wide-screen list+detail pane: clicks on `.js-pane-link` load `?pane=1`, which renders the `_detail.html` / `_payment_detail.html` partial into `#pane`.
- Money screens are in `proposals/views_money.py`. The home page mixes proposal cards and payment cards, with Alpine filter tabs.
- Shared partials: `_return_sheet.html` (mandatory-reason sheet; needs `action_url`, `recipient`, `reasons` inside an `x-data` that has `sheet`), `_timeline.html` and `_files.html`.
- The proposal form posts parallel arrays `item_name` / `item_qty` / `item_price`. They are parsed by `proposals/forms.py` (`parse_proposal`); there is no Django formset.
- `templates/proposals/list.html` filters with HTMX. On an `HX-Request`, the view returns only `_table.html`.
- One responsive UI serves phone, tablet and laptop. CSS tokens are in `static/css/app.css`.
  - Below 900px: a bottom tab bar.
  - From 900px: a sidebar.
  - From 1100px: the split list+detail view.
  - Pages that set the body class `no-tabbar` hide the tab bar on phones.
- Use the template filters `vnd` (18.500.000) and `qty` from `proposals/templatetags/money.py`.

**Design reference:** the mockups are on the claude.ai Design canvas https://claude.ai/artifact/XsYYsn3qXXgUrPNd1VeDGS (phone screens, laptop "Chờ tôi xử lý" / "Tất cả", tablet).

## Testing notes

- `tests/conftest.py` points `MEDIA_ROOT` at `tmp_path`, so uploads in tests never touch `data/`.
- `tests/conftest.py` provides an `org` fixture with a full sample org:
  - 2 departments, each with a trưởng phòng and a nhân viên;
  - 2 giám đốc, 1 chủ tịch, kế toán and thu mua (with a bank account).
- `make_user` re-fetches the user so the cached role set is fresh.
- The Django admin's password-change URL name is `admin:auth_user_password_change`, even with the custom user model.
- `json_script` escapes non-ASCII characters, so asserting Vietnamese text inside it fails. Assert against `r.context` instead.
