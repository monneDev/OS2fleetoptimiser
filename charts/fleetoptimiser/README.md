# FleetOptimiser Helm chart

This chart deploys the FleetOptimiser application workloads:

- backend API Deployment and ClusterIP Service
- Celery worker Deployment
- optional frontend Deployment and ClusterIP Service
- one ServiceAccount per component
- optional Istio PeerAuthentication and AuthorizationPolicies
- optional Gateway API HTTPRoute for the frontend

RabbitMQ, Valkey, SQL, Keycloak, the Istio control plane and the ingress
gateway are supplied by the environment and are deliberately not bundled.

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
