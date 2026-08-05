# One-time setup (per machine)

Everything here happens **once per computer** (e.g. Ken's Mac). Day-to-day operation is
in [WORKFLOW.md](WORKFLOW.md).

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

## 3. Authenticate the CLI (Application Default Credentials)

The CLI talks to Colab's backends with ADC. It needs **exactly these four scopes** —
a plain `gcloud auth application-default login` is NOT enough:

```bash
gcloud auth application-default login \
  --scopes=openid,\
https://www.googleapis.com/auth/cloud-platform,\
https://www.googleapis.com/auth/userinfo.email,\
https://www.googleapis.com/auth/colaboratory
```

Why each scope: `userinfo.email` (session backend, else 401), `colaboratory`
(keep-alive RPC, else 403 and the CLI un-assigns fresh VMs), `openid` + `cloud-platform`
(gcloud refuses scope lists without them).

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
./scripts/run_pipeline.sh 00     # preflight — expect ALL PREFLIGHT CHECKS PASSED
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
