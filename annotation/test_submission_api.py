"""No live GitHub writes: exercise validation and create-only storage with a fake."""
import copy
import http.client
import json
import sys
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api.annotation import APIError, AnnotationService, GitHub, GitHubError, Settings, handler


def dataset():
    return {
        "dataset_id": "test-dataset", "study": {"guidelines_version": "2.0", "labels": [{"id": "physical_obstruction"}, {"id": "lens_contamination"}]},
        "groups": [{"id": "group-01", "name": "Group 01", "image_ids": ["one", "two"], "filenames": {"one": "image_001.jpg", "two": "image_002.jpg"}}, {"id": "group-04", "name": "Group 04", "image_ids": ["three"], "filenames": {"three": "image_003.jpg"}}],
    }


def submission(data=None, group_id="group-01"):
    data = data or dataset()
    group = next(g for g in data["groups"] if g["id"] == group_id)
    return {"schema_version": 1, "submission_id": str(uuid.uuid4()), "dataset_id": data["dataset_id"], "guidelines_version": data["study"]["guidelines_version"], "group_id": group_id, "annotator_id": "Student One", "annotations": {key: {"image_id": key, "filename": "untrusted.jpg", "labels": ["physical_obstruction"], "artifact_judgment": "present", "status": "annotated", "active_seconds": 5} for key in group["image_ids"]}}


class FakeGitHub:
    def __init__(self):
        self.files = {}
        self.lock = threading.Lock()
        self.fail = False
        self.branch_conflicts = 0
        self.puts = 0

    def list_files(self):
        if self.fail:
            raise GitHubError(503)
        with self.lock:
            return {Path(path).name for path in self.files}

    def read_file(self, path):
        if self.fail:
            raise GitHubError(503)
        with self.lock:
            return copy.deepcopy(self.files.get(path))

    def create_file(self, path, payload):
        with self.lock:
            if self.fail:
                raise GitHubError(503)
            if self.branch_conflicts:
                self.branch_conflicts -= 1
                raise GitHubError(409)
            if path in self.files:
                raise GitHubError(422)
            self.puts += 1
            self.files[path] = copy.deepcopy(payload)
            return {"commit": {"sha": "test-commit"}}


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.data = dataset()
        self.store = FakeGitHub()
        self.service = AnnotationService(self.data, Settings(token="test-secret"), self.store)

    def test_success_status_and_authoritative_filenames(self):
        self.assertEqual(self.service.status()["groups"]["group-01"]["state"], "available")
        receipt = self.service.submit(submission(self.data))
        self.assertTrue(receipt["submitted"])
        self.assertTrue(receipt["path"].startswith("data/annotations/raw/group-01_"))
        self.assertEqual(self.service.status()["groups"]["group-01"]["state"], "completed")
        saved = self.store.files[receipt["path"]]
        self.assertEqual(saved["annotations"]["one"]["filename"], "image_001.jpg")
        self.assertNotIn("usability", saved["annotations"]["one"])

    def test_repeat_submission_is_idempotent(self):
        payload = submission(self.data)
        self.service.submit(payload)
        payload["annotations"]["one"]["active_seconds"] = 7
        receipt = self.service.submit(payload)
        self.assertTrue(receipt["already_saved"])
        self.assertEqual(self.store.puts, 1)

    def test_different_student_and_changed_answers_cannot_overwrite(self):
        payload = submission(self.data)
        self.service.submit(payload)
        for other in [submission(self.data), copy.deepcopy(payload)]:
            other["annotations"]["one"]["labels"] = ["lens_contamination"]
            with self.assertRaises(APIError) as error:
                self.service.submit(other)
            self.assertEqual(error.exception.code, "group_completed")
        self.assertEqual(self.store.puts, 1)

    def test_simultaneous_students_accept_only_one(self):
        barrier = threading.Barrier(2)
        original = self.store.read_file
        counter = threading.local()

        def simultaneous_read(path):
            result = original(path)
            if not getattr(counter, "read", False):
                counter.read = True
                barrier.wait(timeout=5)
            return result
        self.store.read_file = simultaneous_read

        def send(payload):
            try:
                return self.service.submit(payload)["submitted"]
            except APIError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, [submission(self.data), submission(self.data)]))
        self.assertCountEqual(results, [True, "group_completed"])
        self.assertEqual(self.store.puts, 1)

    def test_group_completion_survives_adding_other_groups(self):
        self.service.submit(submission(self.data))
        changed = copy.deepcopy(self.data)
        changed["dataset_id"] = "new-global-dataset"
        changed["groups"].append({"id": "group-10", "image_ids": ["extra"]})
        service = AnnotationService(changed, self.service.settings, self.store)
        self.assertEqual(service.status()["groups"]["group-01"]["state"], "completed")
        changed["groups"][0]["image_ids"].append("different")
        self.assertEqual(service.status()["groups"]["group-01"]["state"], "available")

    def test_validation_rejects_partial_unknown_stale_and_inconsistent(self):
        changes = [
            lambda p: p["annotations"].pop("two"),
            lambda p: p.update(dataset_id="old"),
            lambda p: p.update(group_id="group-99"),
            lambda p: p.update(submission_id="bad"),
            lambda p: p["annotations"]["one"].update(labels=["unknown"]),
            lambda p: p["annotations"]["one"].update(labels=["physical_obstruction", "physical_obstruction"]),
            lambda p: p["annotations"]["one"].update(artifact_judgment="none"),
            lambda p: p["annotations"]["one"].update(status="draft"),
            lambda p: p["annotations"]["one"].update(active_seconds=float("nan")),
        ]
        for change in changes:
            payload = submission(self.data)
            change(payload)
            with self.subTest(change=change), self.assertRaises(APIError):
                self.service.submit(payload)
        self.assertEqual(self.store.puts, 0)

    def test_no_artifact_and_uncertain_are_valid_answers(self):
        payload = submission(self.data)
        payload["annotations"]["one"].update(labels=[], artifact_judgment="none")
        payload["annotations"]["two"].update(labels=[], artifact_judgment="uncertain")
        self.assertTrue(self.service.submit(payload)["submitted"])

    def test_failed_storage_does_not_mark_completed_and_retry_succeeds(self):
        self.store.fail = True
        payload = submission(self.data)
        with self.assertRaises(APIError) as error:
            self.service.submit(payload)
        self.assertEqual(error.exception.status, 503)
        self.assertFalse(self.store.files)
        self.store.fail = False
        self.store.branch_conflicts = 1
        self.assertTrue(self.service.submit(payload)["submitted"])

    def test_optional_access_code_and_missing_configuration(self):
        protected = AnnotationService(self.data, Settings(token="test", access_code="class-code"), self.store)
        self.assertTrue(protected.status()["requires_access_code"])
        with self.assertRaises(APIError) as error:
            protected.submit(submission(self.data), "wrong")
        self.assertEqual(error.exception.status, 403)
        self.assertTrue(protected.submit(submission(self.data), "class-code")["submitted"])
        with self.assertRaises(APIError) as error:
            AnnotationService(self.data, Settings()).status()
        self.assertEqual(error.exception.code, "not_configured")

    def test_github_create_never_includes_replacement_sha(self):
        github = GitHub(Settings(token="test"))
        sent = []
        github.request = lambda *args: sent.append(args) or {"commit": {"sha": "created"}}
        github.create_file("data/annotations/raw/group-01.json", {"group_id": "group-01"})
        self.assertNotIn("sha", sent[0][2])
        self.assertEqual(sent[0][0], "PUT")


class HTTPTests(unittest.TestCase):
    def test_handler_rejects_bad_origin_type_and_json_without_writes(self):
        store = FakeGitHub()
        service = AnnotationService(dataset(), Settings(token="never-expose-this-token"), store)

        class TestHandler(handler):
            def _service(self):
                return service

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host = f"127.0.0.1:{server.server_port}"

        def post(body, origin, content_type="application/json"):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            try:
                headers = {"Content-Type": content_type}
                if origin is not None:
                    headers["Origin"] = origin
                connection.request("POST", "/api/annotation", body, headers)
                response = connection.getresponse()
                raw = response.read().decode()
                self.assertNotIn("never-expose-this-token", raw)
                return response.status, json.loads(raw)
            finally:
                connection.close()
        try:
            valid = json.dumps(submission())
            self.assertEqual(post(valid, None)[0], 403)
            self.assertEqual(post(valid, "https://another.example")[0], 403)
            self.assertEqual(post(valid, "http://" + host, "text/plain")[0], 415)
            self.assertEqual(post("not-json", "http://" + host)[0], 400)
            self.assertEqual(store.puts, 0)
            status, result = post(valid, "http://" + host)
            self.assertEqual(status, 200)
            self.assertTrue(result["submitted"])
            self.assertEqual(store.puts, 1)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
