from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, __version__
from .devices import Device, list_devices
from .operations import command_path, missing_commands

BG = "#f5f6f8"
SURFACE = "#ffffff"
TEXT = "#111827"
MUTED = "#626b77"
BORDER = "#c8cdd4"
ACCENT = "#0a67d1"
ACCENT_HOVER = "#0758b6"
DANGER = "#c62828"
SUCCESS = "#16a34a"
DISABLED_BG = "#eef0f3"
DISABLED_TEXT = "#9aa1aa"
DEVICE_PLACEHOLDER = "Select a removable USB drive…"


def human_bytes(value: int | float | None) -> str:
    if value is None:
        return "—"
    value = float(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TiB"


class BootCrafterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__(className="BootCrafterLinux")
        self.title(f"{APP_NAME} {__version__}")
        # Compact Windows-utility proportions while still fitting 1366x768 Linux desktops.
        # The destructive action footer is fixed and never scrolls out of view.
        screen_w = max(self.winfo_screenwidth(), 800)
        screen_h = max(self.winfo_screenheight(), 600)
        width = min(1000, max(800, screen_w - 180))
        height = min(690, max(610, screen_h - 90))
        self.geometry(f"{width}x{height}")
        self.minsize(760, 560)
        self.configure(bg=BG)
        self.devices: list[Device] = []
        self.device_by_display: dict[str, Device] = {}
        self.worker_queue: queue.Queue = queue.Queue()
        self.process: subprocess.Popen | None = None
        self.busy = False
        self.last_operation_succeeded = False
        self._configure_style()
        self._set_window_icon()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, lambda: self.refresh_devices(log=True))
        self.after(100, self._poll_queue)
        self.after(4000, self._periodic_refresh)

    def _set_window_icon(self) -> None:
        candidates = [
            "/usr/share/icons/hicolor/128x128/apps/bootcrafter-linux.png",
            str(Path(__file__).resolve().parent.parent / "assets" / "bootcrafter-linux-128.png"),
            str(Path(__file__).resolve().parent.parent / "assets" / "bootcrafter-linux-source.png"),
        ]
        for path in candidates:
            if not os.path.isfile(path):
                continue
            try:
                self._icon_image = tk.PhotoImage(file=path)
                self.iconphoto(True, self._icon_image)
                return
            except tk.TclError:
                continue

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        base_font = ("DejaVu Sans", 10)
        style.configure(".", background=BG, foreground=TEXT, font=base_font)
        style.configure("TFrame", background=BG)
        style.configure("Surface.TFrame", background=SURFACE)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Surface.TLabel", background=SURFACE, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("SurfaceMuted.TLabel", background=SURFACE, foreground=MUTED)
        style.configure("Section.TLabel", background=BG, foreground=TEXT, font=("DejaVu Sans", 14, "bold"))
        style.configure("Field.TLabel", background=BG, foreground=TEXT, font=("DejaVu Sans", 9))
        style.configure("Info.TLabel", background=BG, foreground=MUTED, font=("DejaVu Sans", 9))
        style.configure("Success.TLabel", background=BG, foreground=SUCCESS, font=("DejaVu Sans", 10, "bold"))
        style.configure("TSeparator", background="#858b93")

        style.configure("TButton", padding=(10, 6), background=SURFACE, foreground=TEXT, borderwidth=1, relief="solid")
        style.map("TButton", background=[("active", "#f0f3f7"), ("disabled", DISABLED_BG)], foreground=[("disabled", DISABLED_TEXT)])
        style.configure("Primary.TButton", padding=(24, 7), background=SURFACE, foreground=ACCENT, borderwidth=1, relief="solid", bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT, font=("DejaVu Sans", 10, "bold"))
        style.map("Primary.TButton", background=[("active", "#edf5ff"), ("disabled", DISABLED_BG)], foreground=[("active", ACCENT_HOVER), ("disabled", DISABLED_TEXT)])
        style.configure("Footer.TButton", padding=(18, 7), background=SURFACE, foreground=TEXT, borderwidth=1, relief="solid")

        style.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE, foreground=TEXT, arrowcolor=TEXT, padding=5, borderwidth=1)
        style.map("TCombobox",
                  fieldbackground=[("disabled", DISABLED_BG), ("readonly", SURFACE)],
                  foreground=[("disabled", DISABLED_TEXT), ("readonly", TEXT)])
        style.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT, insertcolor=TEXT, padding=5, borderwidth=1)
        style.map("TEntry", fieldbackground=[("disabled", DISABLED_BG)], foreground=[("disabled", DISABLED_TEXT)])
        style.configure("TCheckbutton", background=BG, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", BG)], foreground=[("disabled", DISABLED_TEXT)])
        style.configure("Green.Horizontal.TProgressbar", troughcolor="#e3e6ea", background=SUCCESS, bordercolor="#d2d6dc", lightcolor=SUCCESS, darkcolor=SUCCESS)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)

        # Fixed footer: destructive action can never disappear below the viewport.
        footer = ttk.Frame(outer, padding=(18, 7, 18, 9))
        footer.pack(side="bottom", fill="x")
        ttk.Separator(footer, orient="horizontal").pack(side="top", fill="x", pady=(0, 10))

        footer_buttons = ttk.Frame(footer)
        footer_buttons.pack(fill="x")
        self.about_btn = ttk.Button(footer_buttons, text="ⓘ", width=3, command=self.show_about)
        self.about_btn.pack(side="left")
        self.hash_btn = ttk.Button(footer_buttons, text="SHA-256", command=self.calculate_hash)
        self.hash_btn.pack(side="left", padx=(8, 0))
        self.log_btn = ttk.Button(footer_buttons, text="Log", command=self._toggle_log)
        self.log_btn.pack(side="left", padx=(8, 0))
        self.close_btn = ttk.Button(footer_buttons, text="CLOSE", style="Footer.TButton", command=self._on_close)
        self.close_btn.pack(side="right")
        self.start_btn = ttk.Button(footer_buttons, text="START", style="Primary.TButton", command=self.start_operation)
        self.start_btn.pack(side="right", padx=(0, 14))

        body_wrap = ttk.Frame(outer)
        body_wrap.pack(side="top", fill="both", expand=True)
        self.body_canvas = tk.Canvas(body_wrap, bg=BG, highlightthickness=0, bd=0)
        self.body_scroll = ttk.Scrollbar(body_wrap, orient="vertical", command=self.body_canvas.yview)
        self.body_canvas.configure(yscrollcommand=self.body_scroll.set)
        self.body_scroll.pack(side="right", fill="y")
        self.body_canvas.pack(side="left", fill="both", expand=True)

        root = ttk.Frame(self.body_canvas, padding=(22, 5, 22, 0))
        self._body_window = self.body_canvas.create_window((0, 0), window=root, anchor="nw")

        def sync_scroll_region(_event=None) -> None:
            bbox = self.body_canvas.bbox("all")
            self.body_canvas.configure(scrollregion=bbox)
            if not bbox:
                return
            needs_scroll = bbox[3] - bbox[1] > self.body_canvas.winfo_height() + 2
            if needs_scroll and not self.body_scroll.winfo_ismapped():
                self.body_scroll.pack(side="right", fill="y")
            elif not needs_scroll and self.body_scroll.winfo_ismapped():
                self.body_scroll.pack_forget()
                self.body_canvas.yview_moveto(0.0)

        def sync_body_width(event) -> None:
            self.body_canvas.itemconfigure(self._body_window, width=event.width)

        root.bind("<Configure>", sync_scroll_region)
        self.body_canvas.bind("<Configure>", sync_body_width)
        self.body_canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.body_canvas.bind_all("<Button-4>", self._on_mousewheel, add="+")
        self.body_canvas.bind_all("<Button-5>", self._on_mousewheel, add="+")

        def section_heading(parent: ttk.Frame, text: str) -> ttk.Frame:
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=(1, 4))
            ttk.Label(row, text=text, style="Section.TLabel").pack(side="left")
            ttk.Separator(row, orient="horizontal").pack(side="left", fill="x", expand=True, padx=(12, 0), pady=(10, 0))
            return row

        # ----------------------------- Drive Properties -----------------------------
        section_heading(root, "Drive Properties")
        drive = ttk.Frame(root)
        drive.pack(fill="x")
        drive.columnconfigure(0, weight=1)
        drive.columnconfigure(1, weight=0)

        ttk.Label(drive, text="Device", style="Field.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(drive, textvariable=self.device_var, state="readonly")
        self.device_combo.grid(row=1, column=0, sticky="ew", pady=(1, 4))
        self.device_combo.bind("<<ComboboxSelected>>", lambda _e: self._device_changed())
        self.refresh_btn = ttk.Button(drive, text="REFRESH", command=lambda: self.refresh_devices(log=True))
        self.refresh_btn.grid(row=1, column=1, padx=(10, 0), pady=(1, 4), sticky="ew")

        ttk.Label(drive, text="Boot selection", style="Field.TLabel").grid(row=2, column=0, columnspan=2, sticky="w")
        boot_row = ttk.Frame(drive)
        boot_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(1, 5))
        boot_row.columnconfigure(0, weight=1)
        self.image_var = tk.StringVar()
        self.image_entry = ttk.Entry(boot_row, textvariable=self.image_var)
        self.image_entry.grid(row=0, column=0, sticky="ew")
        self.image_ok_var = tk.StringVar(value="")
        self.image_ok_label = ttk.Label(boot_row, textvariable=self.image_ok_var, style="Success.TLabel", width=2, anchor="center")
        self.image_ok_label.grid(row=0, column=1, padx=(8, 4))
        self.select_btn = ttk.Button(boot_row, text="SELECT", command=self.select_image)
        self.select_btn.grid(row=0, column=2, padx=(4, 0))

        mode_row = ttk.Frame(drive)
        mode_row.grid(row=4, column=0, columnspan=2, sticky="ew")
        mode_row.columnconfigure(0, weight=1)
        mode_row.columnconfigure(1, weight=1)
        ttk.Label(mode_row, text="Image mode", style="Field.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 18))
        ttk.Label(mode_row, text="Verify after writing", style="Field.TLabel").grid(row=0, column=1, sticky="w")
        self.mode_var = tk.StringVar(value="Linux/Proxmox ISO or disk image (raw)")
        self.mode_combo = ttk.Combobox(
            mode_row, textvariable=self.mode_var, state="readonly",
            values=(
                "Linux/Proxmox ISO or disk image (raw)",
                "Windows installer ISO (UEFI)",
                "Non bootable / Format only",
            ),
        )
        self.mode_combo.grid(row=1, column=0, sticky="ew", padx=(0, 18), pady=(1, 4))
        self.mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._mode_changed())
        self.verify_var = tk.BooleanVar(value=True)
        self.verify_check = ttk.Checkbutton(mode_row, text="Verify after writing (recommended)", variable=self.verify_var)
        self.verify_check.grid(row=1, column=1, sticky="w", pady=(1, 4))

        target_row = ttk.Frame(drive)
        target_row.grid(row=5, column=0, columnspan=2, sticky="ew")
        target_row.columnconfigure(0, weight=1)
        target_row.columnconfigure(1, weight=1)
        ttk.Label(target_row, text="Partition scheme", style="Field.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 18))
        ttk.Label(target_row, text="Target system", style="Field.TLabel").grid(row=0, column=1, sticky="w")
        self.scheme_var = tk.StringVar(value="GPT")
        self.scheme_combo = ttk.Combobox(target_row, textvariable=self.scheme_var, values=("GPT", "MBR"), state="disabled")
        self.scheme_combo.grid(row=1, column=0, sticky="ew", padx=(0, 18), pady=(1, 3))
        self.target_var = tk.StringVar(value="From image")
        self.target_combo = ttk.Combobox(target_row, textvariable=self.target_var, values=("From image", "UEFI", "Not applicable"), state="disabled")
        self.target_combo.grid(row=1, column=1, sticky="ew", pady=(1, 3))

        self.mode_note_var = tk.StringVar()
        self.mode_note = ttk.Label(drive, textvariable=self.mode_note_var, style="Info.TLabel", wraplength=860, justify="left")
        self.mode_note.grid(row=6, column=0, columnspan=2, sticky="w", pady=(1, 2))

        self.advanced_visible = False
        self.advanced_btn = ttk.Button(drive, text="›  Show advanced drive properties", command=self._toggle_advanced)
        self.advanced_btn.grid(row=7, column=0, columnspan=2, sticky="w", pady=(1, 1))
        self.advanced_frame = ttk.Frame(drive)
        self.advanced_frame.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(1, 2))
        self.advanced_frame.grid_remove()
        self.advanced_var = tk.StringVar(value="Safety: explicit USB selection • system disks protected • device identity rechecked before erase")
        ttk.Label(self.advanced_frame, textvariable=self.advanced_var, style="Info.TLabel", wraplength=860, justify="left").pack(anchor="w")

        # ------------------------------ Format Options ------------------------------
        section_heading(root, "Format Options")
        fmt = ttk.Frame(root)
        fmt.pack(fill="x")
        fmt.columnconfigure(0, weight=1)
        fmt.columnconfigure(1, weight=1)
        self.format_note_var = tk.StringVar()
        ttk.Label(fmt, textvariable=self.format_note_var, style="Info.TLabel", wraplength=860, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 3)
        )

        ttk.Label(fmt, text="Volume label", style="Field.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 18))
        ttk.Label(fmt, text="File system", style="Field.TLabel").grid(row=1, column=1, sticky="w")
        self.label_var = tk.StringVar(value="BOOTCRAFT")
        self.label_entry = ttk.Entry(fmt, textvariable=self.label_var)
        self.label_entry.grid(row=2, column=0, sticky="ew", padx=(0, 18), pady=(1, 4))
        self.fs_var = tk.StringVar(value="FAT32")
        self.fs_combo = ttk.Combobox(fmt, textvariable=self.fs_var, values=("FAT32", "exFAT", "NTFS", "ext4"), state="disabled")
        self.fs_combo.grid(row=2, column=1, sticky="ew", pady=(1, 4))

        ttk.Label(fmt, text="Cluster size", style="Field.TLabel").grid(row=3, column=0, sticky="w", padx=(0, 18))
        self.cluster_var = tk.StringVar(value="Default")
        self.cluster_combo = ttk.Combobox(fmt, textvariable=self.cluster_var, values=("Default",), state="disabled")
        self.cluster_combo.grid(row=4, column=0, sticky="ew", padx=(0, 18), pady=(1, 2))

        opts = ttk.Frame(fmt)
        opts.grid(row=3, column=1, rowspan=3, sticky="nw", pady=(0, 1))
        self.quick_var = tk.BooleanVar(value=True)
        self.quick_check = ttk.Checkbutton(opts, text="Quick format", variable=self.quick_var, state="disabled")
        self.quick_check.pack(anchor="w")
        self.extended_var = tk.BooleanVar(value=False)
        self.extended_check = ttk.Checkbutton(opts, text="Create extended label and icon files", variable=self.extended_var, state="disabled")
        self.extended_check.pack(anchor="w", pady=(2, 0))
        bad_row = ttk.Frame(opts)
        bad_row.pack(anchor="w", pady=(2, 0))
        self.badblocks_var = tk.BooleanVar(value=False)
        self.badblocks_check = ttk.Checkbutton(bad_row, text="Check device for bad blocks", variable=self.badblocks_var, state="disabled")
        self.badblocks_check.pack(side="left")
        self.pass_var = tk.StringVar(value="1 pass")
        self.pass_combo = ttk.Combobox(bad_row, textvariable=self.pass_var, values=("1 pass",), width=8, state="disabled")
        self.pass_combo.pack(side="left", padx=(8, 0))

        # ---------------------------------- Status ----------------------------------
        section_heading(root, "Status")
        status_frame = ttk.Frame(root)
        status_frame.pack(fill="x")
        self.progress = ttk.Progressbar(status_frame, mode="determinate", maximum=100, style="Green.Horizontal.TProgressbar")
        self.progress.pack(side="left", fill="x", expand=True, pady=(0, 3))
        self.percent_var = tk.StringVar(value="0%")
        ttk.Label(status_frame, textvariable=self.percent_var).pack(side="left", padx=(10, 0), pady=(0, 3))
        self.status_var = tk.StringVar(value="Ready")
        self.detail_var = tk.StringVar(value="Select an image and a removable USB drive.")
        ttk.Label(root, textvariable=self.detail_var, style="Muted.TLabel", wraplength=860, justify="left").pack(fill="x", anchor="w")

        # Optional log panel; compact UI keeps it hidden until requested.
        self.log_panel = ttk.Frame(root)
        self.log_panel.pack(fill="both", expand=True, pady=(9, 0))
        self.log_panel.pack_forget()
        log_head = ttk.Frame(self.log_panel)
        log_head.pack(fill="x")
        ttk.Label(log_head, text="Activity log", style="Field.TLabel").pack(side="left")
        ttk.Button(log_head, text="Clear", command=self._clear_log).pack(side="right")
        self.log = tk.Text(
            self.log_panel, height=6, bg="#111318", fg="#e5e7eb", insertbackground="white",
            relief="solid", bd=1, padx=9, pady=7, font=("DejaVu Sans Mono", 9),
        )
        self.log.pack(fill="both", expand=True, pady=(4, 0))
        self.log.configure(state="disabled")

        self._mode_changed()

    def _toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_frame.grid()
            self.advanced_btn.configure(text="⌄  Hide advanced drive properties")
        else:
            self.advanced_frame.grid_remove()
            self.advanced_btn.configure(text="›  Show advanced drive properties")

    def _toggle_log(self) -> None:
        if self.log_panel.winfo_manager():
            self.log_panel.pack_forget()
            self.log_btn.configure(text="Log")
        else:
            self.log_panel.pack(fill="both", expand=True, pady=(9, 0))
            self.log_btn.configure(text="Hide Log")
            self.after_idle(lambda: self.body_canvas.yview_moveto(1.0))

    def _on_mousewheel(self, event) -> None:
        if not hasattr(self, "body_canvas"):
            return
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            raw = getattr(event, "delta", 0)
            if not raw:
                return
            delta = -1 if raw > 0 else 1
        self.body_canvas.yview_scroll(delta * 3, "units")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _set_log(self, text: str) -> None:
        self.log.configure(state="normal")
        stamp = time.strftime("%H:%M:%S")
        self.log.insert("end", f"[{stamp}] {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _periodic_refresh(self) -> None:
        if not self.busy:
            self.refresh_devices(log=False)
        self.after(4000, self._periodic_refresh)

    def refresh_devices(self, *, log: bool = False) -> None:
        if self.busy:
            return
        previous = self._selected_device()
        previous_token = previous.identity_token if previous else ""
        try:
            devices = list_devices()
            self.devices = devices
            self.device_by_display = {d.display: d for d in devices}
            values = list(self.device_by_display)
            self.device_combo.configure(values=[DEVICE_PLACEHOLDER, *values])
            chosen = DEVICE_PLACEHOLDER
            if previous and previous_token:
                for display, device in self.device_by_display.items():
                    if device.path == previous.path and device.identity_token == previous_token:
                        chosen = display
                        break
            self.device_var.set(chosen)
            if values:
                self.status_var.set(f"Ready • {len(values)} removable drive(s) found")
                if chosen == DEVICE_PLACEHOLDER:
                    self.detail_var.set("Select the exact USB drive you want to erase. BootCrafter does not auto-select a replacement drive.")
                else:
                    self._device_changed()
            else:
                self.device_var.set(DEVICE_PLACEHOLDER)
                self.status_var.set("No removable USB drive found")
                self.detail_var.set("Connect a removable USB drive, then click Refresh.")
            if log:
                self._set_log(f"Device scan complete: {len(values)} safe target(s).")
        except Exception as exc:
            self.status_var.set("Device scan failed")
            self.detail_var.set(str(exc))
            if log:
                self._set_log(f"ERROR: {exc}")

    def _device_changed(self) -> None:
        device = self._selected_device()
        if device and not self.busy:
            suffix = ""
            if not device.strong_hardware_id:
                suffix = " • Note: this USB does not expose a serial/WWN; verify model, size and /dev path carefully."
            self.detail_var.set(f"Target: {device.display}{suffix}")

    def _mode_changed(self) -> None:
        mode_key = self._mode_key()
        format_only = mode_key == "format"
        windows_mode = mode_key == "windows"

        image_state = "disabled" if format_only else "normal"
        self.image_entry.configure(state=image_state)
        self.select_btn.configure(state=image_state)
        self.verify_check.configure(state="normal" if mode_key == "raw" else "disabled")

        # Cluster size, extended label files and bad-block passes are intentionally
        # informational/disabled until the backend implements them. No fake controls.
        self.cluster_combo.configure(state="disabled")
        self.quick_check.configure(state="disabled")
        self.extended_check.configure(state="disabled")
        self.badblocks_check.configure(state="disabled")
        self.pass_combo.configure(state="disabled")

        if mode_key == "raw":
            self.scheme_var.set("From image")
            self.target_var.set("From image")
            self.scheme_combo.configure(values=("From image",), state="disabled")
            self.target_combo.configure(values=("From image",), state="disabled")
            self.fs_var.set("From image")
            self.fs_combo.configure(values=("From image",), state="disabled")
            self.label_entry.configure(state="disabled")
            self.format_note_var.set("Formatting options are disabled in raw image mode; the ISO/image defines the disk layout and filesystem.")
            self.mode_note_var.set("ⓘ  Raw image mode: partition scheme and target system come from the image and cannot be changed.")
            self.start_btn.configure(text="START")
            self.detail_var.set("Raw mode is recommended for Linux, Proxmox and hybrid bootable ISOs.")
        elif windows_mode:
            self.scheme_var.set("MBR")
            self.target_var.set("UEFI")
            self.scheme_combo.configure(values=("MBR",), state="disabled")
            self.target_combo.configure(values=("UEFI",), state="disabled")
            self.fs_var.set("FAT32")
            self.fs_combo.configure(values=("FAT32",), state="disabled")
            self.label_entry.configure(state="normal")
            if self.label_var.get() in {"", "BOOTCRAFT"}:
                self.label_var.set("WINDOWS")
            self.format_note_var.set("Windows UEFI mode uses a FAT32 filesystem. The volume label is applied by BootCrafter.")
            self.mode_note_var.set("ⓘ  Windows installer mode validates the ISO before erasing the USB, then creates UEFI media.")
            self.start_btn.configure(text="START")
            self.detail_var.set("Select a Windows installer ISO and confirm the target USB drive.")
        else:
            self.scheme_var.set("GPT" if self.scheme_var.get().startswith("GPT") else "MBR")
            self.scheme_combo.configure(values=("GPT", "MBR"), state="readonly")
            self.target_var.set("Not applicable")
            self.target_combo.configure(values=("Not applicable",), state="disabled")
            if self.fs_var.get() not in {"FAT32", "exFAT", "NTFS", "ext4"}:
                self.fs_var.set("FAT32")
            self.fs_combo.configure(values=("FAT32", "exFAT", "NTFS", "ext4"), state="readonly")
            self.label_entry.configure(state="normal")
            if self.label_var.get() == "WINDOWS":
                self.label_var.set("BOOTCRAFT")
            self.format_note_var.set("Format-only mode recreates one partition using the selected scheme, filesystem and volume label.")
            self.mode_note_var.set("ⓘ  Non-bootable mode formats the selected USB. It does not install or modify boot files.")
            self.start_btn.configure(text="START")
            self.detail_var.set("Choose the partition scheme, filesystem and volume label, then press START.")

    def select_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Select boot image",
            filetypes=[
                ("Boot images", "*.iso *.img *.raw *.bin *.gz *.xz *.bz2 *.zip *.zst *.zstd"),
                ("ISO images", "*.iso"),
                ("Disk images", "*.img *.raw *.bin"),
                ("Compressed images", "*.gz *.xz *.bz2 *.zip *.zst *.zstd"),
                ("All files", "*"),
            ],
        )
        if path:
            self.image_var.set(path)
            self.image_ok_var.set("✓")
            size = os.path.getsize(path)
            self.detail_var.set(f"Image: {Path(path).name} • {human_bytes(size)}")
            self._set_log(f"Selected image: {path}")

    def _selected_device(self) -> Device | None:
        return self.device_by_display.get(self.device_var.get())

    def _helper_path(self) -> list[str]:
        installed = "/usr/lib/bootcrafter-linux/bootcrafter-helper"
        if os.path.isfile(installed) and os.access(installed, os.X_OK):
            return [installed]
        project_root = str(Path(__file__).resolve().parent.parent)
        env_bin = shutil.which("env") or "/usr/bin/env"
        python_bin = sys.executable
        return [env_bin, f"PYTHONPATH={project_root}", python_bin, "-m", "bootcrafter_linux.helper"]

    def _privileged_prefix(self) -> list[str] | None:
        if os.geteuid() == 0:
            return []
        pkexec = shutil.which("pkexec")
        if pkexec:
            return [pkexec]
        sudo = shutil.which("sudo")
        if sudo and sys.stdin.isatty():
            return [sudo]
        return None

    def _mode_key(self) -> str:
        mode = self.mode_var.get()
        if mode.startswith("Windows installer"):
            return "windows"
        if mode.startswith("Non bootable"):
            return "format"
        return "raw"

    def _preflight(self, device: Device, image: str) -> bool:
        mode_key = self._mode_key()
        filesystem = self.fs_var.get().lower() if mode_key == "format" else None
        missing = missing_commands(mode_key, filesystem)
        if mode_key == "raw" and image.lower().endswith((".zst", ".zstd")) and not command_path("zstd"):
            missing.append("zstd")
        if missing:
            unique = sorted(set(missing))
            messagebox.showerror(
                "Missing required tools",
                "Install these required commands/packages before continuing:\n\n" + "\n".join(unique),
            )
            return False
        if device.size < 32 * 1024 * 1024:
            messagebox.showerror("Invalid target", "The selected drive is too small.")
            return False
        return True

    def start_operation(self) -> None:
        if self.busy:
            return
        device = self._selected_device()
        if not device:
            messagebox.showerror("No USB drive", "Connect and select a removable USB drive first.")
            return
        mode_key = self._mode_key()
        format_only = mode_key == "format"
        windows_mode = mode_key == "windows"
        image = self.image_var.get().strip()
        if not format_only and (not image or not os.path.isfile(image)):
            messagebox.showerror("No image", "Select a valid ISO/IMG image first.")
            return
        if windows_mode and not image.lower().endswith(".iso"):
            messagebox.showerror("Windows ISO required", "Windows installer mode requires a .iso file.")
            return
        compressed = image.lower().endswith((".gz", ".xz", ".bz2", ".zip", ".zst", ".zstd"))
        if not format_only and not windows_mode and not compressed and os.path.getsize(image) > device.size:
            messagebox.showerror("Image too large", "The selected image is larger than the target drive.")
            return
        if not self._preflight(device, image):
            return

        action = "FORMAT" if format_only else ("CREATE WINDOWS INSTALLER" if windows_mode else "ERASE AND WRITE")
        identity_note = ""
        if not device.strong_hardware_id:
            identity_note = (
                "\n\nCAUTION: this USB does not expose a hardware serial/WWN. "
                "Confirm the model, capacity and /dev path carefully."
            )
        body = (
            f"{action} {device.path}?\n\n"
            f"Drive: {device.display}\n\n"
            "ALL DATA on this drive will be destroyed.\n"
            "BootCrafter blocks disks used by the running system and re-checks the selected device before writing."
            f"{identity_note}"
        )
        if not messagebox.askyesno("Confirm destructive operation", body, icon="warning"):
            return

        prefix = self._privileged_prefix()
        if prefix is None:
            messagebox.showerror(
                "Administrator authorization unavailable",
                "Install PolicyKit/pkexec, then try again.\n\nDebian/Ubuntu: sudo apt install policykit-1",
            )
            return
        helper = self._helper_path()
        identity = device.identity_token
        if format_only:
            cmd = prefix + helper + [
                "format",
                "--device",
                device.path,
                "--identity",
                identity,
                "--scheme",
                self.scheme_var.get().lower(),
                "--filesystem",
                self.fs_var.get().lower(),
                "--label",
                self.label_var.get(),
            ]
        elif windows_mode:
            cmd = prefix + helper + [
                "windows",
                "--image",
                image,
                "--device",
                device.path,
                "--identity",
                identity,
                "--label",
                self.label_var.get(),
            ]
        else:
            cmd = prefix + helper + [
                "write",
                "--image",
                image,
                "--device",
                device.path,
                "--identity",
                identity,
                "--verify",
                "yes" if self.verify_var.get() else "no",
            ]
        self._begin_process(cmd)

    def _set_controls_busy(self, busy: bool) -> None:
        self.busy = busy
        self.start_btn.configure(state="disabled" if busy else "normal")
        self.close_btn.configure(state="disabled" if busy else "normal")
        self.device_combo.configure(state="disabled" if busy else "readonly")
        self.mode_combo.configure(state="disabled" if busy else "readonly")
        self.refresh_btn.configure(state="disabled" if busy else "normal")
        self.hash_btn.configure(state="disabled" if busy else "normal")
        self.about_btn.configure(state="disabled" if busy else "normal")
        self.log_btn.configure(state="disabled" if busy else "normal")
        self.advanced_btn.configure(state="disabled" if busy else "normal")
        if busy:
            self.image_entry.configure(state="disabled")
            self.select_btn.configure(state="disabled")
            self.verify_check.configure(state="disabled")
            self.scheme_combo.configure(state="disabled")
            self.target_combo.configure(state="disabled")
            self.fs_combo.configure(state="disabled")
            self.label_entry.configure(state="disabled")
        else:
            self._mode_changed()

    def _begin_process(self, cmd: list[str]) -> None:
        self.last_operation_succeeded = False
        self._set_controls_busy(True)
        self.progress.stop()
        self.progress.configure(value=0, mode="determinate")
        self.percent_var.set("0%")
        self.status_var.set("Requesting administrator authorization…")
        self._set_log("Starting privileged disk operation.")

        def worker() -> None:
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                self.process = proc
                assert proc.stdout is not None
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        event = {"event": "log", "message": line}
                    self.worker_queue.put(("event", event))
                code = proc.wait()
                self.worker_queue.put(("exit", code))
            except Exception as exc:
                self.worker_queue.put(("fatal", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.worker_queue.get_nowait()
                if kind == "event":
                    self._handle_event(payload)
                elif kind == "exit":
                    self._finish_process(payload)
                elif kind == "fatal":
                    self._set_log(f"ERROR: {payload}")
                    self._finish_process(1)
                elif kind == "hash-progress":
                    done, total = payload["bytes"], payload["total"]
                    pct = done * 100.0 / total if total else 0
                    self.progress.configure(value=pct)
                    self.percent_var.set(f"{pct:.0f}%")
                    self.detail_var.set(f"Hashing: {pct:.1f}% • {human_bytes(done)} / {human_bytes(total)}")
                elif kind == "hash-done":
                    self._set_controls_busy(False)
                    self.status_var.set("SHA-256 calculated")
                    self._set_log(f"Image SHA-256: {payload}")
                    messagebox.showinfo("SHA-256", payload)
                elif kind == "hash-error":
                    self._set_controls_busy(False)
                    self.status_var.set("Hash failed")
                    self._set_log(f"ERROR: {payload}")
                    messagebox.showerror("SHA-256", payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _handle_event(self, event: dict) -> None:
        kind = event.get("event")
        if kind == "log":
            self._set_log(str(event.get("message", "")))
        elif kind == "stage":
            msg = str(event.get("message") or event.get("name") or "Working")
            self.status_var.set(msg)
            self._set_log(msg)
            if event.get("name") in {"flushing", "partitioning", "formatting", "mounting", "splitting", "validating"}:
                self.progress.stop()
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
                self.percent_var.set("…")
        elif kind == "progress":
            if str(self.progress.cget("mode")) != "determinate":
                self.progress.stop()
                self.progress.configure(mode="determinate")
            done = int(event.get("bytes") or 0)
            total = event.get("total")
            speed = int(event.get("speed") or 0)
            stage = str(event.get("stage") or "working").capitalize()
            if total:
                percent = min(100.0, done * 100.0 / int(total))
                self.progress.configure(value=percent)
                self.percent_var.set(f"{percent:.0f}%")
                self.detail_var.set(
                    f"{stage}: {percent:.1f}% • {human_bytes(done)} / {human_bytes(int(total))} • {human_bytes(speed)}/s"
                )
            else:
                self.detail_var.set(f"{stage}: {human_bytes(done)} • {human_bytes(speed)}/s")
        elif kind == "checksum":
            self._set_log(f"Written SHA-256: {event.get('value')}")
        elif kind == "verified":
            self._set_log("Verification passed: bytes read back from USB match the image.")
        elif kind == "done":
            self.last_operation_succeeded = True
            self.progress.stop()
            self.progress.configure(mode="determinate", value=100)
            self.percent_var.set("100%")
            self.status_var.set("Operation completed successfully")
            self.detail_var.set("The USB drive is ready. Safely eject it before removal.")
            self._set_log("Operation completed successfully.")
        elif kind == "error":
            self.last_operation_succeeded = False
            self.progress.stop()
            self.percent_var.set("0%")
            self.status_var.set("Operation failed")
            self.detail_var.set(str(event.get("message") or "Unknown error"))
            self._set_log(f"ERROR: {event.get('message')}")

    def _finish_process(self, code: int) -> None:
        self.process = None
        self._set_controls_busy(False)
        if code != 0 or not self.last_operation_succeeded:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            self.percent_var.set("0%")
            self.status_var.set("Operation failed or authorization was cancelled")
            messagebox.showerror(APP_NAME, "The operation did not complete. Check the log for details.")
        else:
            messagebox.showinfo(APP_NAME, "Operation completed successfully.")
            self.after(800, lambda: self.refresh_devices(log=True))

    def calculate_hash(self) -> None:
        image = self.image_var.get().strip()
        if not image or not os.path.isfile(image):
            messagebox.showerror("No image", "Select an image first.")
            return
        if self.busy:
            return
        self._set_controls_busy(True)
        self.status_var.set("Calculating SHA-256…")
        self.progress.configure(mode="determinate", value=0)
        self.percent_var.set("0%")

        def worker() -> None:
            try:
                total = os.path.getsize(image)
                done = 0
                import hashlib

                h = hashlib.sha256()
                with open(image, "rb") as f:
                    while True:
                        chunk = f.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        h.update(chunk)
                        done += len(chunk)
                        self.worker_queue.put(("hash-progress", {"bytes": done, "total": total}))
                self.worker_queue.put(("hash-done", h.hexdigest()))
            except Exception as exc:
                self.worker_queue.put(("hash-error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_close(self) -> None:
        if self.busy and self.process is not None:
            messagebox.showwarning(
                "Operation in progress",
                "A disk operation is still running. Keep BootCrafter open until it finishes.\n\nDo not unplug the USB drive.",
            )
            return
        self.destroy()

    def show_about(self) -> None:
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME} {__version__}\n\n"
            "A Linux-native bootable USB creator focused on reliable raw image writing, verification, "
            "Windows UEFI installer creation, and USB format recovery.\n\n"
            "License: GNU GPLv3\n"
            "Safety: disks used by the running system/live media/swap are blocked and the selected device identity is rechecked before erasing.",
        )


def main() -> int:
    app = BootCrafterApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
