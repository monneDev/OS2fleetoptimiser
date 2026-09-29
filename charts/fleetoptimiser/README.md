# FleetOptimiser Helm chart

This chart deploys the FleetOptimiser application workloads:

- backend API Deployment and ClusterIP Service
- Celery worker Deployment
- optional frontend Deployment and ClusterIP Service
- one ServiceAccount per component
- optional database initialisation Job
- optional Kubernetes Ingress or Gateway API HTTPRoute for the frontend
- optional Istio PeerAuthentication and AuthorizationPolicies
- optional NetworkPolicies, PodDisruptionBudgets and VerticalPodAutoscalers
- optional Secret, Vault Secrets Operator resources and Argo CD Application

RabbitMQ, Valkey, SQL, Keycloak, the Istio control plane, the ingress
controller or gateway, cert-manager, Vault and Argo CD are supplied by the
environment and are deliberately not bundled. Keep each environment's values
file with that environment.

## Exposing the frontend

The backend is never exposed; the frontend proxies `/api/fleet` to it. Enable
one of:

- `ingress.enabled` for a standard Ingress, e.g. ingress-nginx with a
  cert-manager issuer in `ingress.annotations` and `ingress.tls`
- `httpRoute.enabled` for a Gateway API gateway, typically together with the
  mesh (see below)

## Secrets

The pods read passwords and auth settings from Secrets named in
`runtime.*.passwordSecret` and `frontend.auth`. There are three ways to provide
them, and `secret.create` and `vault.enabled` are mutually exclusive:

- existing Secrets created outside Helm (the default)
- `secret.create` renders one Secret named `secret.name` from `secret.values`.
  The values end up in the Helm release, so use it only for throwaway
  environments.
- `vault.enabled` syncs `secret.name` from Vault KV v2 with the Vault Secrets
  Operator, authenticating as the backend ServiceAccount, and restarts the
  Deployments when it changes. The operator and the Vault Kubernetes auth role
  must exist beforehand.

With the last two, point the references at `secret.name` and its keys
(`database-password`, `rabbitmq-password`, `valkey-password`, `keycloak-id`,
`keycloak-secret`, `keycloak-issuer`, `better-auth-secret`,
`better-auth-url`).

## Database initialisation

The backend creates missing tables through SQLAlchemy when it starts.
`migration.enabled` also runs that step in a Job after install and before
every upgrade, so an upgrade's schema is in place before its pods roll out.
With the mesh enabled, the Job gets no sidecar, which would keep it from
completing.

## Placement and availability

- `nodeSelector`, `tolerations`, `affinity`, `topologySpreadConstraints` and
  `priorityClassName` apply to all components. The MSSQL driver is only in the
  amd64 image, so MSSQL environments need `kubernetes.io/arch: amd64`.
- `pdb.enabled` adds a PodDisruptionBudget per component with
  `pdb.minAvailable`. With a single replica, `minAvailable: 1` blocks node
  drains, so raise `replicaCount` first.
- `vpa.enabled` adds VerticalPodAutoscalers; `updateMode: "Off"` only
  produces recommendations.
- `networkPolicy.enabled` denies all ingress to the release's pods except from
  the ingress controller to the frontend and from the frontend to the
  backend. Callers from other namespaces that the mesh policies allow, such as
  a load test client, are blocked as well.

## Argo CD

`argocd.enabled` renders an Argo CD Application in the `argocd` namespace that
syncs this chart from `argocd.repoURL` with `argocd.valueFiles`, which are
relative to `argocd.chartPath`. Leave it disabled in the value files the
Application itself uses.

## Service mesh

`mesh.enabled` opts the pods into Istio with the `istio.io/rev` label and adds:

- a PeerAuthentication scoped to this release's pods (`STRICT` by default)
- an AuthorizationPolicy that only lets the frontend's ServiceAccount, plus
  `mesh.authorizationPolicies.backend.extraAllowedPrincipals`, call the backend
- an AuthorizationPolicy that only lets
  `mesh.authorizationPolicies.frontend.allowedPrincipals` call the frontend

The worker gets a sidecar but receives no inbound traffic, so it has no
policy. Components can be kept out with `mesh.inject.<component>: false`.

`STRICT` rejects plaintext. With it, the frontend can only be reached through a
mesh ingress gateway such as the Istio Gateway; a non-mesh ingress like Traefik
needs `mesh.peerAuthentication.mode: PERMISSIVE` and a frontend policy that
does not rely on principals. `kubectl port-forward` bypasses the sidecar and
keeps working.

Classic sidecars add an `istio-init` container with `NET_ADMIN`/`NET_RAW`.
Namespaces that enforce the `restricted` Pod Security Standard need Istio CNI
instead.

Example for a cluster with an Istio Gateway API gateway named `istio-gateway`
in `istio-system` (its generated ServiceAccount is `istio-gateway-istio`):

```yaml
mesh:
  enabled: true
  authorizationPolicies:
    frontend:
      allowedPrincipals:
        - cluster.local/ns/istio-system/sa/istio-gateway-istio
httpRoute:
  enabled: true
  parentRefs:
    - name: istio-gateway
      namespace: istio-system
      sectionName: https
  hostnames:
    - fleetoptimiser.example.dk
```

## Validate

The chart needs the addresses of the database, RabbitMQ and Valkey, so pass
them when linting or rendering:

```sh
helm lint charts/fleetoptimiser \
  --set runtime.database.host=postgresql:5432 \
  --set runtime.rabbitmq.host=rabbitmq \
  --set runtime.valkey.host=valkey
helm template fleetoptimiser charts/fleetoptimiser \
  --namespace fleetoptimiser \
  --set runtime.database.host=postgresql:5432 \
  --set runtime.rabbitmq.host=rabbitmq \
  --set runtime.valkey.host=valkey
```
