import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from prepare_dataset import GROUP_IDS, collect_groups, prepare

STUDY = {"guidelines_version": "test", "labels": [{"id": "fog"}], "usability": [{"id": "usable"}]}


class ManualGroupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "groups"
        for name in GROUP_IDS:
            (self.source / name).mkdir(parents=True)

    def add(self, group, name, content):
        path = self.source / group / name
        path.write_bytes(content)
        return path

    def build(self, manifests=()):
        return prepare(self.source, self.root / "public", self.root / "private", STUDY, manifests)

    def test_unequal_groups_and_user_defined_overlap(self):
        self.add("group-01", "one.jpg", b"shared")
        self.add("group-01", "two.jpg", b"unique")
        self.add("group-02", "renamed.png", b"shared")
        self.add("group-03", "ignored.txt", b"text")
        images, groups, _, _ = collect_groups(self.source)
        self.assertEqual([len(g["image_ids"]) for g in groups], [2, 1, 0])
        self.assertEqual(len(images), 2)
        self.assertEqual(groups[0]["image_ids"][0], groups[1]["image_ids"][0])
        report = self.build()
        self.assertEqual(len(report["shared_image_ids"]), 1)
        self.assertEqual(report["shared_by_all_image_ids"], [])

    def test_no_fixed_maximum_and_no_automatic_split(self):
        for i in range(125):
            self.add("group-02", f"{i:03}.JPG", f"image {i}".encode())
        _, groups, _, _ = collect_groups(self.source)
        self.assertEqual([len(g["image_ids"]) for g in groups], [0, 125, 0])

    def test_repeated_copy_within_group_shown_once(self):
        self.add("group-01", "one.jpg", b"same")
        self.add("group-01", "copy.png", b"same")
        self.add("group-02", "same.jpg", b"same")
        _, groups, _, duplicates = collect_groups(self.source)
        self.assertEqual([len(g["image_ids"]) for g in groups], [1, 1, 0])
        self.assertEqual(len(duplicates["group-01"]), 1)

    def test_empty_groups_and_missing_folder(self):
        self.assertEqual(self.build()["assigned_unique_images"], 0)
        (self.source / "group-03").rmdir()
        with self.assertRaisesRegex(ValueError, "Missing group folder"):
            self.build()

    def test_refresh_add_remove_stable_id_and_originals_preserved(self):
        original = self.add("group-01", "named-category.jpg", b"one")
        first = self.build()
        self.assertEqual(first["dataset_id"], self.build()["dataset_id"])
        added = self.add("group-03", "second.jpg", b"two")
        second = self.build()
        self.assertNotEqual(first["dataset_id"], second["dataset_id"])
        added.unlink()
        self.assertEqual(first["dataset_id"], self.build()["dataset_id"])
        self.assertEqual(original.read_bytes(), b"one")
        payload = (self.root / "public" / "dataset.json").read_text()
        self.assertIn("named-category.jpg", payload)
        self.assertNotIn(str(self.source).replace("\\", "\\\\"), payload)
        self.assertNotIn("source_mapping", payload)
        for image in json.loads(payload)["images"].values():
            self.assertTrue((self.root / "public" / "images" / Path(image["src"]).name).is_file())

    def test_attribution_survives_refresh_without_manifest(self):
        self.add("group-01", "renamed.jpg", b"photo")
        manifest = self.root / "manifest.csv"
        with manifest.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["download_status", "sha256", "creator", "license"])
            writer.writeheader()
            writer.writerow({"download_status": "downloaded", "sha256": hashlib.sha256(b"photo").hexdigest(), "creator": "Photographer", "license": "cc0"})
        self.assertEqual(self.build([manifest])["missing_attribution_image_ids"], [])
        self.assertEqual(self.build()["missing_attribution_image_ids"], [])
        self.assertIn("Photographer", (self.root / "public" / "ATTRIBUTION.csv").read_text())


if __name__ == "__main__":
    unittest.main()
