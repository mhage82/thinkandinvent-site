import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from add_image_groups import add_groups, allocate_new
from prepare_dataset import collect_groups, prepare


class NewGroupAllocationTests(unittest.TestCase):
    def test_all_new_images_covered_with_exact_common_overlap(self):
        ids = [f"image-{i:04d}" for i in range(1071)]
        groups, common = allocate_new(ids)
        self.assertEqual(len(groups), 27)
        self.assertEqual([len(g) for g in groups], [50] * 26 + [31])
        self.assertEqual(len(common), 10)
        counts = Counter(key for group in groups for key in group)
        self.assertEqual(set(counts), set(ids))
        self.assertTrue(all(len(set(g)) == len(g) for g in groups))
        self.assertTrue(all(counts[key] == (27 if key in common else 1) for key in ids))
        self.assertEqual(allocate_new(list(reversed(ids))), (groups, common))

    def test_empty_small_and_invalid_input(self):
        self.assertEqual(allocate_new([]), ([], []))
        groups, common = allocate_new(["one", "two"])
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]), {"one", "two"})
        self.assertEqual(common, [])
        for size, shared in [(0, 0), (50, -1), (50, 50)]:
            with self.assertRaises(ValueError):
                allocate_new(["one"], size, shared)


@unittest.skipUnless(importlib.util.find_spec("PIL") and importlib.util.find_spec("pillow_heif"), "Install requirements-images.txt for conversion integration tests")
class WebCopyTests(unittest.TestCase):
    def test_original_ids_filenames_old_groups_and_repeated_run(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "incoming"
            source.mkdir()
            groups = root / "groups"
            old_group = groups / "group-03"
            old_group.mkdir(parents=True)
            for i in range(9):
                Image.new("RGB", (200 + i, 100), (i * 23, 40, 100)).save(source / f"image_{i:04d}.jpg")
            shutil.copyfile(source / "image_0000.jpg", old_group / "renamed-old.jpg")
            shutil.copyfile(source / "image_0001.jpg", source / "duplicate.jpg")
            original_bytes = (old_group / "renamed-old.jpg").read_bytes()
            report = add_groups(source, groups, root / "private", group_size=4, shared_count=1, max_edge=64, apply=True)
            self.assertEqual(report["new_unique_images"], 8)
            self.assertEqual(report["group_counts"], {"group-04": 4, "group-05": 4, "group-06": 2})
            self.assertEqual((old_group / "renamed-old.jpg").read_bytes(), original_bytes)
            found, _, _, _ = collect_groups(groups)
            expected = {"img-" + hashlib.sha256(path.read_bytes()).hexdigest() for path in source.glob("*.jpg")}
            self.assertEqual(set(found), expected)
            for path in groups.glob("group-*/*.webp"):
                with Image.open(path) as image:
                    self.assertLessEqual(max(image.size), 64)
            study = {"guidelines_version": "2", "labels": [{"id": "fault"}]}
            prepare(groups, root / "public", root / "private", study)
            dataset = json.loads((root / "public" / "dataset.json").read_text())
            for group in dataset["groups"]:
                if group["id"] == "group-03":
                    continue
                for key, name in group["filenames"].items():
                    self.assertTrue((source / name).is_file())
                    self.assertEqual(key, "img-" + hashlib.sha256((source / name).read_bytes()).hexdigest())
                    self.assertIn("display", dataset["images"][key])
            again = add_groups(source, groups, root / "private", group_size=4, shared_count=1, max_edge=64, apply=True)
            self.assertEqual(again["new_unique_images"], 0)
            self.assertEqual(again["groups"], [])
            changed = next(groups.glob("group-04/*.webp"))
            changed.write_bytes(b"changed-preview")
            with self.assertRaisesRegex(ValueError, "changed without updating"):
                collect_groups(groups)


if __name__ == "__main__":
    unittest.main()
