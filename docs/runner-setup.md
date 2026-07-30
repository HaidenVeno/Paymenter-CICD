# Self-Hosted Runner Setup (Stage 1)

The pipeline executes entirely on your homelab. GitHub's cloud is only the code
host, trigger, and Issues surface — see the on-premise justification in
[../README.md](../README.md).

## 1. Register the runner

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

The workflows assume these are on the runner host (installed once, not per-job):

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin python3-pip ansible nikto
sudo usermod -aG docker "$(whoami)"   # let the runner user drive Docker
# log out/in (or restart the runner service) for the group change to apply
```

Ansible plays use `become` (sudo). Give the runner user passwordless sudo, or
run the deploy with an ask-become-pass alternative:

```bash
echo "$(whoami) ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/gh-runner
```

## 3. Secrets & variables (Settings → Secrets and variables → Actions)

**Secrets** (sensitive):
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
