"""Browser-to-real-API tests with fake GitHub storage; no external writes."""
import argparse
import copy
import functools
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "annotation"))
from api.annotation import AnnotationService, Settings
from serve_annotation import PreviewHandler
from test_submission_api import FakeGitHub, submission


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    study = json.loads((ROOT / "annotation" / "study.json").read_text())
    data = {
        "dataset_id": "online-test", "schema_version": 1, "study": study,
        "groups": [
            {"id": "group-01", "name": "Group 01", "image_ids": ["wide", "tall"], "filenames": {"wide": "image_0001.jpg", "tall": "image_0002.jpg"}},
            {"id": "group-02", "name": "Group 02", "image_ids": ["single"], "filenames": {"single": "image_0003.jpg"}},
            {"id": "group-03", "name": "Group 03", "image_ids": ["done"], "filenames": {"done": "image_0004.jpg"}},
        ],
        "images": {key: {"src": f"data/images/{key}.svg"} for key in ("wide", "tall", "single", "done")},
    }
    store = FakeGitHub()
    service = AnnotationService(data, Settings(token="test-only-not-a-real-token"), store)
    service.submit(submission(data, "group-03"))

    class TestHandler(PreviewHandler):
        drop_confirmation = False

        def _service(self):
            return service

        def log_message(self, *args):
            pass

        def _respond(self, status, body):
            if status == 200 and body.get("submitted") and TestHandler.drop_confirmation:
                TestHandler.drop_confirmation = False
                return super()._respond(503, {"error": "Confirmation was interrupted; retry submission.", "code": "network"})
            return super()._respond(status, body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path.endswith("/data/dataset.json"):
                return self._respond(200, data)
            if path.endswith(".svg"):
                width, height = (600, 2400) if path.endswith("tall.svg") else (3000, 500)
                svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><rect width="100%" height="100%" fill="#9bcbd4"/><text x="15" y="30" font-size="18">TEST IMAGE</text></svg>'.encode()
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.end_headers()
                self.wfile.write(svg)
                return
            return super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(TestHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/annotation/"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True, args=["--renderer-process-limit=1", "--disable-gpu"])
            context = browser.new_context(accept_downloads=True, viewport={"width": 1366, "height": 768})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            expect(page.locator("#start-form")).to_be_visible()
            expect(page.locator('#group option[value="group-03"]')).to_be_disabled()
            expect(page.locator("#group-availability s")).to_have_text("Group 03")
            page.locator("#annotator").fill("Student One")
            page.locator("#read-guidelines").check()
            page.locator("#start-form button").click()
            expect(page.locator('#annotation-form input').first).to_be_enabled()
            page.locator("#submit-annotations").click()
            expect(page.locator("#form-error")).to_contain_text("every image")
            self_count = store.puts
            page.locator('[value="physical_obstruction"]').check()
            page.locator('[value="lens_contamination"]').check()
            page.locator("#next").click()
            expect(page.locator("#image-heading")).to_have_text("Image 2 of 2")
            page.locator('[value="none"]').check()
            for width, height in [(1366, 768), (1280, 600), (1024, 700)]:
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollHeight <= innerHeight"), f"Page scroll at {width}x{height}"
                assert page.locator("#photo").evaluate('(el) => {let a=el.getBoundingClientRect(),b=el.parentElement.getBoundingClientRect();return a.top>=b.top-1&&a.bottom<=b.bottom+1&&getComputedStyle(el).objectFit==="contain";}')
            page.set_viewport_size({"width": 1366, "height": 768})
            store.fail = True
            page.locator("#submit-annotations").click()
            expect(page.locator("#export-status")).to_contain_text("could not be confirmed")
            self_count_after_failure = store.puts
            assert self_count_after_failure == self_count
            expect(page.locator("#submit-annotations")).to_be_enabled()
            # A complete backup remains available even when the online save fails.
            with page.expect_download() as download:
                page.locator("#export-json").click()
            backup_path = args.artifacts / "online-backup.json"
            download.value.save_as(backup_path)
            backup = json.loads(backup_path.read_text())
            assert backup["annotations"]["tall"]["filename"] == "image_0002.jpg"
            assert len(backup["annotations"]) == 2
            store.fail = False
            page.locator("#submit-annotations").click()
            expect(page.locator("#export-status")).to_contain_text("submitted successfully")
            expect(page.locator("#submit-annotations")).to_be_disabled()
            expect(page.locator('#annotation-form input').first).to_be_disabled()
            assert store.puts == self_count + 1
            page.screenshot(path=str(args.artifacts / "submission-success.png"), full_page=True)
            # Another browser immediately sees the shared completion, not local storage.
            other = browser.new_context()
            second = other.new_page()
            second.goto(url)
            expect(second.locator('#group option[value="group-01"]')).to_be_disabled()
            expect(second.locator('#group-availability s')).to_have_count(2)
            second.locator("#annotator").fill("Student Two")
            second.locator("#group").select_option("group-02")
            second.locator("#read-guidelines").check()
            second.locator("#start-form button").click()
            second.locator('[value="none"]').check()
            TestHandler.drop_confirmation = True
            second.locator("#submit-annotations").click()
            expect(second.locator("#export-status")).to_contain_text("Confirmation was interrupted")
            after_first_put = store.puts
            second.locator("#submit-annotations").click()
            expect(second.locator("#export-status")).to_contain_text("submitted successfully")
            assert store.puts == after_first_put, "A retry created a duplicate commit"
            second.locator("#change-group").click()
            expect(second.locator("#loading")).to_contain_text("All groups have been completed")
            expect(second.locator("#start-form")).not_to_be_visible()
            expect(second.locator("#group-availability s")).to_have_count(3)
            assert not errors, errors
            other.close()
            browser.close()
        print("PASS: real HTTP API, partial-submit rejection, full submission, failed-save backup/retry, shared crossed-out groups across browsers, lost-confirmation idempotency, one-image group, and viewport fit. No live GitHub writes.")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
