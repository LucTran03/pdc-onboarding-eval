"""Kiểm lớp HTTP bằng TestClient (cần httpx — chỉ dev, không nằm trong requirements.txt). Không DB, không mạng."""
import os
import unittest
from unittest import mock

try:
    from fastapi.testclient import TestClient
    from obeval import app as appmod
except ImportError:  # thiếu httpx / fastapi ở máy dev
    TestClient = None

TOKEN = "thu-nghiem"
GOOD = {"X-Obeval-Token": TOKEN}
FILE = {"id": "x", "name": "y", "webViewLink": "z"}


@unittest.skipIf(TestClient is None, "thiếu fastapi/httpx")
class AppTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"OBEVAL_API_TOKEN": TOKEN})
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(appmod.app)

    def test_healthz(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok", "service": "obeval"})

    def test_recordings_without_or_wrong_token_is_401(self):
        with mock.patch.object(appmod, "_deps") as deps:
            self.assertEqual(self.client.post("/v1/recordings", json=FILE).status_code, 401)
            self.assertEqual(self.client.post("/v1/recordings", json=FILE, headers={"X-Obeval-Token": "sai"}).status_code, 401)
        deps.assert_not_called()

    def test_advance_without_token_is_401(self):
        with mock.patch.object(appmod, "_deps") as deps:
            r = self.client.post("/v1/tasks/advance", json={"booking_id": "b", "run_id": 1})
        self.assertEqual(r.status_code, 401)
        deps.assert_not_called()

    def test_unauthenticated_bad_body_is_401_not_422(self):
        # Xác thực chạy trước kiểm body: không lộ schema cho người chưa có token.
        with mock.patch.object(appmod, "_deps") as deps:
            self.assertEqual(self.client.post("/v1/recordings", json={"bad": 1}).status_code, 401)
            self.assertEqual(self.client.post("/v1/tasks/advance", json={"run_id": "abc"}).status_code, 401)
        deps.assert_not_called()

    def test_deps_wiring_uses_config_publish(self):
        appmod._deps.cache_clear()
        self.addCleanup(appmod._deps.cache_clear)
        with mock.patch("obeval.store.Store") as store_cls:
            deps = appmod._deps()
        self.assertIs(deps.publish, appmod.config.PUBLISH)
        self.assertIs(deps.store, store_cls.return_value)

    def test_recordings_with_token_calls_register(self):
        fake = mock.Mock()
        with mock.patch.object(appmod, "_deps", return_value=fake), \
                mock.patch.object(appmod.service, "register", return_value={"status": "ignored"}) as reg:
            r = self.client.post("/v1/recordings", json=FILE, headers=GOOD)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ignored"})
        sent = reg.call_args.args[0]
        self.assertEqual((sent["id"], sent["name"], sent["webViewLink"]), ("x", "y", "z"))
        self.assertIs(reg.call_args.args[1], fake)

    def test_advance_passes_args_through(self):
        fake = mock.Mock()
        with mock.patch.object(appmod, "_deps", return_value=fake), \
                mock.patch.object(appmod.service, "advance", return_value={"status": "waiting"}) as adv:
            r = self.client.post("/v1/tasks/advance", json={"booking_id": "b1", "run_id": 7, "attempt": 3}, headers=GOOD)
        self.assertEqual(r.status_code, 200)
        adv.assert_called_once_with("b1", 7, 3, fake)

    def test_run_id_string_is_coerced_to_int(self):
        # pydantic v2 (chế độ lax) đổi "7" thành 7; chuỗi không phải số thì bị từ chối 422.
        self.assertEqual(appmod.AdvanceIn(booking_id="b", run_id="7").run_id, 7)
        self.assertIsInstance(appmod.AdvanceIn(booking_id="b", run_id="7").run_id, int)
        r = self.client.post("/v1/tasks/advance", json={"booking_id": "b", "run_id": "abc"}, headers=GOOD)
        self.assertEqual(r.status_code, 422)

    def test_token_unset_rejects_everything(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.client.post("/v1/recordings", json=FILE, headers=GOOD).status_code, 401)


if __name__ == "__main__":
    unittest.main()
