# Portainer (stack visualization)

A web GUI to **watch** the running Paymenter containers — status, health, live
logs, CPU/mem/network stats, and the frontend/app/db networks. Runs as a
separate management plane, not part of the app deploy.

## Run (on the Linux homelab host)

```bash
docker compose -f docker/monitoring/docker-compose.portainer.yml up -d
```

Then open **https://localhost:9443** on the homelab host (self-signed cert — the
browser warning is expected). Set the admin password within a few minutes of
first start or Portainer locks itself.

Browsing from another machine (e.g. your Windows box)? Tunnel it:

```bash
ssh -L 9443:localhost:9443 user@homelab
# then open https://localhost:9443 on your machine
```

Portainer auto-detects the local environment (via the socket-proxy) — no
endpoint setup needed. You'll see every container on the host, including the
whole `paymenter` stack.

## Why the socket-proxy?

Portainer normally needs the Docker socket, which is root-equivalent control of
the host. Instead, a **read-only `docker-socket-proxy`** sits in front of it and
only forwards GET/view API calls — `POST`, `EXEC`, `BUILD`, secrets, swarm, and
system endpoints are denied. So you can **view** everything but not start/stop/
exec/redeploy from the UI, and a Portainer compromise can't pivot to host
control. Fitting for a hardening project.

## Want management (start/stop/redeploy) too?

Edit `docker-compose.portainer.yml` and flip the socket-proxy env you need:

```yaml
POST: 1     # enables start/stop/restart/create
EXEC: 1     # enables container console/exec
```

Then `docker compose -f docker/monitoring/docker-compose.portainer.yml up -d`.
Understand the trade-off: this broadens what the proxy (and thus Portainer) can
do to the host. Keep the UI bound to localhost if you enable these.

## Exposure

The UI binds to `127.0.0.1:9443` by default. To expose on your LAN (accepting
the risk), set `PORTAINER_BIND`:

```bash
PORTAINER_BIND=192.168.0.10 docker compose -f docker/monitoring/docker-compose.portainer.yml up -d
```

Note the app stack's `DOCKER-USER` firewall (Ansible `harden.yml`) only allows
80/443 by source; if you expose 9443 on the LAN, add a matching rule there to
restrict it to your management network.
