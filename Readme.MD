# option-chain launcher (public repo)

This repo contains NO secrets and NO strategy code. It only:
1. clones your private repo using a token stored in GitHub Secrets,
2. starts it behind a password gate,
3. opens a Cloudflare tunnel,
4. sends the link to your phone through ntfy.sh (the link is never printed in the public log).

## Files
- `.github/workflows/run.yml`  (put `run.yml` here)
- `run_site.py`
- `login_gate.py`

## Setup
1. Create a NEW PUBLIC repo, e.g. `v22-launcher`, and upload the 3 files above
   (`run.yml` must be at `.github/workflows/run.yml`).
2. Make a fine-grained token: GitHub -> Settings -> Developer settings -> Fine-grained tokens
   -> only repository `italisa800-tech/v22`, permission **Contents: Read-only**.
3. In the launcher repo: Settings -> Secrets and variables -> Actions -> New repository secret:

| Secret | Value |
|---|---|
| `PRIVATE_REPO` | `italisa800-tech/v22` |
| `GH_PAT` | the new read-only token |
| `GATE_PASSWORD` | your NEW password |
| `GATE_LINK_KEY` | your NEW auto-login key |
| `NTFY_TOPIC` | a long random word, e.g. `v22-k8f3x9q2m7` |

   Optional variable (Variables tab): `SYMBOL` = `NIFTY`.
4. Install the **ntfy** app on your phone and subscribe to the same topic name.
5. Actions tab -> option-chain-site -> **Run workflow** to test. The link arrives in ntfy in ~1-2 min.

## Rules / limits
- Public repo = unlimited free Actions minutes. Private repo = only 2,000 min/month.
- One job lasts at most 6 h, so two scheduled runs (09:00 and 14:25 IST) cover the day.
- Scheduled runs can start a few minutes late; the 14:25 run overlaps the first one on purpose.
- The tunnel URL changes on every run, so always use the newest ntfy message.
- Scheduled workflows stop after 60 days without repo activity; push a small commit to re-enable.
- Never print secrets and never commit them. Anyone can read a public repo's logs.
