"""End-to-end smoke tests with fixture images; no real student data or network services.

Requires Playwright for Python and an installed Chrome (no extra browser download).
Run from anywhere: python annotation/test_browser.py --artifacts <outside-site-folder>
"""
import argparse
import functools
import http.server
import json
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Model clean-URL hosting that serves index.html at /annotation without
        # adding a slash. Relative asset URLs must still load correctly.
        if self.path.split("?", 1)[0] == "/annotation":
            self.path = "/annotation/index.html"
        super().do_GET()

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parent
    study = json.loads((root / "study.json").read_text())
    dataset = {
        "schema_version": 1, "dataset_id": "browser-test-study", "study": study,
        "groups": [
            {"id": "group-01", "name": "Group 01", "image_ids": ["one", "two", "three"], "filenames": {"one": "image_0051.jpg", "two": "image_0099.png", "three": "image_0100.jpg"}},
            {"id": "group-02", "name": "Group 02", "image_ids": ["one"]},
            {"id": "group-03", "name": "Group 03", "image_ids": []},
        ],
        "images": {x: {"src": f"data/images/{x}.svg"} for x in ("one", "two", "three")},
    }
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(root.parent)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/annotation/"
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="650"><rect width="1000" height="650" fill="#9bcbd4"/><path d="M0 380L280 190L540 390L820 210L1000 400V650H0Z" fill="#456b56"/><path d="M360 650L490 400L530 400L710 650Z" fill="#bbc3bb"/><text x="30" y="50" font-size="24">TEST FIXTURE — not a dataset image</text></svg>'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 1050})
            errors = []
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/data/dataset.json", lambda route: route.fulfill(json=dataset))
            page.route("**/data/images/*.svg", lambda route: route.fulfill(status=404) if route.request.url.endswith("three.svg") else route.fulfill(content_type="image/svg+xml", body=svg))
            page.goto(url.rstrip("/") + "?group=group-01")
            expect(page.locator("#start-form")).to_be_visible()
            expect(page.locator("header")).to_have_css("background-color", "rgb(24, 46, 54)")
            expect(page.locator('#group option[value="group-01"]')).to_have_text("Group 01 (3 images)")
            expect(page.locator('#group option[value="group-02"]')).to_have_text("Group 02 (1 images)")
            expect(page.locator('#group option[value="group-03"]')).to_be_disabled()
            page.locator("#annotator").fill("tester-01")
            page.locator("#read-guidelines").check()
            page.locator('#start-form button').click()
            expect(page.locator('input[name="artifact"]').first).to_be_enabled()
            expect(page.locator('#notes')).to_have_count(0)
            expect(page.locator('#save-next')).to_have_count(0)
            page.set_viewport_size({"width": 1366, "height": 768})
            page.locator('[value="lens_contamination"]').check()
            page.locator('[value="partial_obstruction"]').check()
            page.locator('[value="none"]').check()
            assert page.locator('input[name="artifact"]:checked').count() == 1
            page.locator('[value="lens_contamination"]').check()
            page.locator('[value="partial_obstruction"]').check()
            expect(page.locator('[value="none"]')).not_to_be_checked()
            page.locator('[name="usability"][value="usable"]').check()
            expect(page.locator("#progress-text")).to_contain_text("1 labeled")
            assert page.evaluate("document.documentElement.scrollHeight <= window.innerHeight"), "Laptop layout needs page scrolling"
            assert page.locator('#annotation-form').evaluate('(el) => el.scrollHeight <= el.clientHeight'), "Label controls need scrolling"
            page.screenshot(path=str(args.artifacts / "annotation-desktop.png"), full_page=True)
            page.locator("#next").click()
            expect(page.locator("#image-heading")).to_have_text("Image 2 of 3")
            expect(page.locator('input[name="artifact"]:checked')).to_have_count(0)
            page.locator('[value="none"]').check()
            # Save results must include current selections before Next or usability.
            with page.expect_download() as partial_download:
                page.locator('#export-json').click()
            partial_path = args.artifacts / 'partial-results.json'
            partial_download.value.save_as(partial_path)
            partial = json.loads(partial_path.read_text())
            assert partial['annotations']['two']['artifact_judgment'] == 'none'
            assert partial['annotations']['two']['status'] == 'draft'
            assert 'confidence' not in partial['annotations']['one']
            assert 'notes' not in partial['annotations']['one']
            # Partial answer remains saved after reload.
            page.reload()
            page.locator("#annotator").fill("tester-01")
            page.locator("#read-guidelines").check()
            page.locator('#start-form button').click()
            expect(page.locator("#image-heading")).to_have_text("Image 2 of 3")
            expect(page.locator('[value="none"]')).to_be_checked()
            expect(page.locator("#progress-text")).to_contain_text("1 labeled")
            page.locator('[name="usability"][value="usable"]').check()
            page.locator("#next").click()
            expect(page.locator("#image-status")).to_contain_text("could not load")
            expect(page.locator('input[name="artifact"]').first).to_be_disabled()
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator("#report-broken").click()
            expect(page.locator("#progress-text")).to_contain_text("2 labeled · 1 image issues · 0 unfinished")
            with page.expect_download() as download:
                page.locator("#export-json").click()
            json_path = args.artifacts / "results.json"
            download.value.save_as(json_path)
            results = json.loads(json_path.read_text())
            assert set(results["annotations"]["one"]["labels"]) == {"lens_contamination", "partial_obstruction"}
            assert results["annotations"]["one"]["usability"] == "usable"
            assert results["annotations"]["one"]["filename"] == "image_0051.jpg"
            assert results["annotations"]["three"]["filename"] == "image_0100.jpg"
            assert results["annotations"]["three"]["status"] == "image_unavailable"
            with page.expect_download() as download:
                page.locator("#export-csv").click()
            download.value.save_as(args.artifacts / "results.csv")
            assert "lens_contamination" in (args.artifacts / "results.csv").read_text()
            assert "image_0051.jpg" in (args.artifacts / "results.csv").read_text()
            page.locator("#change-group").click()
            page.locator("#annotator").fill("tester-02")
            page.locator('#start-form button').click()
            expect(page.locator("#progress-text")).to_contain_text("0 labeled")
            page.locator("#change-group").click()
            expect(page.locator('input[type="file"]')).to_have_count(0)
            page.locator("#annotator").fill("tester-01")
            page.locator('#start-form button').click()
            expect(page.locator("#progress-text")).to_contain_text("2 labeled")
            page.locator("#previous").click()
            page.locator("#previous").click()
            expect(page.locator('[value="lens_contamination"]')).to_be_checked()
            page.locator('[value="partial_obstruction"]').uncheck()
            expect(page.locator("#progress-text")).to_contain_text("2 labeled")
            with page.expect_download() as edited_download:
                page.locator('#export-json').click()
            edited_path = args.artifacts / 'edited-results.json'
            edited_download.value.save_as(edited_path)
            assert json.loads(edited_path.read_text())['annotations']['one']['labels'] == ['lens_contamination']
            page.locator("#next").click()
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(args.artifacts / "annotation-mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            # Still works when browser storage is denied.
            blocked = context.new_page()
            blocked.route("**/data/dataset.json", lambda route: route.fulfill(json=dataset))
            blocked.route("**/data/images/*.svg", lambda route: route.fulfill(content_type="image/svg+xml", body=svg))
            blocked.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('Storage denied'); }});")
            blocked.goto(url)
            blocked.locator("#annotator").fill("no-storage")
            blocked.locator("#read-guidelines").check()
            blocked.locator('#start-form button').click()
            expect(blocked.locator("#workspace")).to_be_visible()
            expect(blocked.locator("#storage-status")).to_contain_text("unavailable")
            # A one-image group completes at one, independently of the other group.
            blocked.locator("#change-group").click()
            blocked.locator("#group").select_option("group-02")
            blocked.locator('#start-form button').click()
            expect(blocked.locator("#image-heading")).to_have_text("Image 1 of 1")
            expect(blocked.locator("#progress")).to_have_attribute("max", "1")
            expect(blocked.locator("#next")).to_be_disabled()
            blocked.locator('[value="none"]').check()
            blocked.locator('[name="usability"][value="usable"]').check()
            expect(blocked.locator("#progress-text")).to_contain_text("1 labeled · 0 image issues · 0 unfinished")
            empty = context.new_page()
            empty_data = {**dataset, "groups": [{**g, "image_ids": []} for g in dataset["groups"]]}
            empty.route("**/data/dataset.json", lambda route: route.fulfill(json=empty_data))
            empty.goto(url)
            expect(empty.locator("#loading")).to_contain_text("All three groups are empty")
            expect(empty.locator("#start-form")).not_to_be_visible()
            expect(empty.locator("header")).to_have_css("background-color", "rgb(24, 46, 54)")
            # Direct-file previews still have styling and explain the server requirement.
            preview = context.new_page()
            preview.goto((root / "index.html").as_uri())
            expect(preview.locator("header")).to_have_css("background-color", "rgb(24, 46, 54)")
            expect(preview.locator("#local-file-notice")).to_be_visible()
            assert not errors, errors
            browser.close()
        print("PASS: automatic saving, Next navigation, partial and edited exports, original filenames, no confidence/notes, browser resume, laptop layout without scrolling, mobile layout, independent groups and missing images.")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
