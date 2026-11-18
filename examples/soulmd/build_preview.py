"""Inline all assets into one self-contained preview.html (for sharing/previewing without a server)."""
import base64, pathlib, re
root = pathlib.Path(__file__).parent
html = (root / "index.html").read_text()
def data(rel):
    f = root / rel
    mime = {"svg": "image/svg+xml", "png": "image/png"}[f.suffix[1:]]
    return f"data:{mime};base64," + base64.b64encode(f.read_bytes()).decode()
html = re.sub(r'(src|href)="(assets/[^"]+\.(?:svg|png))"', lambda m: f'{m.group(1)}="{data(m.group(2))}"', html)
(root / "preview.html").write_text(html)
print("preview.html", len(html) // 1024, "KB")
