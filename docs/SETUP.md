# One-time setup (per machine)

Everything here happens **once per computer** (e.g. Ken's Mac). Day-to-day operation is
in [WORKFLOW.md](WORKFLOW.md). For **local (no-Colab) execution**, do § 2–3 below plus
`./scripts/setup_local.sh` — details in [LOCAL.md](LOCAL.md); § 0–1 and 4 are only
needed for the Colab path.

## 0. Prerequisites

- **Colab subscription with GPU entitlement.** A100s require Colab Pro/Pro+ and consume
  compute units while a session is up. `colab pay` opens the subscription page.
  If `colab new --gpu A100` returns a 400, the account lacks quota for that accelerator —
  fall back to `--gpu T4` (slower sampling) or check the plan.
- **Google account** with access to: BigQuery project `donut-426`, the `ABC/MMM` Drive
  folder, and the dashboard spreadsheet. (All one account: ken@donutanalytics.com.)
- macOS or Linux (the CLI does not support Windows).

## 1. Install the Colab CLI

```bash
# uv (recommended; installs its own Python if needed — CLI requires Python >= 3.12)
curl -LsSf https://astral.sh/uv/install.sh | sh   # if uv isn't installed yet
uv tool install google-colab-cli

colab version   # should print 0.6.0 or newer
```

If `colab` isn't found afterwards, ensure `~/.local/bin` is on PATH (`uv tool update-shell`).

## 2. Install gcloud (needed once, for auth)

```bash
brew install google-cloud-sdk        # macOS
# or https://cloud.google.com/sdk/docs/install
```

## 3. Authenticate with Google (Application Default Credentials)

**The Drive scope is NOT optional here.** The `abc.mmm` BigQuery view reads a
Google-Sheets-backed external table (the "ABC MMM Inputs" sheet), so *any* query
against it — i.e. the core pipeline, not just step 05 — needs Drive-scoped
credentials. BigQuery fails with `Permission denied while getting Drive credentials`
otherwise (hit on first local run, 2026-08-05). On Colab this is invisible because
`colab auth` always grants Drive access.

Because `drive` is a sensitive scope, Workspace **blocks** the login ("This app is
blocked") until the gcloud OAuth client is trusted. So setup is two sub-steps:

### 3a. Trust the gcloud app in Workspace admin (once, needs the donutanalytics.com admin)

admin.google.com → **Security → Access and data control → API controls →
Manage third-party app access** → **Configure new app** → search by OAuth client ID:

```
764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com
```

→ select "Google Cloud SDK" → apply to everyone → **Trusted**. Allow a few minutes
to propagate.

### 3b. Mint ADC with the full scope list

A plain `gcloud auth application-default login` is NOT enough:

```bash
gcloud auth application-default login \
  --scopes=openid,\
https://www.googleapis.com/auth/cloud-platform,\
https://www.googleapis.com/auth/userinfo.email,\
https://www.googleapis.com/auth/colaboratory,\
https://www.googleapis.com/auth/drive,\
https://www.googleapis.com/auth/spreadsheets
```

Why each scope: `userinfo.email` (Colab session backend, else 401), `colaboratory`
(Colab keep-alive RPC, else 403 and the CLI un-assigns fresh VMs), `openid` +
`cloud-platform` (gcloud refuses scope lists without them; `cloud-platform` also
covers BigQuery's API), `drive` (BigQuery's Sheets-backed source table — required
by every pipeline run), `spreadsheets` (step 05's dashboard upload via gspread).

**Verify:**

```bash
colab whoami     # prints active email, scopes, expiry (hidden debug command)
colab sessions   # read-only; succeeding = auth works
```

If any CLI call 403s against `colab.pa.googleapis.com`, it is almost always a missing
scope — re-run the gcloud command above.

## 4. First session walkthrough

```bash
cd <this repo>
./scripts/provision.sh
```

This allocates the A100, installs Meridian on the VM, and then (because you're in a real
terminal) walks you through the **two interactive steps**:

1. `colab auth -s mmm` — puts Google credentials **on the VM** so kernel code can reach
   BigQuery/Sheets/Drive APIs. (Different thing from step 3, which authenticated the CLI
   itself. Both are needed.)
2. `colab drivemount -s mmm` — mounts your Drive at `/content/drive` so outputs land in
   `My Drive/ABC/MMM`.

Both must be redone for each **new** session/VM (they die with the VM); the pipeline's
preflight (`./scripts/run_pipeline.sh 00`) tells you exactly which one is missing.

Then:

```bash
./scripts/run_pipeline.sh 00     # preflight — expect PREFLIGHT OK
./scripts/run_pipeline.sh        # full run: fit + save + diagnostics + ROAS + decay
./scripts/teardown.sh            # when done for the day
```

## Notes for agent-driven use (Claude Code)

- Agents can run everything **except** `colab auth` / `colab drivemount` / `repl` /
  `console` — those need a human TTY. When an agent hits a missing-auth error it should
  ask you to run the exact command it prints.
- Parallel agent runs should isolate session state:
  `colab --config /tmp/agent-session.json new -s job` (see `colab skill` for details).
- `colab skill` prints the CLI's own agent-facing documentation — the authoritative
  reference for command behavior, gotchas, and recovery.
