# Demo Script — Final Project Submission

A runbook to read from while recording, not a transcript to memorize. **SAY:**
lines are narration cues (paraphrase freely); everything else is a command to
run and show on screen. Total runtime ~10-12 minutes as scoped.

**Do not run a fresh full pipeline during recording** — `security-tests.yml`
takes ~30 minutes (Nikto is the long pole). Sections 2 and 4 below use
already-completed runs and one short, real `promote-prod.yml` dispatch
instead (that one's fast — a couple of minutes, no Nikto involved).

## Pre-flight (do this 10 minutes before you hit record, off-camera)

```bash
# Confirm both live targets are healthy before you rely on them on camera
curl -sk -o /dev/null -w 'Staging: %{http_code}\n' \
  --resolve paymenter.homelab.local:443:10.0.20.20 https://paymenter.homelab.local/
ssh -i ~/.ssh/id_ed25519_deploy hveno@10.0.20.30 \
  "curl -sk -o /dev/null -w 'Prod-DMZ: %{http_code}\n' --resolve paymenter.homelab.local:443:127.0.0.1 https://paymenter.homelab.local/"

# Confirm there's a promotable digest
gh variable list | grep STAGING_VALIDATED_DIGEST

# Export the remember-me cookie for Section 5 — pull the value from your own
# secret notes (NOT committed anywhere, and don't paste it in the recording
# either — just export it in a terminal that isn't on screen yet). It's a
# real auth-bypass credential against a live host.
export REMEMBER_COOKIE='<the value you saved when you first ran security-tests.yml — see docs/maintenance-guide.md "Regenerate the auth test credentials" if you need a fresh one>'
```

Have two things open before you start: a terminal on the Runner, and a
browser tab on this repo's **Actions** tab (logged in as yourself, since
Section 4 needs you to click an approval button).

---

## 1. Intro (30-45s)

**SAY:** what the project is — an on-premise DevSecOps pipeline for
Paymenter, a self-hosted GitHub Actions runner doing every build/scan/deploy,
with a true DMZ in production (not just a diagram — segmentation that
actually blocks traffic, which you'll prove live in a minute).

Optional: have `docs/network-topology.md`'s table on screen for 5 seconds
while you say this.

## 2. Pipeline overview (1 min)

On the **Actions** tab, show the four workflows:

**SAY:** `ci.yml` runs SAST/secrets/IaC/SCA on every push — Semgrep,
ESLint-security, Gitleaks, Hadolint, Trivy-config, Dependency-Check.
`deploy.yml` builds the hardened image, Trivy-scans it, and deploys to
Staging over SSH — not locally, for real, over the actual pipeline.
`security-tests.yml` runs the DAST/regression suite against the deployed
app. `promote-prod.yml` is the piece you'll trigger live in a few minutes.

Click into a recent green `ci.yml` run, show the 6 jobs. Click into a
recent `deploy.yml` run, show `build → trivy-scan → deploy` all green.

**SAY:** every one of these gates was calibrated against real findings, not
placeholders — `docs/allowlist.md` documents every exception and why.

## 3. True DMZ segmentation — the core security claim, proven live (2-3 min)

**SAY:** production isn't a single host behind a proxy — Prod-DMZ runs only
the reverse-proxy/WAF and is the *only* public-facing host; Prod-App has no
public network interface at all. Here's proof that's actually enforced, not
just drawn in a diagram.

```bash
# From the Runner: try to reach Prod-App directly. It should hang/time out —
# the Runner isn't in the allowlist for Prod-App's app port at all.
timeout 5 curl -sk https://10.0.20.31/ ; echo "exit: $?"
```

**SAY:** that's not a typo or a missing route — it's a firewall rule
(`DOCKER-USER` chain) that only allows Prod-DMZ's internal address to reach
that port. Now the same request, routed correctly:

```bash
# Through Prod-DMZ, over its dedicated internal link (prodint) to Prod-App
ssh -i ~/.ssh/id_ed25519_deploy hveno@10.0.20.30 \
  "curl -sk --resolve paymenter.homelab.local:443:127.0.0.1 https://paymenter.homelab.local/ -o /dev/null -w 'HTTP %{http_code}\n'"
```

**SAY:** and that hop itself is TLS-encrypted and certificate-*pinned* —
Prod-DMZ doesn't just trust any cert claiming to be Prod-App, it validates
the specific certificate:

```bash
# Fingerprint match: Prod-App's real cert vs. what Prod-DMZ has pinned
ssh -i ~/.ssh/id_ed25519_deploy hveno@10.0.20.31 \
  "echo password | sudo -S cat /home/hveno/Paymenter-CICD/docker/secrets/certs/fullchain.pem 2>/dev/null" \
  | openssl x509 -noout -fingerprint -sha256
ssh -i ~/.ssh/id_ed25519_deploy hveno@10.0.20.30 \
  "echo password | sudo -S cat /home/hveno/Paymenter-CICD/docker/secrets/certs/app-fullchain.pem 2>/dev/null" \
  | openssl x509 -noout -fingerprint -sha256
```

**SAY:** identical fingerprints — that's the pin actually working, not
decorative.

## 4. Approval-gated production promotion, live (2-3 min)

**SAY:** getting code to production isn't automatic on push — it's a
separate, deliberate, human-approved action, and the promoted image is
*provably* the exact same bytes that were scanned and health-checked on
Staging, by content digest, not a rebuild.

```bash
gh workflow run promote-prod.yml
```

Switch to the browser, refresh the Actions tab, click into the new run.

**SAY:** watch — it's not running. It's paused at a required-reviewer gate.

Point at the "Review deployments" banner, click it, approve.

**SAY:** now it proceeds — pulling that exact digest onto Prod-App, bringing
up both compose stacks, and confirming end-to-end.

Wait for it to go green (~1-2 min), then back to the terminal:

```bash
# Prove it: the digest actually running matches what was promoted
gh variable list | grep STAGING_VALIDATED_DIGEST
ssh -i ~/.ssh/id_ed25519_deploy hveno@10.0.20.31 \
  "docker inspect docker-paymenter-1 --format '{{.Image}}'"
```

**SAY:** same digest, both places — the approval gate promoted exactly what
was validated, nothing rebuilt in between.

## 5. A real vulnerability the pipeline actually caught (2-3 min)

This is the strongest section — lead with it if you're tight on time and
need to cut something else.

**SAY:** the regression suite isn't just infrastructure checks — it caught
a real, live authentication bypass in the app itself. Here it is:

```bash
# Only a remember-me cookie — no session, no password, no 2FA
ssh -i ~/.ssh/id_ed25519_deploy hveno@10.0.20.20 \
  "curl -sk -H 'Cookie: paymenter_remember=$REMEMBER_COOKIE' https://paymenter.homelab.local/admin -o /dev/null -w 'HTTP %{http_code}\n'"
```

**SAY:** that's `HTTP 200` — the full admin panel — from a cookie that's
supposed to only support a "remember me" convenience flow, not stand in for
real authentication. This is exactly the class of bug Lab 5's MFA-bypass
fix was supposed to close, and it's regressed.

Show `security/tests/auth/test_remember_mfa_bypass.py` on screen briefly
(the docstring explains the intended fix in one sentence).

```bash
cd security/tests
BASE_URL="https://paymenter.homelab.local" VERIFY_TLS=false \
  python3 -m pytest -v auth/test_remember_mfa_bypass.py
```

**SAY:** and there's the regression suite catching it automatically —
`FAILED`, not a silent pass. That's the whole point of Stage 3: this isn't
a one-time manual pentest, it's a check that runs on every deploy and would
have caught this the moment it regressed.

## 6. Closing (30-45s)

**SAY:** recap — self-hosted pipeline, real findings fixed along the way
(CVE patched, CSP added, a firewall bug that was silently blocking a
container's own outbound traffic), a true DMZ with proven segmentation, an
approval-gated promotion path with a content-addressed guarantee, and a
regression suite that just demonstrated it catches real bugs, not just
infra drift. Point to `docs/report-summary.md` and `docs/allowlist.md` for
the full writeup.

---

## If something doesn't cooperate live

- **Section 3's timeout takes too long on camera** — cut the `timeout 5` to
  `timeout 2`; the point lands in 2 seconds just as well.
- **`promote-prod.yml` fails for an unrelated transient reason** — you have
  a full successful run's evidence already in
  `evidence/phase2-promotion/promote-prod-e2e.txt`; narrate over that
  instead of re-running live.
- **The remember-cookie demo stops reproducing** (e.g. the user's
  `remember_token` got rotated) — regenerate per
  `docs/maintenance-guide.md`'s "Regenerate the auth test credentials"
  section *before* recording, not during.
- **Staging or a prod host is unreachable** — check `docker ps` on the
  relevant host before you're on camera; don't debug infrastructure live.
