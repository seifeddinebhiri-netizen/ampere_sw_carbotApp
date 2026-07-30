# MyCarBot — Scaling Plan (Handoff)

**Status:** Design / not-yet-implemented — intended for an engineer other than the original author.
**Scope of "scale":** target on the order of 10 million connected vehicles + their app users.
**Author's note:** The full stack currently works locally (app → FastAPI backend → mTLS-bridged Mosquitto brokers → mocked car, with realtime push back). Nothing below has been built. Integration with the colleague's SOME/IP↔MQTT bridge is a **separate, currently-blocked** track and is out of scope here.

---

## 0. Read this first — the constraints that drive every decision

Three properties of the system decide almost everything downstream:

1. **Connection count, not throughput, is the hard problem.** Because a 5G car sits behind carrier-grade NAT, it can only dial *out* and must hold a persistent outbound MQTT/TLS connection open. 10M cars = 10M long-lived TLS connections that mostly sit idle. The same is true app-side if the phone holds a WebSocket. This is what breaks first — long before message volume does.
2. **MQTT brokers are stateful.** Subscriptions and sessions live *inside* a single broker. Two independent brokers do not know about each other's subscribers. Any "just add replicas" plan has to answer: *how does a message reach a subscriber on a different node?*
3. **The backend is stateful in one specific, easy-to-miss place.** The request/response correlation uses an **in-memory `request_id → asyncio.Future` table**. That assumes exactly one backend process. It must be fixed before the backend can be replicated (see Workstream 3).

Everything else is detail hanging off these three.

---

## Workstream 0 — Dynamic ACL (low-risk, do now)

**Change:** replace per-VIN static ACL entries with a single pattern rule.

Before:
```
user car_TESTVIN123
topic readwrite vehicle/TESTVIN123/#
```

After:
```
# Each authenticated car may read/write ONLY its own VIN subtree.
pattern readwrite vehicle/%u/#

# Backend keeps fleet-wide access (the documented "skeleton key").
user backend-service
topic readwrite vehicle/#
```

**Why it matters at scale:** the static form requires regenerating and reloading the ACL file every time a vehicle is provisioned. The pattern form is O(1) — new cars need no ACL change at all.

**Two things the implementer must not get wrong:**
- `%u` expands to the MQTT username, which — with `use_identity_as_username true` — is the **client-cert CN**. For `vehicle/%u/#` to match the `vehicle/<VIN>/#` topic scheme, **the CN must be the bare VIN** (`CN=TESTVIN123`), *not* `car_TESTVIN123`. If certs carry a prefix, this rule silently grants access to the wrong subtree and matches nothing real. Fix the CN, don't patch the pattern.
- Use `%u` (identity, from the certificate — unforgeable) rather than `%c` (client-id, which a client usually chooses for itself). `%c` is only trustworthy if client-id is separately forced to equal the CN.
- Confirm `allow_anonymous false` and that there is no default/global topic grant, so only these two rules are in effect.

**Limitation to accept:** a single pattern can't distinguish "car role" from "backend role," so both directions are `readwrite` within the subtree. Per-direction least privilege would require role separation the pattern alone can't express. Fine for now.

---

## Workstream 1 — Broker tier: horizontal scale done correctly

**The trap:** open-source Mosquitto does **not** cluster. Running N Mosquitto replicas behind a load balancer produces a *silent correctness bug*: a car subscribed on broker-2 never receives a command published by a backend on broker-1, because subscription state is per-broker. This looks like intermittent "commands sometimes don't arrive" and is miserable to debug.

**Two valid ways out:**

**Option A (recommended): a natively-clustering broker.**
Replace/augment Mosquitto with EMQX, VerneMQ, HiveMQ, or NanoMQ. These share session/routing state across nodes, so a publish on any node reaches a subscriber on any other node. This removes the need to hand-pin "server X ↔ broker Y." Servers connect to *any* node via a load balancer; the cluster routes internally.
- *Verify, don't trust these numbers:* these brokers are marketed as handling millions of connections per cluster, but the real ceiling depends on message rate, payload size, TLS overhead, and node sizing. Run a connection-count load test against a representative payload before committing to a node count.

**Option B: shard by VIN (this is what "wire each server to a certain broker" really is).**
Deterministically map `hash(VIN) → shard`, and make the car, its backend handler, and its broker all land on the same shard. Legitimate, but harder than it sounds:
- The car bridges *outward* through NAT, so the *bridge target* must resolve to the correct shard — routing by VIN at connection time needs MQTT-aware (L7) edge routing; a plain L4 load balancer can't see the VIN.
- Response correlation must return to the originating backend instance (see Workstream 3).
- Rebalancing shards (adding capacity) forces mass reconnects.
Prefer Option A unless there's a concrete reason the clustering broker can't be used (licensing, Ampere platform constraints).

**Do NOT** build a full bridge-mesh between Mosquitto nodes (N² bridges, loop risk, operational nightmare). It "works" for 3 nodes and collapses at 30.

**Orchestration (Kubernetes):**
- Run the broker as a **StatefulSet**, not a Deployment — brokers need stable network identity and persistent volumes.
- **HPA** for scale-*up* is straightforward. Scale-*down* is dangerous: draining a node reconnects every car on it simultaneously (thundering herd). Use conservative scale-down policies, connection draining, and lean on the clients' existing exponential-backoff-with-jitter (already implemented app-side — keep it, it's load-bearing here).
- mTLS in-cluster: plan cert distribution/rotation as its own task (Workstream 4).

---

## Workstream 2 — Edge in front of the brokers (and where CDN actually belongs)

**Correction up front:** a **CDN is the wrong tool for the broker path.** CDNs cache static HTTP at the edge. MQTT is a persistent, bidirectional, stateful TCP connection carrying unique real-time telemetry — nothing is cacheable, and CDNs don't proxy long-lived raw MQTT. A CDN in front of a broker does nothing.

**What actually goes in front of each broker / broker cluster:**
- An **L4 connection load balancer** (NLB / HAProxy / Envoy in TCP mode) to distribute millions of connections and terminate or pass through TLS.
- Optionally an **MQTT-aware gateway** for connection rate-limiting, backpressure, and auth offload. (This is likely what the original plan called a "payload manager" — that part is sound; just don't call it a CDN and don't expect caching.)

**Where the CDN *is* useful:** in front of the mobile app's static assets, and in front of any cacheable REST responses the backend serves. That's a real optimization — just on a different part of the system.

---

## Workstream 3 — Backend statefulness (the blocker for replicating the server)

**The bug that scaling exposes:** the backend correlates request↔response with an in-memory `request_id → Future` "pending" table. With one backend that's fine. With N replicas behind a load balancer, a car's response is published to MQTT and delivered to *whichever* backend instance holds the matching broker subscription — which may not be the instance that issued the request and holds the Future. Result: the request times out silently even though the car executed the command. This is the *exact* "we don't know" failure the design already tries to handle — but now caused by architecture, not by a lost ack.

**Fix (pick one):**
- **Instance-addressed responses:** include a backend-instance id in the request, and have responses come back on `.../response/<instance-id>` (or a per-instance reply topic) so the reply reaches the issuing instance. Simple, no new infra.
- **Shared correlation store:** keep pending state in Redis; whichever instance receives the response looks up the request_id and signals the owner (Redis pub/sub or a wake channel). More moving parts, but decouples reply routing from instance identity.

**Also required for the backend to scale:**
- **Database:** SQLite is single-writer and file-local — it will not serve 10M users. Move to managed PostgreSQL with read replicas. JWT is already stateless (good); refresh tokens live in the DB and scale with it.
- **App-facing connections:** 10M phones each holding a WebSocket is its own connection-count problem, mirroring the car side. Needs a sticky L4 LB or a dedicated push tier. At true scale, **FCM push becomes necessary, not optional** — you cannot cheaply hold 10M idle WebSockets, so the "system notifications need FCM, scoped out" decision has to be revisited here. WebSocket then becomes the *foreground* channel, FCM the *background* one.

---

## Workstream 4 — PKI and the skeleton-key fix (security at scale)

- **Certificate lifecycle:** the current CA is a local/toy one. 10M vehicles need a real PKI: automated per-vehicle issuance, rotation, and revocation (CRL or OCSP). This is a full workstream, not a config tweak, and it gates Workstream 1's mTLS.
- **The documented skeleton-key hole gets worse at scale.** Today a single fleet-wide backend broker credential means a compromised backend can act as any car. mTLS guards that credential but doesn't remove the concentration of authority. The real fix — **command signing verified in-car**, so the car trusts the command's signature rather than the connection — matters far more at 10M vehicles than at one. Flag it as a security-critical item, currently not built.

---

## Suggested sequencing

1. **Workstream 0 (ACL pattern)** — small, safe, correct now. Ship it.
2. **Workstream 3 (backend correlation + Postgres)** — this is the true blocker; the backend cannot be replicated safely until the pending-table problem is solved. Do it *before* scaling the broker tier, or broker scaling will surface the silent-timeout bug.
3. **Workstream 1 (clustering broker on k8s)** — the main capacity lift.
4. **Workstream 2 (edge LB / MQTT gateway; CDN for app assets)** — alongside/after Workstream 1.
5. **Workstream 4 (PKI + command signing)** — parallel security track; gates any production mTLS rollout.

---

## Open questions / verify before building

- **Broker choice:** confirm Ampere's platform allows EMQX/VerneMQ/HiveMQ (licensing, approved-software list) before designing around one.
- **Real benchmarks:** measure connections-per-node with a representative payload and TLS on; don't design node counts from vendor marketing figures.
- **Colleague's bridge contract (out of scope here but affects topic design):** exact topic strings, matching VIN, and — critically — whether his bridge echoes `request_id` on request→response. If it doesn't, every backend call times out silently regardless of how well the tier scales.
- **Shard vs cluster decision** (Workstream 1) should be made explicitly and written down, not defaulted into.