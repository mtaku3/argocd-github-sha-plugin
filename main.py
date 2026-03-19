#!/usr/bin/env python3
"""ArgoCD ApplicationSet Plugin: GitHub HEAD SHA Resolver.

A generic plugin that resolves the HEAD commit SHA of any GitHub repository
branch. Credentials are passed per-request by referencing K8s secrets in
the argocd namespace — matching ArgoCD's native appSecretName/tokenRef pattern.

Input parameters (from ApplicationSet):
  owner              - GitHub repo owner (required)
  repo               - GitHub repo name (required)
  branch             - Branch name (default: main)
  appSecretName      - K8s secret with githubAppID, githubAppInstallationID,
                       githubAppPrivateKey (GitHub App auth)
  tokenSecretName    - K8s secret containing a GitHub PAT
  tokenSecretKey     - Key within tokenSecretName (default: token)

Environment variables:
  ARGO_TOKEN_PATH    - Path to ArgoCD plugin token file (default: /var/run/argo/token)
  PORT               - Server port (default: 4355)
  WATCH_NAMESPACE    - Namespace to read secrets from (default: argocd)
"""

import base64
import json
import logging
import os
import ssl
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

try:
    import jwt
except ImportError:
    jwt = None

logger = logging.getLogger(__name__)

WATCH_NAMESPACE = os.environ.get("WATCH_NAMESPACE", "argocd")

_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
_SA_CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"


def _read_file(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


PLUGIN_TOKEN = _read_file(
    os.environ.get("ARGO_TOKEN_PATH", "/var/run/argo/token")
)


def read_k8s_secret(name, namespace=None):
    """Read a K8s secret using the in-cluster service account."""
    namespace = namespace or WATCH_NAMESPACE
    sa_token = _read_file(_SA_TOKEN_PATH)
    if not sa_token:
        raise RuntimeError("No service account token — not running in-cluster?")

    ctx = ssl.create_default_context(cafile=_SA_CA_PATH)
    url = f"https://kubernetes.default.svc/api/v1/namespaces/{namespace}/secrets/{name}"
    req = Request(url, headers={"Authorization": f"Bearer {sa_token}"})

    with urlopen(req, context=ctx) as resp:
        data = json.loads(resp.read())

    return {
        k: base64.b64decode(v).decode()
        for k, v in data.get("data", {}).items()
    }


def generate_app_token(app_id, installation_id, private_key):
    """Generate a GitHub App installation access token."""
    if not jwt:
        raise RuntimeError("PyJWT required for GitHub App auth: pip install PyJWT[crypto]")

    now = int(time.time())
    encoded_jwt = jwt.encode(
        {"iat": now - 60, "exp": now + 600, "iss": app_id},
        private_key,
        algorithm="RS256",
    )

    req = Request(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        method="POST",
        data=b"",
        headers={
            "Authorization": f"Bearer {encoded_jwt}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urlopen(req) as resp:
        return json.loads(resp.read())["token"]


def resolve_credentials(params):
    """Resolve GitHub credentials from input parameters.

    Reads the referenced K8s secret and returns a GitHub token.
    Priority: appSecretName > tokenSecretName > None (anonymous).
    """
    app_secret = params.get("appSecretName", "")
    if app_secret:
        secret = read_k8s_secret(app_secret)
        return generate_app_token(
            secret["githubAppID"],
            secret["githubAppInstallationID"],
            secret["githubAppPrivateKey"],
        )

    token_secret = params.get("tokenSecretName", "")
    if token_secret:
        key = params.get("tokenSecretKey", "token")
        secret = read_k8s_secret(token_secret)
        return secret[key]

    return None


def get_head_sha(owner, repo, branch, token=None):
    """Get the HEAD commit SHA of a branch via GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}"
    headers = {"Accept": "application/vnd.github.sha"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return resp.read().decode("utf-8").strip()


class PluginHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self._respond(200, {"status": "ok"})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if PLUGIN_TOKEN:
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {PLUGIN_TOKEN}":
                self._respond(403, {"error": "forbidden"})
                return

        if self.path != "/api/v1/getparams.execute":
            self._respond(404, {"error": "not found"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length))

        params = body.get("input", {}).get("parameters", {})
        owner = params.get("owner", "")
        repo = params.get("repo", "")
        branch = params.get("branch", "main")

        if not owner or not repo:
            self._respond(400, {"error": "owner and repo are required"})
            return

        try:
            token = resolve_credentials(params)
            sha = get_head_sha(owner, repo, branch, token)
            self._respond(200, {
                "output": {
                    "parameters": [{
                        "sha": sha,
                        "short_sha": sha[:8],
                        "short_sha_7": sha[:7],
                        "branch": branch,
                        "owner": owner,
                        "repository": repo,
                    }]
                }
            })
        except HTTPError as e:
            logger.error("GitHub API error: %s %s", e.code, e.reason)
            self._respond(502, {"error": f"GitHub API: {e.code} {e.reason}"})
        except Exception as e:
            logger.exception("Unexpected error")
            self._respond(500, {"error": str(e)})

    def _respond(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, fmt, *args):
        logger.info(fmt, *args)


def main():
    port = int(os.environ.get("PORT", "4355"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not PLUGIN_TOKEN:
        logger.warning("No plugin token configured — running without auth")
    logger.info("Starting on port %d", port)
    ThreadingHTTPServer(("", port), PluginHandler).serve_forever()


if __name__ == "__main__":
    main()
