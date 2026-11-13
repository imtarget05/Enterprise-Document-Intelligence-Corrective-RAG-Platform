# Argo CD GitOps — SmartDoc

App-of-apps manifests that deploy the `helm/smartdoc` chart (PR #43,
`feat/helm-chart` — qdrant, llm-router, backend, frontend) to prod via Argo CD.

## Contents

| File | Kind | Purpose |
|---|---|---|
| `appproject.yaml` | AppProject `portfolio` | Scopes which repos/clusters/namespaces apps may use |
| `application-smartdoc.yaml` | Application | Prod: `helm/smartdoc` + `values-prod.yaml` → `smartdoc-prod` |

> **Placeholders:** every destination `server` is `https://kubernetes.default.svc`
> (the API server of the cluster Argo CD itself runs on). Replace with real
> cluster names/URLs (`argocd cluster list`) when deploying to external clusters.

## Install Argo CD

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd --create-namespace \
  --set configs.params."server\.insecure"=true
kubectl -n argocd rollout status deploy/argocd-server
```

## App-of-apps pattern

Instead of running `kubectl apply` per application, you apply **one** root
application that watches this `argocd/` directory; every `Application` manifest
it finds is then created automatically:

```bash
kubectl apply -n argocd -f - <<'EOF'
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: portfolio-root
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: portfolio
  source:
    repoURL: https://github.com/imtarget05/Enterprise-Document-Intelligence-Corrective-RAG-Platform.git
    targetRevision: main
    path: argocd
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
EOF
```

The root app syncs `argocd/appproject.yaml` and `application-smartdoc.yaml`;
each child Application in turn syncs its Helm chart. Adding a new environment =
adding a new YAML file to this directory.

## How sync works with the Helm charts

1. Argo CD polls the Git repo (`targetRevision: main`) every 3 minutes by default.
2. It runs the equivalent of `helm template helm/smartdoc -f values-prod.yaml`
   against the repo snapshot.
3. The rendered manifests are diffed against the live cluster
   (`smartdoc-prod` namespace, auto-created by `CreateNamespace=true`).
4. Out of sync → automated sync (`prune: true` removes deleted resources,
   `selfHeal: true` reverts manual cluster-side changes). Retries with
   exponential backoff on failure.

Deploying a change therefore means **merging to `main`** — no kubectl, no CI/CD
pipeline push to the cluster.

> **Secrets note:** the chart ships a `secret-template.yaml` (runtime-populated).
> Argo CD will see a difference between the rendered placeholder and live data;
> annotate with `argocd.argoproj.io/ignoreDifferences` or sync only specific
> resources if that becomes noisy. Never commit real secrets — use an
> ExternalSecret/Vault or SOPS in a follow-up.

## Rollback

```bash
# list sync history
argocd app history smartdoc-prod

# roll back to a previous deployment id
argocd app rollback smartdoc-prod 5

# IMPORTANT: because syncPolicy.automated.selfHeal is enabled, Argo CD will
# re-sync back to the Git revision. To make a rollback stick, revert the commit
# on main (git revert) — GitOps treats Git as the source of truth.
```
