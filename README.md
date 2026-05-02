# argocd-github-sha-plugin

ArgoCD ApplicationSet plugin that resolves the HEAD commit SHA of a GitHub repository branch. Credentials are passed per-request by referencing K8s secrets in the `argocd` namespace, matching ArgoCD's native `appSecretName`/`tokenRef` pattern.

## Endpoints

- `GET /healthz` — liveness probe
- `POST /api/v1/getparams.execute` — ApplicationSet plugin generator endpoint

POST requests require `Authorization: Bearer <token>` matching the file at `ARGO_TOKEN_PATH` (when configured).

## Input parameters

| Param | Required | Default | Description |
|---|---|---|---|
| `owner` | yes | — | GitHub repo owner |
| `repo` | yes | — | GitHub repo name |
| `branch` | no | `main` | Branch name |
| `appSecretName` | no | — | K8s secret with `githubAppID`, `githubAppInstallationID`, `githubAppPrivateKey` (GitHub App auth) |
| `tokenSecretName` | no | — | K8s secret containing a GitHub PAT |
| `tokenSecretKey` | no | `token` | Key within `tokenSecretName` |

Auth priority: `appSecretName` > `tokenSecretName` > anonymous.

## Output parameters

```json
{
  "output": {
    "parameters": [{
      "sha": "<full sha>",
      "short_sha": "<8 char>",
      "short_sha_7": "<7 char>",
      "branch": "...",
      "owner": "...",
      "repository": "..."
    }]
  }
}
```

## Environment variables

| Var | Default | Description |
|---|---|---|
| `PORT` | `4355` | Server port |
| `ARGO_TOKEN_PATH` | `/var/run/argo/token` | ArgoCD plugin token file |
| `WATCH_NAMESPACE` | `argocd` | Namespace to read secrets from |

## ApplicationSet example

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: my-app
  namespace: argocd
spec:
  generators:
    - plugin:
        configMapRef:
          name: github-sha-plugin
        input:
          parameters:
            owner: my-org
            repo: my-repo
            branch: main
            tokenSecretName: github-pat
  template:
    metadata:
      name: 'my-app-{{ .short_sha }}'
    spec:
      source:
        repoURL: https://github.com/my-org/my-repo
        targetRevision: '{{ .sha }}'
        path: manifests
      destination:
        server: https://kubernetes.default.svc
        namespace: default
      project: default
```

The plugin's ConfigMap and required RBAC (read access to Secrets in `WATCH_NAMESPACE`) must be installed separately.

## Development

```sh
uv sync
uv run pytest
uv run python main.py
```

## License

MIT — see [LICENSE](LICENSE).
