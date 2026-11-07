import os
import sys
import time
import subprocess
import urllib.request
import webbrowser

PORT = 5050
URL = f"http://127.0.0.1:{PORT}"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_SCRIPT = os.path.join(BASE_DIR, "studio", "server.py")

def get_pythonw():
    py_dir = os.path.dirname(sys.executable)
    pyw = os.path.join(py_dir, "pythonw.exe")
    if os.path.isfile(pyw):
        return pyw
    return sys.executable

def is_server_running():
    try:
        req = urllib.request.Request(f"{URL}/api/status", headers={"User-Agent": "MangaStudioLauncher"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False

def start_server():
    if is_server_running():
        return True
    
    python_bin = get_pythonw()
    startupinfo = None
    creationflags = 0
    if os.name == 'nt':
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    subprocess.Popen(
        [python_bin, SERVER_SCRIPT],
        cwd=BASE_DIR,
        creationflags=creationflags,
        startupinfo=startupinfo,
        close_fds=True
    )

    for _ in range(15):
        time.sleep(0.4)
        if is_server_running():
            return True
    return False

def find_browser():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None

def launch():
    start_server()
    browser_exe = find_browser()
    if browser_exe:
        cmd = [
            browser_exe,
            f"--app={URL}",
            "--window-size=1380,880",
            "--disable-features=Translate"
        ]
        subprocess.Popen(cmd)
    else:
        webbrowser.open(URL)

if __name__ == "__main__":
    launch()
