"""Refresh the image list from three manually populated group folders."""
import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
GROUP_IDS = ("group-01", "group-02", "group-03")
HERE = Path(__file__).resolve().parent


def scan_images(source):
    images, duplicates = {}, []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        image_id = "img-" + hashlib.sha256(path.read_bytes()).hexdigest()
        if image_id in images:
            duplicates.append(str(path.relative_to(source)))
        else:
            images[image_id] = path
    return images, duplicates


def collect_groups(source):
    """Preserve membership; recognize identical copies across groups."""
    images, groups, mapping, duplicates = {}, [], {}, {}
    for number, group_id in enumerate(GROUP_IDS, 1):
        folder = source / group_id
        if not folder.is_dir():
            raise ValueError(f"Missing group folder: {folder}")
        found, repeated = scan_images(folder)
        groups.append({"id": group_id, "name": f"Group {number:02d}", "image_ids": list(found)})
        duplicates[group_id] = repeated
        mapping[group_id] = {key: str(path) for key, path in found.items()}
        for key, path in found.items():
            images.setdefault(key, path)
    return images, groups, mapping, duplicates


def read_attributions(paths):
    records = {}
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("download_status") == "downloaded" and row.get("sha256"):
                    records[row["sha256"]] = {key: row.get(key, "") for key in ("creator", "license", "license_url", "foreign_landing_url", "provider")}
    return records


def prepare(source, output, private_dir, study, manifests=()):
    source, output, private_dir = source.resolve(), output.resolve(), private_dir.resolve()
    if not source.is_dir():
        raise ValueError("The source group folder does not exist.")
    if output == source or source in output.parents or output in source.parents:
        raise ValueError("Keep generated output separate from the source group folders.")
    website_root = HERE.parent
    if private_dir == output or output in private_dir.parents or private_dir == website_root or website_root in private_dir.parents:
        raise ValueError("Keep the private organizer report outside the website root and public output.")
    if output.exists() and any(output.iterdir()) and not (output / "dataset.json").is_file():
        raise ValueError("Output is not an existing annotation dataset. Choose an empty output folder.")
    images, groups, mapping, duplicates = collect_groups(source)
    public_images = {key: {"src": f"data/images/{key}{path.suffix.lower()}"} for key, path in images.items()}
    payload = {"schema_version": 1, "study": study, "images": public_images, "groups": groups}
    dataset_id = "study-" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]
    payload["dataset_id"] = dataset_id
    # Export-only metadata: keep the existing study ID and saved annotations.
    # Use each group's own filename when a shared image has been renamed.
    for group in groups:
        group["filenames"] = {key: Path(path).name for key, path in mapping[group["id"]].items()}
    attribution = read_attributions(manifests)
    # Retain attribution from earlier refreshes when manifests are not re-supplied.
    existing_attribution = output / "ATTRIBUTION.csv"
    if existing_attribution.is_file():
        with existing_attribution.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                key = row.pop("image_id", "")
                if key.startswith("img-") and any(row.values()):
                    attribution.setdefault(key[4:], row)
    (output / "images").mkdir(parents=True, exist_ok=True)
    for key, path in images.items():
        destination = output / "images" / Path(public_images[key]["src"]).name
        if not destination.exists():
            shutil.copyfile(path, destination)
    with (output / "ATTRIBUTION.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["image_id", "creator", "license", "license_url", "foreign_landing_url", "provider"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for key in images:
            writer.writerow({"image_id": key, **attribution.get(key[4:], {})})
    counts = Counter(key for group in groups for key in group["image_ids"])
    report = {
        "dataset_id": dataset_id, "assigned_unique_images": len(images),
        "group_counts": {group["id"]: len(group["image_ids"]) for group in groups},
        "shared_image_ids": sorted(key for key, count in counts.items() if count > 1),
        "shared_by_all_image_ids": sorted(key for key, count in counts.items() if count == len(GROUP_IDS)),
        "duplicate_files_excluded_within_group": duplicates, "source_mapping": mapping,
        "groups": groups,
        "missing_attribution_image_ids": [key for key in images if key[4:] not in attribution],
        "assignments": [{"group_id": group["id"], "annotator_code": "", "role": "", "url_suffix": f"/annotation/?group={group['id']}"} for group in groups],
    }
    private_dir.mkdir(parents=True, exist_ok=True)
    (private_dir / f"{dataset_id}-organizer.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # Refresh only the generated index; originals and old generated copies stay intact.
    temporary = output / "dataset.json.tmp"
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output / "dataset.json")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=HERE / "groups", help="Parent of group-01, group-02 and group-03")
    parser.add_argument("--output", type=Path, default=HERE / "data")
    parser.add_argument("--private-report-dir", type=Path, default=HERE.parent.parent / "annotation-organizer")
    parser.add_argument("--study", type=Path, default=HERE / "study.json")
    parser.add_argument("--manifest", type=Path, action="append", default=[], help="Collector manifest CSV; repeat for multiple collections")
    args = parser.parse_args()
    try:
        study = json.loads(args.study.read_text(encoding="utf-8-sig"))
        if not study.get("labels") or not study.get("usability"):
            raise ValueError("Study needs labels and usability choices.")
        report = prepare(args.source, args.output, args.private_report_dir, study, args.manifest)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Cannot prepare study: {error}\n")
    print(f"Refreshed {report['dataset_id']}:")
    for group_id, count in report["group_counts"].items():
        print(f"  {group_id}: {count} images")
    print(f"Unique images: {report['assigned_unique_images']}; overlapping images: {len(report['shared_image_ids'])}.")
    print(f"Missing attribution: {len(report['missing_attribution_image_ids'])}. Add source manifests before sharing publicly.")
    if not study.get("contact") or not study.get("examples"):
        print("Study is a draft: add organizer contact and reviewed visual examples before inviting annotators.")
    print("Changed images, membership, order, or guidelines create a new study ID. Finalize folders before annotation starts.")


if __name__ == "__main__":
    main()
