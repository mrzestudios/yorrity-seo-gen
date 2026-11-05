"""Yorrity SEO Gen - Windows desktop app (pywebview + local server)."""
import base64
import os
import sys
import webbrowser

import webview

from server import start_in_thread

APP_NAME = "Yorrity SEO Gen"


def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def data_dir():
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(root, "YorrityTech", "SEOGen")
    os.makedirs(path, exist_ok=True)
    return path


class Api:
    """Exposed to the page as window.pywebview.api"""

    def save_file(self, filename, b64data):
        win = webview.windows[0]
        result = win.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=filename,
            file_types=("Text files (*.txt)", "All files (*.*)"),
        )
        if not result:
            return False
        path = result if isinstance(result, str) else result[0]
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64data))
        return True


def main():
    srv, url = start_in_thread(resource("assets"), on_open_external=webbrowser.open)
    webview.create_window(
        APP_NAME,
        url,
        js_api=Api(),
        width=1180,
        height=840,
        min_size=(720, 600),
        background_color="#fbf7ec",
    )
    # private_mode=False + storage_path => API keys, presets & history persist between launches
    webview.start(
        private_mode=False,
        storage_path=os.path.join(data_dir(), "webview"),
        icon=resource("assets", "icon.ico") if sys.platform != "win32" else None,
    )
    srv.shutdown()


if __name__ == "__main__":
    main()
