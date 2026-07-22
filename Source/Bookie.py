import subprocess
import threading
import queue
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path
import psutil

APP_TITLE = "Audiobook Reencode Monitor"

POWERSHELL_SCRIPT = r"C:\Projects\PowerShellTools\M4B-Shrinker_v3.ps1"


class ReencodeMonitor(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("550x340")
        self.resizable(False, False)

        self.source_var = tk.StringVar()
        self.dest_var = tk.StringVar()
        self.file_var = tk.StringVar(value="No file running")
        self.size_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Idle")
        self.progress_var = tk.IntVar(value=0)

        self.msg_queue = queue.Queue()
        self.process = None

        self.build_ui()
        self.after(100, self.poll_queue)

    def build_ui(self):
        pad = {"padx": 10, "pady": 4}
        self.grid_columnconfigure(1, weight=1)
        tk.Label(self, text="Source folder").grid(row=0, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.source_var, width=70).grid(row=0, column=1, **pad)
        tk.Button(self, text="Pick", command=self.pick_source).grid(row=0, column=2, **pad)

        tk.Label(self, text="Destination").grid(row=1, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.dest_var, width=70).grid(row=1, column=1, **pad)
        tk.Button(self, text="Pick", command=self.pick_dest).grid(row=1, column=2, **pad)

        ttk.Separator(self).grid(row=2, column=0, columnspan=3, sticky="ew", pady=10)

        tk.Label(self, textvariable=self.file_var, font=("Segoe UI", 11, "bold")).grid(
            row=3, column=0, columnspan=3, sticky="w", padx=10
        )

        tk.Label(self, textvariable=self.size_var).grid(
            row=4, column=0, columnspan=3, sticky="w", padx=10
        )

        self.progress = ttk.Progressbar(
            self,
            variable=self.progress_var,
            maximum=100
)

        self.progress.grid(
            row=5,
            column=0,
            columnspan=3,
            padx=10,
            pady=10,
            sticky="ew"
        )

        tk.Label(self, textvariable=self.status_var).grid(
            row=6, column=0, columnspan=3, sticky="w", padx=10
        )

        self.start_button = tk.Button(self, text="Start Encoding", command=self.start)
        self.start_button.grid(row=7, column=1, pady=18)

        self.stop_button = tk.Button(self, text="Stop", command=self.stop_process)
        self.stop_button.grid(row=7, column=2, pady=18)

    def pick_source(self):
        folder = filedialog.askdirectory(title="Pick source folder")
        if folder:
            self.source_var.set(folder)

    def pick_dest(self):
        folder = filedialog.askdirectory(title="Pick destination folder")
        if folder:
            self.dest_var.set(folder)

    def start(self):
        source = self.source_var.get().strip()
        dest = self.dest_var.get().strip()

        if not source or not dest:
            self.status_var.set("Pick both source and destination first.")
            return

        if not Path(source).exists():
            self.status_var.set("Source folder does not exist.")
            return

        Path(dest).mkdir(parents=True, exist_ok=True)

        self.start_button.config(state="disabled")
        self.status_var.set("Starting...")
        self.file_var.set("Preparing...")
        self.size_var.set("")
        self.progress_var.set(0)

        thread = threading.Thread(
            target=self.run_powershell,
            args=(source, dest),
            daemon=True
        )
        thread.start()

    def run_powershell(self, source, dest):
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", POWERSHELL_SCRIPT,
            "-SourceFolder", source,
            "-OutputFolder", dest
        ]

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        for line in self.process.stdout:
            self.msg_queue.put(line.strip())

        code = self.process.wait()
        self.msg_queue.put(f"DONE|{code}")

    def stop_process(self):
        if not self.process or self.process.poll() is not None:
            self.status_var.set("Nothing is currently running.")
            return

        self.status_var.set("Stopping...")

        try:
            parent = psutil.Process(self.process.pid)

            for child in parent.children(recursive=True):
                child.terminate()

            parent.terminate()

            try:
                parent.wait(timeout=3)
            except psutil.TimeoutExpired:
                for child in parent.children(recursive=True):
                    child.kill()
                parent.kill()

        except psutil.NoSuchProcess:
            pass

        dest = Path(self.dest_var.get().strip())

        if dest.exists():
            for tmp_file in dest.glob("*.tmp.m4b"):
                try:
                    tmp_file.unlink()
                except OSError:
                    pass

        self.status_var.set("Stopped. Temp file cleaned up.")
        self.file_var.set("Stopped")
        self.progress_var.set(0)
        self.start_button.config(state="normal")

    def poll_queue(self):
        while not self.msg_queue.empty():
            line = self.msg_queue.get()
            self.handle_line(line)

        self.after(100, self.poll_queue)

    def handle_line(self, line):
        if line.startswith("FILE|"):
            self.file_var.set(line[5:])

        elif line.startswith("SIZE|"):
            self.size_var.set("Size: " + line[5:])

        elif line.startswith("PROGRESS|"):
            try:
                pct = int(float(line[9:]))
                self.progress_var.set(max(0, min(100, pct)))
            except ValueError:
                pass

        elif line.startswith("STATUS|"):
            self.status_var.set(line[7:])

        elif line.startswith("DONE|"):
            code = line[5:]
            if code == "0":
                self.status_var.set("Finished.")
            else:
                self.status_var.set(f"Stopped or failed with exit code {code}")
            self.start_button.config(state="normal")

        elif line:
            self.status_var.set(line[:120])


if __name__ == "__main__":
    app = ReencodeMonitor()
    app.mainloop()
