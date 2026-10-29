"""Vercel function: shared completion status and create-only GitHub submissions."""
import base64
import hashlib
import hmac
import json
import logging
import math
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 2 * 1024 * 1024


class APIError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class GitHubError(Exception):
    def __init__(self, status):
        self.status = status


@dataclass(frozen=True)
class Settings:
    token: str = ""
    repository: str = "mhage82/inline-image-classifier"
    branch: str = "main"
    prefix: str = "data/annotations/raw"
    access_code: str = ""

    @classmethod
    def from_env(cls):
        result = cls(
            token=os.environ.get("ANNOTATION_GITHUB_TOKEN", "").strip(),
            repository=os.environ.get("ANNOTATION_GITHUB_REPOSITORY", cls.repository).strip(),
            branch=os.environ.get("ANNOTATION_GITHUB_BRANCH", cls.branch).strip(),
            prefix=os.environ.get("ANNOTATION_GITHUB_PATH", cls.prefix).strip("/"),
            access_code=os.environ.get("ANNOTATION_ACCESS_CODE", ""),
        )
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", result.repository):
            raise APIError(503, "configuration", "The submission repository is not configured correctly.")
        if not result.prefix or any(not re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in result.prefix.split("/")) or not result.branch:
            raise APIError(503, "configuration", "The submission path or branch is not configured correctly.")
        return result


class GitHub:
    def __init__(self, settings):
        self.settings = settings

    def request(self, method, path, body=None):
        request = Request(
            "https://api.github.com/repos/" + self.settings.repository + "/" + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self.settings.token,
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "ThinkAndInvent-Annotation",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urlopen(request, timeout=10) as response:
                raw = response.read(MAX_BODY * 2 + 1)
                if len(raw) > MAX_BODY * 2:
                    raise GitHubError(502)
                return json.loads(raw)
        except HTTPError as error:
            raise GitHubError(error.code) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise GitHubError(502) from None

    def contents_path(self, path):
        return "contents/" + quote(path, safe="/")

    def list_files(self):
        path = self.contents_path(self.settings.prefix) + "?ref=" + quote(self.settings.branch, safe="")
        try:
            rows = self.request("GET", path)
        except GitHubError as error:
            if error.status != 404:
                raise
            # A missing raw folder is normal on first use; a missing branch or
            # inaccessible repository must not masquerade as an empty folder.
            self.request("GET", "branches/" + quote(self.settings.branch, safe=""))
            return set()
        if not isinstance(rows, list) or len(rows) >= 1000:
            raise GitHubError(502)
        return {row["name"] for row in rows if row.get("type") == "file"}

    def read_file(self, path):
        try:
            row = self.request("GET", self.contents_path(path) + "?ref=" + quote(self.settings.branch, safe=""))
        except GitHubError as error:
            if error.status == 404:
                return None
            raise
        try:
            if row.get("encoding") != "base64":
                raise ValueError("Unexpected encoding")
            return json.loads(base64.b64decode(row["content"]))
        except (ValueError, KeyError, TypeError):
            raise GitHubError(502) from None

    def create_file(self, path, payload):
        # Omitting sha deliberately makes this CREATE-ONLY. A second annotator
        # cannot replace the first accepted submission for the same group.
        return self.request("PUT", self.contents_path(path), {
            "message": "Submit annotations for " + payload["group_id"],
            "content": base64.b64encode((json.dumps(payload, indent=2) + "\n").encode()).decode(),
            "branch": self.settings.branch,
        })


def group_version(dataset, group):
    # Other groups can be added without reopening already completed groups.
    signature = {
        "image_ids": sorted(group["image_ids"]),
        "labels": dataset["study"]["labels"],
        "guidelines_version": dataset["study"]["guidelines_version"],
    }
    display_versions = {key: dataset.get("images", {}).get(key, {}).get("display", {}).get("display_sha256") for key in group["image_ids"]}
    if any(display_versions.values()):
        signature["display_versions"] = display_versions
    return hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:20]


def submission_filename(dataset, group):
    return group["id"] + "_" + group_version(dataset, group) + ".json"


def require(condition, message):
    if not condition:
        raise APIError(400, "invalid_submission", message)


class AnnotationService:
    def __init__(self, dataset, settings, github=None):
        self.dataset, self.settings = dataset, settings
        self.github = github or GitHub(settings)

    def ready(self):
        if not self.settings.token:
            raise APIError(503, "not_configured", "Online submission has not been configured yet.")

    def status(self):
        self.ready()
        try:
            filenames = self.github.list_files()
        except GitHubError as error:
            logging.getLogger(__name__).warning("Annotation availability: GitHub returned HTTP %s", error.status)
            if error.status == 401:
                raise APIError(503, "github_auth", "GitHub rejected the submission token. The organizer needs to replace ANNOTATION_GITHUB_TOKEN in Vercel and redeploy.") from None
            if error.status == 403:
                raise APIError(503, "github_access", "GitHub denied access or reached its request limit. The organizer should check the token's selected repository and Contents permissions in GitHub.") from None
            if error.status == 404:
                raise APIError(503, "github_repository", "The configured GitHub repository or branch could not be accessed. The organizer should check repository access and the configured branch.") from None
            raise APIError(503, "storage_unavailable", "Group availability could not be checked. Please try again. The organizer can check the Vercel function logs for the GitHub response status.") from None
        return {
            "dataset_id": self.dataset["dataset_id"],
            "requires_access_code": bool(self.settings.access_code),
            "groups": {group["id"]: {
                "state": "completed" if submission_filename(self.dataset, group) in filenames else "available",
            } for group in self.dataset["groups"]},
        }

    def validate(self, payload):
        require(isinstance(payload, dict), "Expected a JSON object.")
        if payload.get("dataset_id") != self.dataset["dataset_id"]:
            raise APIError(409, "stale_dataset", "The image groups have changed. Download a backup, then refresh the page.")
        require(payload.get("guidelines_version") == self.dataset["study"]["guidelines_version"], "The label definitions have changed. Refresh the page.")
        require(payload.get("schema_version") == 1, "Unsupported submission format.")
        try:
            submission_id = str(uuid.UUID(payload.get("submission_id", "")))
        except (ValueError, TypeError, AttributeError):
            raise APIError(400, "invalid_submission", "Missing or invalid submission identifier.") from None
        annotator = payload.get("annotator_id")
        require(isinstance(annotator, str) and 1 <= len(annotator.strip()) <= 64 and annotator.isprintable(), "Enter a name or annotator code of at most 64 characters.")
        group = next((g for g in self.dataset["groups"] if g["id"] == payload.get("group_id")), None)
        require(group is not None and bool(group["image_ids"]), "Unknown or empty image group.")
        annotations = payload.get("annotations")
        require(isinstance(annotations, dict) and set(annotations) == set(group["image_ids"]), "Label every image in this group before submitting.")
        allowed = {label["id"] for label in self.dataset["study"]["labels"]}
        clean = {}
        for image_id in group["image_ids"]:
            row = annotations[image_id]
            require(isinstance(row, dict) and row.get("image_id") == image_id and row.get("status") == "annotated", "Every image must have a completed answer.")
            labels = row.get("labels")
            require(isinstance(labels, list) and all(isinstance(x, str) for x in labels), "Invalid label list.")
            require(len(labels) == len(set(labels)) and set(labels) <= allowed, "Unknown or duplicate artifact label.")
            judgment = row.get("artifact_judgment")
            require(judgment in ("present", "none", "uncertain") and (judgment == "present") == bool(labels), "Artifact selections are inconsistent.")
            seconds = row.get("active_seconds", 0)
            require(isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and math.isfinite(seconds) and 0 <= seconds <= 604800, "Invalid interaction timing.")
            clean[image_id] = {
                "image_id": image_id, "filename": group.get("filenames", {}).get(image_id, ""),
                "labels": sorted(labels), "artifact_judgment": judgment, "status": "annotated",
                "active_seconds": seconds,
            }
            display = self.dataset.get("images", {}).get(image_id, {}).get("display")
            if display:
                clean[image_id]["display"] = display
            for field in ("started_at", "updated_at"):
                value = row.get(field)
                if isinstance(value, str) and len(value) <= 64:
                    clean[image_id][field] = value
        answers = {key: {"labels": row["labels"], "artifact_judgment": row["artifact_judgment"]} for key, row in clean.items()}
        answers_digest = hashlib.sha256(json.dumps({"annotator": annotator.strip(), "answers": answers}, sort_keys=True).encode()).hexdigest()
        return group, {
            "schema_version": 1, "submission_id": submission_id,
            "dataset_id": self.dataset["dataset_id"], "guidelines_version": self.dataset["study"]["guidelines_version"],
            "group_id": group["id"], "group_version": group_version(self.dataset, group),
            "annotator_id": annotator.strip(), "annotations": clean,
            "answers_digest": answers_digest,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }

    def submit(self, payload, access_code=""):
        self.ready()
        if self.settings.access_code and not hmac.compare_digest(self.settings.access_code.encode(), access_code.encode()):
            raise APIError(403, "access_code", "The class access code was not accepted. Check the code in Change session.")
        group, clean = self.validate(payload)
        filename = submission_filename(self.dataset, group)
        path = self.settings.prefix + "/" + filename

        def existing_receipt(existing):
            if not existing:
                return None
            if existing.get("submission_id") == clean["submission_id"] and existing.get("answers_digest") == clean["answers_digest"]:
                return {"submitted": True, "already_saved": True, "submission_id": clean["submission_id"], "group_id": group["id"], "path": path}
            raise APIError(409, "group_completed", "This group has already been submitted. Your local answers are still available to download as a backup.")

        try:
            receipt = existing_receipt(self.github.read_file(path))
            if receipt:
                return receipt
            for attempt in range(3):
                try:
                    response = self.github.create_file(path, clean)
                    return {"submitted": True, "submission_id": clean["submission_id"], "group_id": group["id"], "path": path, "commit_sha": response.get("commit", {}).get("sha", "")}
                except GitHubError as error:
                    if error.status not in (409, 422):
                        raise
                    receipt = existing_receipt(self.github.read_file(path))
                    if receipt:
                        return receipt
                    # Different groups may race to update the repository branch.
                    # Retry create-only; never fall back to replacing a file.
                    if attempt < 2:
                        time.sleep(0.15 * (attempt + 1))
            raise GitHubError(409)
        except GitHubError:
            raise APIError(503, "storage_unavailable", "Submission could not be confirmed. Your answers are saved in this browser. Retry Submit annotations; duplicate files will not be created.") from None


class handler(BaseHTTPRequestHandler):
    def _service(self):
        with (ROOT / "annotation" / "data" / "dataset.json").open(encoding="utf-8") as file:
            return AnnotationService(json.load(file), Settings.from_env())

    def _respond(self, status, body):
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    def _run(self, action):
        try:
            result = action()
            self._respond(200, result)
        except APIError as error:
            self._respond(error.status, {"error": error.message, "code": error.code})
        except Exception:
            # Do not expose GitHub credentials, student payloads, or tracebacks.
            self._respond(503, {"error": "The annotation service is unavailable. Please retry later.", "code": "service_unavailable"})

    def do_GET(self):
        def get():
            if parse_qs(urlparse(self.path).query).get("action") == ["health"]:
                return {"service": "annotation-api", "configured": bool(Settings.from_env().token)}
            return self._service().status()
        self._run(get)

    def do_POST(self):
        def post():
            origin = urlparse(self.headers.get("Origin", ""))
            host = self.headers.get("X-Forwarded-Host", self.headers.get("Host", "")).split(",")[0].strip()
            if origin.scheme not in ("http", "https") or origin.netloc.lower() != host.lower():
                raise APIError(403, "origin", "Submit annotations from this website.")
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise APIError(415, "content_type", "Expected JSON annotations.")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if not 0 < length <= MAX_BODY:
                raise APIError(413, "body_size", "The submission is empty or too large.")
            try:
                payload = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError):
                raise APIError(400, "invalid_json", "The annotation JSON could not be read.") from None
            return self._service().submit(payload, self.headers.get("X-Annotation-Code", ""))
        self._run(post)

    def do_OPTIONS(self):
        self._respond(405, {"error": "Use this website to submit annotations."})
