"""Запуск УчительPRO как локального приложения.

    python run.py              # открыть в браузере (или в окне, если установлен pywebview)
    python run.py --no-open    # только запустить сервер
    python run.py --port 8765 --data D:\\UchitelPRO

Сервер слушает только 127.0.0.1: приложение недоступно из сети.
"""
from __future__ import annotations

import argparse
import socket
import threading
import webbrowser

from app import create_app


def free_port(preferred: int) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.close()
    with socket.socket() as s2:
        s2.bind(("127.0.0.1", 0))
        return s2.getsockname()[1]


def serve(app, port: int, host: str = "127.0.0.1") -> None:
    try:
        from waitress import serve as wserve  # необязательно, но надёжнее встроенного сервера
        wserve(app, host=host, port=port, threads=6)
    except ImportError:
        app.run(host=host, port=port, debug=False, threaded=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data", help="Папка данных (по умолчанию ~/.uchitelpro или %%LOCALAPPDATA%%\\UchitelPRO)")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 — открыть доступ с других устройств (Codespaces, локальная сеть)")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    app = create_app(args.data)
    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    print(f"УчительPRO запущен: {url}\nПапка данных: {app.config['DATA_DIR']}\nОстановить: Ctrl+C")

    if args.no_open:
        serve(app, port, args.host)
        return
    try:
        import webview  # pywebview: окно приложения вместо вкладки браузера
        threading.Thread(target=serve, args=(app, port), daemon=True).start()
        webview.create_window("УчительPRO", url, width=1200, height=800)
        webview.start()
    except ImportError:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        serve(app, port)


if __name__ == "__main__":
    main()
