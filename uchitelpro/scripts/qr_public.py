"""Печатает ссылку на сайт и QR-код (в терминал) и сохраняет qr.svg / qr.png."""
import os, subprocess, sys

name = os.environ.get("CODESPACE_NAME")
domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
port = os.environ.get("PORT", "8765")
url = f"https://{name}-{port}.{domain}/" if name else (sys.argv[1] if len(sys.argv) > 1 else f"http://127.0.0.1:{port}/")

try:
    import segno
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "segno"], check=False)
    import segno

q = segno.make(url, error="m")
print("\nСайт:", url, "\n")
q.terminal(compact=True)
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
q.save(os.path.join(here, "qr.svg"), scale=10, border=2)
try:
    q.save(os.path.join(here, "qr.png"), scale=10, border=2)
except Exception:
    pass
print("\nФайлы QR: qr.svg, qr.png в корне проекта (можно распечатать).")
