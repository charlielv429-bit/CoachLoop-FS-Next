"""Generate CC0/self-authored synthetic fixtures, never a textbook PDF.
Usage: .venv/bin/python scripts/generate_demo_pdfs.py /tmp/coachloop-demo
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "tests"))
from pdf_factory import make_pdf, make_scan

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
(out / "self-authored-demo.pdf").write_bytes(make_pdf())
for i in range(7):
    (out / f"synthetic-volume-{i + 1}.pdf").write_bytes(
        make_pdf(
            [f"第{i + 1}份自建批量测试文档，平衡与侧蹬冰检索定位参考。这不是实际教材。"]
        )
    )
try:
    (out / "self-authored-scan.pdf").write_bytes(make_scan())
except FileNotFoundError:
    print("CJK font unavailable: optional scan fixture not generated")
print("Synthetic fixtures generated locally; no copyrighted textbook text.")
