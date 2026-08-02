# Network Topology & IP Addressing

The pipeline is validated in a 5-VM VirtualBox lab that mirrors a real,
segmented deployment: a **true DMZ for production** (reverse proxy/WAF on its own
VM, app + data on a separate internal VM), a single-VM staging environment that
is **never public**, an isolated attacker/DAST box, and a CI/CD runner that
orchestrates everything over an out-of-band management network.

## Zones (VirtualBox networks)

| Zone | Trust | VBox adapter type | Subnet | Purpose |
|---|---|---|---|---|
| **Untrusted / public** `attacknet` | none | Internal Network | `10.0.10.0/24` | attacker ↔ production DMZ only |
| **Management (OOB)** `mgmtnet` | admin | Host-only | `10.0.20.0/24` | SSH/Ansible deploys + monitoring; connects the Runner to all servers |
| **Prod internal** `prodint` | internal | Internal Network | `10.0.40.0/24` | link between Prod-DMZ proxy and Prod-App (proxy → app only) |
| **Egress** | — | NAT (per VM) | auto `10.0.2.x` | outbound only: apt, docker pull, GitHub |

Host-only `mgmtnet`: the Windows host is `10.0.20.1`.

## Virtual machines

| VM | Role | OS | RAM | vCPU | Disk | Adapters → IPs | Phase |
|---|---|---|---|---|---|---|---|
| **Runner** | CI/CD self-hosted runner; builds + scans + orchestrates deploys | Ubuntu 24.04 | 6 GB | 4 | 60 GB | NAT · mgmt `10.0.20.10` | 1 |
| **Staging** | proxy + app + db as containers (soft DMZ); internal-only | Ubuntu 24.04 | 4 GB | 2 | 40 GB | NAT · mgmt `10.0.20.20` | 1 |
| **Prod-DMZ** | reverse proxy + ModSecurity WAF only | Ubuntu 24.04 | 2 GB | 2 | 30 GB | NAT · attack `10.0.10.30` · prodint `10.0.40.30` · mgmt `10.0.20.30` | 2 |
| **Prod-App** | app + db + cache (no public NIC) | Ubuntu 24.04 | 4 GB | 2 | 40 GB | NAT · prodint `10.0.40.31` · mgmt `10.0.20.31` | 2 |
| **Attacker/Ops** | external ZAP/Nikto; validates prod from outside | Kali | 4 GB | 2 | 40 GB | NAT · attack `10.0.10.10` | 3 |

Convention: **last octet = host identity** across every subnet (staging is always `.20`).

## Where the reverse proxy sits

- **Production:** its own VM (**Prod-DMZ**) in the DMZ segment — the only public-facing box. A proxy compromise lands the attacker in the DMZ, *not* on the host with the database.
- **Staging:** a container inside the single Staging VM (soft DMZ via the Docker `frontend` network). Acceptable because staging has no public NIC at all.

## Two planes of segmentation

1. **VirtualBox networks** = coarse zones between VMs (above).
2. **Docker networks inside each app VM** = fine tiers:

| Tier | Docker network | Subnet | Members |
|---|---|---|---|
| DMZ | `frontend` | `172.30.0.0/24` | nginx-edge + ModSecurity |
| App | `app` | `172.30.1.0/24` | app ↔ proxy |
| Data | `db` | `172.30.2.0/24` | mariadb + redis (no published ports) |

## Traffic policy (default-deny)

| From → To | Allowed |
|---|---|
| Attacker `10.0.10.10` → Prod-DMZ `10.0.10.30` | TCP 443 (+80 redirect) |
| Prod-DMZ `10.0.40.30` → Prod-App `10.0.40.31` | app port (8080) only |
| Runner `10.0.20.10` → Staging/Prod hosts (mgmt) | TCP 22 (deploy) |
| Runner `10.0.20.10` → Staging `10.0.20.20` | TCP 443 (internal DAST) |
| Host `10.0.20.1` → mgmt hosts | TCP 22 (admin) |
| Any VM → Internet (NAT) | 53, 80, 443 out |
| Staging ↔ Production | **DENY** (no lateral movement) |
| Attacker → mgmtnet / prodint / Prod-App | **DENY** (attacker only ever sees Prod-DMZ:443) |

Enforced by host `nftables` + the `DOCKER-USER` chain (Ansible `harden.yml`).

## Rollout phases

- **Phase 1 — Runner + Staging.** Full pipeline end-to-end against staging (internal). Shake out deploy/Ansible/DAST breakage here.
- **Phase 2 — Prod-DMZ + Prod-App.** True DMZ + approval-gated promotion (build once on staging, promote the same image to prod).
- **Phase 3 — Attacker/Ops.** External validation of production through the WAF; demonstrate segmentation blocks lateral/internal access.

## Notes / rationale
- **Staging is never public** — it has no `attacknet` NIC, so the attacker VM cannot route to it. Only the Runner (deploy + DAST) and the host reach it.
- **Attacker box is isolated** — `attacknet` only, no management leg, so offensive tooling never sits on the admin plane.
- This is stricter than Lab 5 (single-host `nginx-edge → app → db`); the true-DMZ split for prod is a deliberate improvement to document in the report.
