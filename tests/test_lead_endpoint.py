import argparse
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://parkskazka.ru"


class MockBitrixHandler(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *_):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.__class__.calls.append((self.path, body))
        if self.path.startswith("/error/"):
            payload = {"error": "MOCK_ERROR"}
        else:
            payload = {"result": 12345}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LeadEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.php = os.environ["PHP_BIN"]
        cls.mock = ThreadingHTTPServer(("127.0.0.1", 0), MockBitrixHandler)
        cls.mock_port = cls.mock.server_address[1]
        cls.mock_thread = threading.Thread(target=cls.mock.serve_forever, daemon=True)
        cls.mock_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.shutdown()
        cls.mock.server_close()

    def setUp(self):
        MockBitrixHandler.calls.clear()
        self.processes = []
        self.tempdirs = []

    def tearDown(self):
        for process in self.processes:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        for directory in self.tempdirs:
            directory.cleanup()

    def start_php(self, scenario="success", configured=True):
        directory = tempfile.TemporaryDirectory()
        self.tempdirs.append(directory)
        port = free_port()
        env = os.environ.copy()
        env.update(
            {
                "BITRIX_MOCK_MODE": "1" if configured else "0",
                "BITRIX_MOCK_URL": f"http://127.0.0.1:{self.mock_port}/{scenario}",
                "BITRIX_WEBHOOK_URL": "",
                "LEAD_STORAGE_DIR": directory.name,
                "LEAD_LOG_PATH": str(Path(directory.name) / "events.log"),
            }
        )
        process = subprocess.Popen(
            [self.php, "-S", f"127.0.0.1:{port}", "-t", str(ROOT), str(ROOT / "tests/router.php")],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.processes.append(process)
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.2)
                break
            except urllib.error.HTTPError:
                break
            except Exception:
                time.sleep(0.05)
        return port

    @staticmethod
    def payload(**changes):
        data = {
            "request_id": str(uuid.uuid4()),
            "elapsed_ms": 1500,
            "website": "",
            "name": "Тестовый клиент",
            "phone": "8 (999) 000-11-22",
            "date": "2026-12-20",
            "children": "15",
            "age": "7-8 лет",
            "comment": "Локальный mock",
            "consent": True,
            "page_url": "https://parkskazka.ru/snow-mail/?utm_source=yandex",
            "referrer": "https://yandex.ru/",
            "utm_source": "yandex",
            "utm_medium": "cpc",
            "utm_campaign": "snow-mail",
            "utm_content": "hero",
            "utm_term": "kids",
        }
        data.update(changes)
        return data

    @staticmethod
    def request(port, method="POST", payload=None, origin=ORIGIN):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Origin": origin}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/lead",
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                raw = response.read()
                body = json.loads(raw) if raw else {}
                return response.status, body, dict(response.headers)
        except urllib.error.HTTPError as error:
            raw = error.read()
            body = json.loads(raw) if raw else {}
            return error.code, body, dict(error.headers)

    def test_success_maps_utm_and_form_fields(self):
        port = self.start_php()
        status, body, headers = self.request(port, payload=self.payload())
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True, "leadId": 12345})
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), ORIGIN)
        self.assertEqual(len(MockBitrixHandler.calls), 1)
        path, bitrix_body = MockBitrixHandler.calls[0]
        self.assertTrue(path.endswith("/crm.lead.add.json"), path)
        fields = bitrix_body["fields"]
        self.assertEqual(fields["PHONE"][0]["VALUE"], "+79990001122")
        self.assertEqual(fields["UTM_SOURCE"], "yandex")
        self.assertEqual(fields["UTM_MEDIUM"], "cpc")
        self.assertEqual(fields["UTM_CAMPAIGN"], "snow-mail")
        self.assertEqual(fields["UTM_CONTENT"], "hero")
        self.assertEqual(fields["UTM_TERM"], "kids")
        self.assertIn("Желаемая дата: 2026-12-20", fields["COMMENTS"])
        self.assertIn("Количество детей: 15", fields["COMMENTS"])

    def test_preflight_and_wrong_origin(self):
        port = self.start_php()
        status, _, headers = self.request(port, method="OPTIONS")
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), ORIGIN)
        status, _, headers = self.request(port, method="OPTIONS", origin="https://nessbleesn.github.io")
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "https://nessbleesn.github.io")
        status, body, _ = self.request(port, payload=self.payload(), origin="https://example.com")
        self.assertEqual(status, 403)
        self.assertFalse(body["ok"])
        self.assertEqual(len(MockBitrixHandler.calls), 0)

    def test_duplicate_request_is_rejected(self):
        port = self.start_php()
        payload = self.payload()
        self.assertEqual(self.request(port, payload=payload)[0], 200)
        self.assertEqual(self.request(port, payload=payload)[0], 409)
        self.assertEqual(len(MockBitrixHandler.calls), 1)

    def test_invalid_date_and_missing_consent_are_rejected(self):
        port = self.start_php()
        self.assertEqual(self.request(port, payload=self.payload(date="2027-01-01"))[0], 422)
        self.assertEqual(self.request(port, payload=self.payload(consent=False))[0], 422)
        self.assertEqual(len(MockBitrixHandler.calls), 0)

    def test_honeypot_does_not_create_lead(self):
        port = self.start_php()
        status, body, _ = self.request(port, payload=self.payload(website="spam"))
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(len(MockBitrixHandler.calls), 0)

    def test_missing_configuration_and_bitrix_error_are_sanitized(self):
        port = self.start_php(configured=False)
        status, body, _ = self.request(port, payload=self.payload())
        self.assertEqual(status, 503)
        self.assertEqual(set(body), {"ok", "error"})
        self.assertNotIn("webhook", json.dumps(body).lower())

        port = self.start_php(scenario="error")
        status, body, _ = self.request(port, payload=self.payload())
        self.assertEqual(status, 502)
        self.assertFalse(body["ok"])
        self.assertNotIn("MOCK_ERROR", json.dumps(body))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--php", required=True)
    arguments, remaining = parser.parse_known_args()
    os.environ["PHP_BIN"] = arguments.php
    unittest.main(argv=[__file__, *remaining], verbosity=2)

