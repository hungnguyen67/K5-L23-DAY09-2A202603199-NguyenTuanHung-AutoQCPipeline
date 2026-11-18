"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict  # noqa: F401

import yaml  # noqa: F401

from ..common import ERROR, parse_yolo_line  # noqa: F401


def fix(ds, issues, cfg):
    errors = [issue for issue in issues if issue.severity == ERROR]
    fixes = []
    removed_images = set()

    def add_fix(image, line, action, before, after):
        fixes.append({
            "image": image,
            "line": line,
            "action": action,
            "before": before,
            "after": after,
        })

    for issue in errors:
        code = issue.code
        if not (code.startswith("DUP_IMAGE_") or code in {"LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}):
            continue
        stem = issue.image
        if stem in removed_images:
            continue
        removed_images.add(stem)
        image_paths = [path for path in ds.image_files() if path.stem == stem]
        before = ", ".join(path.name for path in image_paths)
        for path in image_paths:
            path.unlink()
        label_path = ds.label_path(stem)
        if label_path.exists():
            label_path.unlink()
        add_fix(stem, None, "remove_image", before, "")

    renamed = False
    for issue in errors:
        if issue.code != "BAD_CLASS_NAME" or renamed:
            continue
        names = {index: name for index, name in enumerate(cfg["classes"])}
        data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
        before = str(data.get("names", {}))
        data["names"] = names
        ds.yaml_path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        add_fix("data.yaml", None, "rename_classes", before, str(names))
        renamed = True

    for issue in errors:
        if issue.code != "MISSING_LABEL_FILE" or issue.image in removed_images:
            continue
        add_fix(issue.image, None, "needs_label", "(không có file)", "chuyển người gán")

    drop_codes = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
    line_issues = defaultdict(lambda: defaultdict(set))
    for issue in errors:
        if issue.image in removed_images or issue.line is None:
            continue
        if issue.code in drop_codes or issue.code == "BOX_OUT_OF_IMAGE":
            line_issues[issue.image][issue.line].add(issue.code)

    for stem, by_line in line_issues.items():
        label_path = ds.label_path(stem)
        if not label_path.exists():
            continue
        original_text = label_path.read_text(encoding="utf-8", errors="replace")
        original_lines = original_text.splitlines()
        updates = {}

        for line_no in sorted(by_line):
            if not 1 <= line_no <= len(original_lines):
                continue
            before = original_lines[line_no - 1]
            codes = by_line[line_no]
            if codes & drop_codes:
                updates[line_no] = ("drop_line", "")
                continue
            if "BOX_OUT_OF_IMAGE" not in codes:
                continue
            try:
                cls, cx, cy, width, height = parse_yolo_line(before)
            except ValueError:
                continue

            x1, y1 = max(0.0, cx - width / 2), max(0.0, cy - height / 2)
            x2, y2 = min(1.0, cx + width / 2), min(1.0, cy + height / 2)
            clipped_width, clipped_height = x2 - x1, y2 - y1
            if clipped_width <= 0 or clipped_height <= 0:
                updates[line_no] = ("drop_line", "")
            else:
                clipped = (
                    f"{cls} {(x1 + x2) / 2:.6f} {(y1 + y2) / 2:.6f} "
                    f"{clipped_width:.6f} {clipped_height:.6f}"
                )
                if clipped != before:
                    updates[line_no] = ("clip_box", clipped)

        if not updates:
            continue

        for line_no, (action, after) in sorted(updates.items()):
            add_fix(stem, line_no, action, original_lines[line_no - 1], after)

        kept_lines = []
        for line_no, line in enumerate(original_lines, 1):
            update = updates.get(line_no)
            if update and update[0] == "drop_line":
                continue
            kept_lines.append(update[1] if update else line)
        new_text = "\n".join(kept_lines)
        if original_text.endswith(("\n", "\r")) and kept_lines:
            new_text += "\n"
        label_path.write_text(new_text, encoding="utf-8")

    return fixes
