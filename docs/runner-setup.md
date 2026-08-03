# Self-Hosted Runner Setup (Stage 1)

The pipeline executes entirely on your homelab. GitHub's cloud is only the code
host, trigger, and Issues surface — see the on-premise justification in
[../README.md](../README.md).

## Quick start — one command (any Linux machine)

`scripts/runner-up.sh` downloads, configures, and starts the runner. The same
script works on WSL2-Ubuntu and the homelab — register each machine once, then
re-run to start it anytime:

```bash
REPO=<owner>/<repo> ./scripts/runner-up.sh            # if gh is installed+auth'd
REPO=<owner>/<repo> RUNNER_TOKEN=<token> ./scripts/runner-up.sh   # else paste a token
REPO=<owner>/<repo> AS_SERVICE=1 ./scripts/runner-up.sh  # + survives reboot (systemd)
```

`gh auth login` (no browser on a headless VM) uses the device-code flow:
`gh` prints a one-time code and a URL — open the URL on any device, enter the
code, done. `./scripts/runner-up.sh` itself needs `chmod +x` if cloned fresh
(it wasn't committed with the executable bit, a real bug caught running this
in Phase 1).

**Note:** `./scripts/runner-up.sh` needs to be run *manually* (not
autonomously) since it requires either `gh auth login`'s interactive
device-code approval or a token pasted from the GitHub UI — a Claude Code
instance can drive the rest of setup but can't complete this step alone.

Both machines can stay registered; a job runs on whichever runner is online. If
both are up, steer specific jobs with labels — e.g. register the homelab with
`LABELS=self-hosted,homelab` and set the deploy job to `runs-on: [self-hosted,
homelab]`, so deploys only ever land on the homelab.

### Running it in WSL2 first (this dev machine)

You currently have no general-purpose WSL distro (only Docker's internal one), so
one-time:

```powershell
wsl --install -d Ubuntu          # reboot / create a UNIX user when prompted
```
Then Docker Desktop → Settings → Resources → WSL Integration → enable **Ubuntu**
(so `docker` works inside it). Inside Ubuntu:
```bash
sudo apt-get update && sudo apt-get install -y curl
# optional but makes the runner script one-command:
#   sudo apt-get install -y gh && gh auth login
REPO=<owner>/<repo> ./scripts/runner-up.sh
```

**WSL2 caveat:** build/scan/test stages work (they share Docker Desktop). The
`deploy`/Ansible/nftables stages are real Linux-host operations (systemd,
firewall) that don't meaningfully apply in WSL2 — run those on the homelab.

## 1. Register the runner (manual, what the script automates)

On the homelab host (or a dedicated VM/container on it — record which, it
affects your segmentation diagram):

1. GitHub repo → **Settings → Actions → Runners → New self-hosted runner**.
2. Follow the generated commands (download, `./config.sh --url … --token …`).
3. Install as a service so it survives reboots:
   ```bash
   sudo ./svc.sh install
   sudo ./svc.sh start
   sudo ./svc.sh status
   ```

## 2. Host prerequisites

The workflows assume these are on the runner host (installed once, not per-job).
Use Docker's **official apt repo**, not Ubuntu's `docker.io` package (older,
diverges from what's validated here):

```bash
# Docker CE via the official repo (see docker.com/engine/install/ubuntu for the
# keyring/repo setup) — NOT `apt-get install docker.io`
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo apt-get install -y ansible python3-pip nikto gh
ansible-galaxy collection install ansible.posix   # harden.yml needs this
sudo usermod -aG docker "$(whoami)"   # let the runner user drive Docker
# Group membership only applies to NEW sessions (fresh SSH connections, the
# runner service's own process) — a shell open from before this command won't
# see it. Use `sg docker -c "..."` there instead of logging out/in mid-session.
```

`python3-pip` matters even though `python3` ships by default — `pip`/`pip3`
don't, and `security-tests.yml`'s `regression-tests` job needs them.

**Two separate sudo needs, don't conflate them:**
1. **The runner's own local sudo** — used by `.github/actions/reclaim-workspace`
   to `chown` the shared `_work` directory back after Docker-based actions
   leave root-owned files in it (self-hosted runners reuse `_work` across every
   job, unlike GitHub-hosted ephemeral runners). Scope this narrowly, not
   blanket `NOPASSWD:ALL`:
   ```bash
   printf 'hveno ALL=(root) NOPASSWD: /usr/bin/chown\n' | sudo tee /etc/sudoers.d/hveno-ci-chown
   sudo chmod 440 /etc/sudoers.d/hveno-ci-chown
   ```
2. **Ansible `become` on deploy targets** (Staging/Prod, via SSH) — `deploy.yml`
   passes this as `-e ansible_become_pass="${{ secrets.STAGING_BECOME_PASS }}"`,
   a GitHub Actions secret, not passwordless sudo on the target. Simpler to set
   up than sudoers-per-target, but means the become password lives in a GitHub
   secret; a NOPASSWD sudoers entry on each deploy target would be the cleaner
   long-term alternative if you revisit this.

## 3. Secrets & variables (Settings → Secrets and variables → Actions)

**Secrets** (sensitive):
- `STAGING_BECOME_PASS` — **required for `deploy.yml`**; the Ansible `become`
  (sudo) password used when provisioning the deploy target over SSH. Without
  it, `deploy.yml`'s Ansible step fails.
- `DISCORD_WEBHOOK_URL` — notifications (Stage 4)
- `NVD_API_KEY` — faster Dependency-Check feed updates (optional)
- `ADMIN_API_TOKEN`, `LOWPRIV_API_TOKEN`, `CUSTOMER_COOKIE`, `REMEMBER_COOKIE`,
  `EXPIRED_COOKIE`, `RACE_COUPON_CODE` — activate the app-layer Stage 3 tests

**Variables** (non-sensitive, have defaults):
- `APP_REPO` (default `HaidenVeno/Paymenter`), `APP_REF` (default
  `fix/upgrade-configoptions-injection`) — which fork/branch to build & scan
- `BASE_URL` (default `https://paymenter.homelab.local`)
- `LOWPRIV_ROLE_ID`, `UPGRADE_SERVICE_ID`, `CHECKOUT_PRODUCT_ID` — test seed IDs

> The app source is a **separate repo**, cloned at build/scan time. If your fork
> is private, add a `repo`-scoped PAT and pass it to the `actions/checkout` steps
> that fetch `APP_REPO`.

## 4. Smoke test

Push the trivial workflow and confirm a run appears under **Actions**:

```yaml
# already covered by ci.yml; or a throwaway:
jobs:
  hello:
    runs-on: self-hosted
    steps:
      - run: echo "runner is alive on homelab"
```

## 5. DNS

Point `paymenter.homelab.local` at the reverse proxy (hosts file or local DNS)
so `BASE_URL` resolves on the runner and your test clients.
