"""Offline: exclude assigned originals, create randomized overlapping web-image groups."""
import argparse
import hashlib
import io
import json
import os
import random
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from prepare_dataset import HERE, collect_groups

SOURCE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".heic", ".heif", ".avif", ".jfif"}


def scan_incoming(source, exclude):
    images, duplicates, assigned = {}, [], []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_EXTENSIONS or path.name.startswith("._"):
            continue
        key = "img-" + hashlib.sha256(path.read_bytes()).hexdigest()
        if key in exclude:
            assigned.append(str(path))
        elif key in images:
            duplicates.append(str(path))
        else:
            images[key] = path
    return images, duplicates, assigned


def allocate_new(image_ids, group_size=50, shared_count=10, seed=20261029):
    if group_size < 1 or not 0 <= shared_count < group_size:
        raise ValueError("Require 0 <= shared images < images per group.")
    ids = sorted(image_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("Incoming image IDs must be unique.")
    if not ids:
        return [], []
    rng = random.Random(seed)
    rng.shuffle(ids)
    if len(ids) <= group_size:
        return [ids], []
    common = ids[:shared_count]
    remaining = ids[shared_count:]
    unique_per_group = group_size - shared_count
    groups = []
    for start in range(0, len(remaining), unique_per_group):
        group = common + remaining[start:start + unique_per_group]
        rng.shuffle(group)
        groups.append(group)
    return groups, common


def make_display(source, image_id, target, max_edge, quality):
    try:
        from PIL import Image, ImageOps
        from pillow_heif import register_heif_opener
    except ImportError:
        raise ValueError("Install the image tools: python -m pip install -r annotation/requirements-images.txt") from None
    register_heif_opener()
    raw = source.read_bytes()
    if "img-" + hashlib.sha256(raw).hexdigest() != image_id:
        raise ValueError(f"Source changed while preparing groups: {source}")
    with Image.open(io.BytesIO(raw)) as original:
        source_format, source_size = original.format, original.size
        frames = getattr(original, "n_frames", 1)
        # JPEG draft decoding reduces peak memory; source identity still uses raw bytes.
        original.draft("RGB", (max_edge * 2, max_edge * 2))
        image = ImageOps.exif_transpose(original)
        if image.mode == "CMYK" and image.info.get("icc_profile"):
            from PIL import ImageCms
            image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(image.info["icc_profile"])), ImageCms.createProfile("sRGB"), outputMode="RGB")
        else:
            image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        kwargs = {"format": "WEBP", "quality": quality, "method": 6, "exact": True}
        if image.info.get("icc_profile"):
            kwargs["icc_profile"] = image.info["icc_profile"]
        image.save(target, **kwargs)
        width, height = image.size
    return {
        "image_id": image_id, "source_filename": source.name,
        "display_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "width": width, "height": height,
        "source_format": source_format, "source_size": list(source_size), "source_frames": frames,
        "profile": {"format": "webp", "max_edge": max_edge, "quality": quality, "method": 6, "orientation": "exif_transpose", "frame": 0},
    }


def add_groups(source, group_root, report_dir, group_size=50, shared_count=10, seed=20261029, max_edge=1600, quality=95, apply=False):
    source, group_root, report_dir = source.resolve(), group_root.resolve(), report_dir.resolve()
    if not source.is_dir() or not group_root.is_dir():
        raise ValueError("Source and existing group folders must exist.")
    site_root = HERE.parent.resolve()
    if report_dir == site_root or site_root in report_dir.parents:
        raise ValueError("Keep the private report/staging folder outside the website.")
    if source == group_root or source in group_root.parents or group_root in source.parents:
        raise ValueError("Source and destination groups must be separate.")
    existing, old_groups, _, _ = collect_groups(group_root)
    if not 1 <= quality <= 100 or not 64 <= max_edge <= 8192:
        raise ValueError("Use quality 1-100 and max-edge 64-8192.")
    incoming, duplicates, assigned = scan_incoming(source, set(existing))
    groups, common = allocate_new(incoming, group_size, shared_count, seed)
    first_number = max(int(group["id"][6:]) for group in old_groups) + 1
    assignments = [{"id": f"group-{first_number + n:02d}", "image_ids": ids} for n, ids in enumerate(groups)]
    report = {
        "source": str(source), "seed": seed, "group_size_limit": group_size,
        "new_unique_images": len(incoming), "excluded_already_assigned_files": assigned,
        "excluded_exact_duplicate_files": duplicates, "common_image_ids": common,
        "groups": assignments, "group_counts": {g["id"]: len(g["image_ids"]) for g in assignments},
        "source_mapping": {key: str(path) for key, path in incoming.items()},
        "display_profile": {"format": "webp", "max_edge": max_edge, "quality": quality, "method": 6},
        "applied": False,
    }
    if not apply or not assignments:
        return report
    targets = [group_root / group["id"] for group in assignments]
    if any(path.exists() for path in targets):
        raise ValueError("A destination group already exists. Nothing was copied.")
    report_dir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="incoming-web-groups-", dir=report_dir)).resolve()
    records, preview_paths = {}, {}
    try:
        cache = stage / "previews"
        cache.mkdir()
        for number, (key, path) in enumerate(sorted(incoming.items()), 1):
            preview = cache / (key + ".webp")
            records[key] = make_display(path, key, preview, max_edge, quality)
            preview_paths[key] = preview
            if number % 50 == 0 or number == len(incoming):
                print(f"Prepared {number}/{len(incoming)} web images", flush=True)
        stems = Counter(path.stem.lower() for path in incoming.values())
        for group in assignments:
            folder = stage / group["id"]
            folder.mkdir()
            metadata = {"schema_version": 1, "images": {}}
            for key in group["image_ids"]:
                path = incoming[key]
                name = path.stem + ("_" + key[4:12] if stems[path.stem.lower()] > 1 else "") + ".webp"
                shutil.copyfile(preview_paths[key], folder / name)
                metadata["images"][name] = records[key]
            (folder / ".image_sources.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        # Verify exact targets before moving populated directories on Windows.
        for group, target in zip(assignments, targets):
            staged = (stage / group["id"]).resolve()
            target = target.resolve()
            if staged.parent != stage or target.parent != group_root or target.exists():
                raise ValueError("Unsafe or occupied group destination; refusing to replace existing groups.")
            os.replace(staged, target)
        report["applied"] = True
        report["display_bytes_unique"] = sum(path.stat().st_size for path in preview_paths.values())
        report["source_bytes_unique"] = sum(path.stat().st_size for path in incoming.values())
        report["conversion_details"] = records
        report_file = report_dir / f"added-groups-{assignments[0]['id']}-through-{assignments[-1]['id']}.json"
        report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        report["report_file"] = str(report_file)
        return report
    finally:
        if stage.exists():
            if stage.parent != report_dir or not stage.name.startswith("incoming-web-groups-"):
                raise ValueError("Refusing to remove an unexpected staging directory.")
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--groups", type=Path, default=HERE / "groups")
    parser.add_argument("--report-dir", type=Path, default=HERE.parent.parent / "annotation-organizer")
    parser.add_argument("--group-size", type=int, default=50)
    parser.add_argument("--shared", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--max-edge", type=int, default=1600)
    parser.add_argument("--quality", type=int, default=95)
    parser.add_argument("--apply", action="store_true", help="Create the new folders; otherwise show the offline plan only")
    args = parser.parse_args()
    if not 1 <= args.quality <= 100 or not 64 <= args.max_edge <= 8192:
        parser.error("Use quality 1-100 and max-edge 64-8192.")
    try:
        report = add_groups(args.source, args.groups, args.report_dir, args.group_size, args.shared, args.seed, args.max_edge, args.quality, args.apply)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Could not create groups: {error}\n")
    print(f"New unique images: {report['new_unique_images']}; already assigned files skipped: {len(report['excluded_already_assigned_files'])}; exact duplicate files skipped: {len(report['excluded_exact_duplicate_files'])}.")
    print(f"New groups: {len(report['groups'])}; common overlap: {len(report['common_image_ids'])}.")
    for name, count in report["group_counts"].items():
        print(f"  {name}: {count}")
    if report["applied"]:
        print(f"Unique source MiB: {report['source_bytes_unique']/1048576:.1f}; unique display MiB: {report['display_bytes_unique']/1048576:.1f}.")
        print("Report: " + report["report_file"])
        print("Next: python annotation/prepare_dataset.py")
    elif report["groups"]:
        print("Plan only. Add --apply to create these folders.")


if __name__ == "__main__":
    main()
