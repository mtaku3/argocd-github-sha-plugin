import json
import os
import unittest
from http.server import HTTPServer
from threading import Thread
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

os.environ["ARGO_TOKEN_PATH"] = "/dev/null"

from main import PluginHandler, resolve_credentials

FAKE_SHA = "abc1234567890def1234567890abcdef12345678"


class TestPluginHandler(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), PluginHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _post(self, path, body):
        data = json.dumps(body).encode()
        req = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urlopen(req)
        return resp.status, json.loads(resp.read())

    def _get(self, path):
        req = Request(f"http://127.0.0.1:{self.port}{path}", method="GET")
        resp = urlopen(req)
        return resp.status, json.loads(resp.read())

    def test_healthz(self):
        status, body = self._get("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    @patch("main.resolve_credentials", return_value="fake-token")
    @patch("main.get_head_sha", return_value=FAKE_SHA)
    def test_returns_sha_parameters(self, mock_sha, mock_creds):
        status, body = self._post("/api/v1/getparams.execute", {
            "applicationSetName": "test",
            "input": {
                "parameters": {
                    "owner": "myorg",
                    "repo": "myrepo",
                    "branch": "main",
                    "appSecretName": "repo-myrepo",
                }
            }
        })
        self.assertEqual(status, 200)
        params = body["output"]["parameters"]
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0]["sha"], FAKE_SHA)
        self.assertEqual(params[0]["short_sha_7"], FAKE_SHA[:7])
        self.assertEqual(params[0]["short_sha"], FAKE_SHA[:8])
        self.assertEqual(params[0]["owner"], "myorg")
        self.assertEqual(params[0]["repository"], "myrepo")
        self.assertEqual(params[0]["branch"], "main")
        mock_sha.assert_called_once_with("myorg", "myrepo", "main", "fake-token")

    @patch("main.resolve_credentials", return_value=None)
    @patch("main.get_head_sha", return_value=FAKE_SHA)
    def test_defaults_branch_to_main(self, mock_sha, mock_creds):
        status, body = self._post("/api/v1/getparams.execute", {
            "applicationSetName": "test",
            "input": {
                "parameters": {
                    "owner": "myorg",
                    "repo": "myrepo",
                }
            }
        })
        self.assertEqual(status, 200)
        mock_sha.assert_called_once_with("myorg", "myrepo", "main", None)

    def test_missing_owner_returns_400(self):
        with self.assertRaises(HTTPError) as ctx:
            self._post("/api/v1/getparams.execute", {
                "applicationSetName": "test",
                "input": {"parameters": {"repo": "myrepo"}}
            })
        self.assertEqual(ctx.exception.code, 400)

    def test_missing_repo_returns_400(self):
        with self.assertRaises(HTTPError) as ctx:
            self._post("/api/v1/getparams.execute", {
                "applicationSetName": "test",
                "input": {"parameters": {"owner": "myorg"}}
            })
        self.assertEqual(ctx.exception.code, 400)


class TestResolveCredentials(unittest.TestCase):
    @patch("main.read_k8s_secret")
    @patch("main.generate_app_token")
    def test_app_secret_name(self, mock_gen, mock_read):
        mock_read.return_value = {
            "githubAppID": "123",
            "githubAppInstallationID": "456",
            "githubAppPrivateKey": "fake-key",
        }
        mock_gen.return_value = "app-token"
        result = resolve_credentials({"appSecretName": "repo-test"})
        self.assertEqual(result, "app-token")
        mock_read.assert_called_once_with("repo-test")
        mock_gen.assert_called_once_with("123", "456", "fake-key")

    @patch("main.read_k8s_secret")
    def test_token_secret_name(self, mock_read):
        mock_read.return_value = {"token": "my-pat"}
        result = resolve_credentials({
            "tokenSecretName": "my-secret",
            "tokenSecretKey": "token",
        })
        self.assertEqual(result, "my-pat")
        mock_read.assert_called_once_with("my-secret")

    @patch("main.read_k8s_secret")
    def test_token_secret_default_key(self, mock_read):
        mock_read.return_value = {"token": "my-pat"}
        result = resolve_credentials({"tokenSecretName": "my-secret"})
        self.assertEqual(result, "my-pat")

    def test_no_credentials_returns_none(self):
        result = resolve_credentials({})
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
