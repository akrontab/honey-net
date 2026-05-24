# Honey-Net on AWS EKS — Migration Plan

## Architecture shift

```
┌──────────────────────── AWS Account ─────────────────────────┐
│                                                              │
│  ┌─ EKS cluster (private API endpoint) ───────────────────┐  │
│  │                                                        │  │
│  │  Node group: honeypot-nodes  (tainted, isolated)       │  │
│  │   • cowrie pod   → NLB :22                             │  │
│  │   • mysql pod    → NLB :3306                           │  │
│  │   • vector sidecar per pod (or DaemonSet)              │  │
│  │                                                        │  │
│  │  Node group: platform-nodes  (no public exposure)      │  │
│  │   • loki + grafana (internal NLB only, behind VPN)     │  │
│  │   • metadata / malware-sender addons as CronJobs       │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  S3 (malware catalog) · ECR (images) · CloudWatch (audit)    │
│  Client VPN or Tailscale Subnet Router → Grafana             │
└──────────────────────────────────────────────────────────────┘
```

## Migration phases

1. **Package each honeypot as an OCI image** in ECR. Replace `docker-compose.yml` per honey-pot dir with a Helm chart or Kustomize overlay. The Vector sidecar moves into the Pod spec, no more per-VM compose.
2. **Manifest translation** — `honey-net.json` becomes the input to a generator that emits per-pot `Deployment` + `Service type=LoadBalancer` (NLB, one ELB IP per honeypot so attackers still see distinct IPs).
3. **Storage** — Cowrie's downloads dir, the shared `inbox/`, and the malware catalog all move off node-local volumes. Inbox → EFS (RWX needed for metadata + sender to share). Malware catalog → S3 with object-lock for immutability. Loki storage → S3 (boltdb-shipper or TSDB schema).
4. **Provisioning rewrite** — `provision.py` / `redeploy.py` become `eksctl create cluster` + `helm upgrade --install`. Terraform stays, but now provisions VPC, EKS, node groups, NLBs, ECR, EFS, S3 instead of Linodes.
5. **Tailscale** — either run it as a sidecar in the Grafana pod (so it joins the tailnet for admin access) or replace it with AWS Client VPN. The honeypot-to-Loki path becomes in-cluster service DNS — no VPN needed for that hop anymore.
6. **Observability** — keep Loki/Grafana, but add CloudWatch for the EKS control-plane audit log (separate trust boundary from honeypot logs).

## Trade-offs vs. raw EC2 / current Linode model

| Concern | EKS | EC2 / Linode |
|---|---|---|
| **Cost floor** | ~$73/mo EKS control plane + nodes + NLBs (~$18/mo each) + NAT GW. Realistic minimum ~$200/mo. | $5/mo per Nanode. Project today: ~$10–15/mo total. |
| **Isolation** | Pods share the node kernel. A container escape from Cowrie lands on a node hosting other workloads. VMs give you a hypervisor boundary for free. | Each honeypot is on its own VM. Compromise blast radius = one $5 VM. |
| **Per-honeypot public IP** | Need one NLB per pot to preserve distinct attacker-facing IPs. Adds cost and config. | Each VM already has a public IP. |
| **Operational complexity** | RBAC, IRSA, NetworkPolicy, CNI quirks, cert rotation, cluster upgrades. | `docker compose up`. |
| **Scale-out** | Add a row to `honey-net.json`, `helm upgrade`, done. Horizontal scaling is trivial. | New VM, new SSH key, new Tailscale auth key, new setup.sh run. |
| **Ephemerality** | Pods are cattle. Wiping a compromised pot is `kubectl delete pod`. | Need to rebuild VM. |
| **Forensics** | Pod filesystem is gone the moment it restarts unless you snapshot. Need explicit volume snapshots or commit-on-exit. | Whole VM disk available. |
| **Egress control** | Fine-grained per-pod via NetworkPolicy + egress proxy. Important since honeypots shouldn't be able to attack outward. | iptables on the VM. |
| **Compliance / audit** | CloudTrail + EKS audit log out of the box. | Roll your own. |

The honest summary: **EKS is the wrong choice for a 2–3 server hobby honeynet on cost grounds alone**, but the right choice if this becomes a real research platform with dozens of pots, multi-region deployment, or a team operating it. The isolation story is also *worse* than VMs unless you add Fargate or gVisor — see hardening below.

## Container hardening in EKS (honeypot-aware)

Honeypots are intentionally exploitable, so the goal is **escape containment**, not preventing the in-container compromise.

### Pod spec

- `securityContext.runAsNonRoot: true` for everything that supports it. Cowrie can run as UID 1000; the MySQL emulator likewise. Vector runs unprivileged.
- Drop all Linux capabilities, then add back only what's truly needed. Cowrie needs none (it binds to a high port inside the container; NLB does the :22 translation).
- `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, with explicit `emptyDir` mounts for the writable paths the honeypot expects (Cowrie's `var/`, `dl/`).
- Seccomp: `RuntimeDefault` minimum. For Cowrie specifically, build a custom profile — the shell emulator doesn't need most syscalls.
- AppArmor profile per honeypot (EKS supports this on Bottlerocket / AL2023 nodes).
- Resource limits on CPU/memory + `ephemeral-storage` — attackers love to fill disks.

### Stronger isolation options (pick one for honeypot pods specifically)

- **Fargate** — each pod gets a microVM (Firecracker). Strongest isolation, but no DaemonSets, no privileged containers, limited storage classes. Best fit for the honeypot pods themselves.
- **Bottlerocket nodes + gVisor (runsc) RuntimeClass** — userspace kernel between the container and the host. ~10–30% perf hit, irrelevant for honeypots. Bottlerocket also gives you an immutable host OS.
- **Kata Containers** via the AWS Marketplace AMIs — VM-per-pod without the Fargate restrictions. Heavier ops cost.

### Network

- Dedicated node group for honeypot pods with a taint (`role=honeypot:NoSchedule`) so platform workloads can't land there.
- **Security Groups for Pods** to put each honeypot pod in its own SG with explicit egress allow-list — only Loki and any C2-sinkhole you want it to be able to reach. Default-deny everything else, so a compromised Cowrie can't pivot to AWS metadata, internal services, or scan the internet from your account.
- Block IMDSv1 cluster-wide and require hop-limit 1 for IMDSv2 so containers can't reach `169.254.169.254`. Critical — attackers will try this.
- `NetworkPolicy` denying pod-to-pod east-west by default; honeypot pods can only reach Loki on its service IP.
- Private EKS API endpoint. No public kube-apiserver.

### Identity & secrets

- IRSA per honeypot ServiceAccount, scoped to only the resources it needs (e.g. write to one S3 prefix). No node-level instance profile reachable from pods.
- Pod Identity (newer than IRSA) if you're on EKS 1.28+.
- Secrets via AWS Secrets Manager + CSI driver, not Kubernetes Secrets (which are base64, not encrypted at rest without KMS envelope).

### Image supply chain

- Distroless or minimal base images for the Vector sidecar and addons. Cowrie/MySQL emulator stay as-is (they need Python/runtime).
- ECR image scanning enhanced + Inspector findings into Security Hub.
- Sign images with cosign, enforce with a policy controller (Kyverno or OPA Gatekeeper) — `imagePullPolicy: Always` + signature verification.
- Pin image digests, not tags, in Helm values.

### Runtime & cluster

- EKS control-plane audit logs → CloudWatch → a separate account if you can swing it. Honeypot logs and audit logs should never share a trust boundary.
- GuardDuty for EKS (runtime monitoring agent). It catches a lot of the obvious post-exploitation patterns.
- Falco DaemonSet on honeypot nodes for syscall-level alerting (e.g. `execve` of a shell in the Vector container = something is very wrong).
- `kubectl` and the EKS API are not reachable from honeypot pods (NetworkPolicy + SG egress block).
- Regular node rotation — Karpenter or scheduled CycleNodes — so a persistence foothold on a compromised node has a short half-life.

### Honeypot-specific gotchas

- Don't apply `readOnlyRootFilesystem` to Cowrie's emulated FS layer — attackers expect to be able to write. Scope it to the container root, mount writable `emptyDir` where Cowrie writes.
- The malware-sender addon needs S3 write. Give it IRSA with `s3:PutObject` only, to one prefix, with object-lock so a compromised pot can't delete prior catches.
- The metadata extractor and malware-sender share an EFS inbox. EFS access points + POSIX UIDs to keep them from reading each other's writes if you ever multi-tenant.

## Recommendation

If the goal is "learn EKS while running honeynet," do it on Fargate-only with one honeypot to start, accept the ~$200/mo floor, and treat the hardening list above as the curriculum. If the goal is "scale honeynet," the answer is probably *more Linode VMs orchestrated by the existing Python tooling*, not EKS — the per-VM isolation is the feature, and the current `honey-net.json` → provision flow already does the orchestration job that EKS would replace.
