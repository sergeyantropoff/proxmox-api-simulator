# Prompt: fix API error bodies + Web UI session on 401 (other simulators)

Copy everything below the line into a chat opened on **ovirt_api_simulator**,
**vmware_api_simulator**, or **openstack_api_simulator**. Adapt product names
(API path prefixes, cookie/CSRF names, Helm chart paths) to that repo.

---

## Task

Fix the same class of production issues already fixed in
`proxmox_api_simulator` (reference implementation). Do **not** claim the
simulator is “incomplete” or “not supported”; keep durable, realistic API
behavior.

### Symptoms seen behind Ingress

1. Client calls a path with a **wrong / missing resource id** (e.g. bad node /
   host / datacenter name). Instead of the simulator’s JSON/XML error, the
   browser or curl receives a **branded HTML 404** (“page not found”) from the
   cluster Ingress / custom error pages.
2. Client sends a mutation (**POST/PUT/DELETE**) that the Ingress rejects or
   rewrites → **nginx HTML 405** instead of the simulator’s auth/validation
   error.
3. In the **Web UI**, after the API returns **401** (expired session), the
   response panel says unauthorized but the **header still shows the signed-in
   user** (does not switch to Guest / signed-out).

Root cause for (1)/(2) is usually **ingress-nginx**
`custom-http-errors` / `proxy-intercept-errors` replacing upstream bodies.
Root cause for (3) is UI code that renders 401 text but does not clear
ticket/token/cookie/localStorage and call the same path as logout.

### What to implement in THIS repo

#### 1. Clearer “resource not found” API errors

- Find the shared helper that validates that a node/host/cluster/datacenter
  exists (equivalent of Proxmox `require_node`).
- On miss, return the **native API error shape** for this product with a
  message that includes the bad id, e.g. Proxmox style:
  `No such node ('pve01')` plus a field-level `errors` map when the product
  uses one.
- Update unit tests that matched the old message string.
- Ensure the app always returns `Content-Type` appropriate for the API
  (JSON/XML) and never an HTML error page from the app itself.

#### 2. Web UI: treat HTTP 401 as session expiry

- When any in-app API helper gets **401** and a session is currently stored:
  - clear ticket/token/csrf/username (whatever this UI uses);
  - clear auth cookies;
  - clear persisted auth in localStorage/sessionStorage;
  - update the header auth pill / badge to the signed-out / Guest state;
  - show a short toast like “Session expired — sign in again”;
  - still show the 401 explanation in the response panel.
- Refactor logout to share one `clearSession(...)` helper so logout and
  expiry stay in sync. Do not leave stale “signed in as …” UI after 401.

#### 3. Helm / Ingress example + docs

- In the chart’s ingress example values (and kubernetes troubleshooting docs):
  - `nginx.ingress.kubernetes.io/proxy-intercept-errors: "false"`
  - `nginx.ingress.kubernetes.io/custom-http-errors: "502,503"`
    (do **not** list 404/405 so API bodies are preserved)
- Document: if clients still see branded HTML 404/405, the cluster controller
  is rewriting responses — fix Ingress annotations, not the simulator handlers.
- Document a correct authenticated mutation curl for this product (cookie /
  token + CSRF if required + the body encoding this API expects — often
  form-urlencoded, not bare JSON).

### Out of scope

- Do not add “not implemented in the simulator” user-facing messages.
- Do not change unrelated product semantics.
- Do not force-push or commit unless the user asks.

### Done when

- Missing resource → product-shaped API error with the id in the message
  (verified by unit test and/or curl against the app, not only via Ingress).
- UI 401 → Guest / signed-out header + cleared storage/cookies.
- Ingress example + troubleshooting docs warn about HTML error-page rewrite
  and show the correct curl pattern.
- Lint/tests for touched areas pass.

### Reference (proxmox_api_simulator)

- `app/handlers/common.py` — `require_node` / `node_metadata` message
- `app/web/index.html` — `clearSession` / `expireSession` / `showResponse` 401
- `helm/proxmox-api-simulator/values-ingress-example.yaml` — annotations
- `docs/troubleshooting.md` — Ingress HTML 404/405 + curl notes
