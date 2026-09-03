#!/usr/bin/env python3
from __future__ import annotations

from unittest.mock import patch

from bootcrafter_linux.app import BootCrafterApp, DEVICE_PLACEHOLDER
from bootcrafter_linux.devices import Device


def assert_visible(app, widget) -> None:
    app.update_idletasks()
    assert widget.winfo_ismapped(), f"{widget} is not mapped"
    wx = widget.winfo_rootx()
    wy = widget.winfo_rooty()
    ww = widget.winfo_width()
    wh = widget.winfo_height()
    ax = app.winfo_rootx()
    ay = app.winfo_rooty()
    aw = app.winfo_width()
    ah = app.winfo_height()
    assert wx >= ax, (wx, ax)
    assert wy >= ay, (wy, ay)
    assert wx + ww <= ax + aw + 2, (wx, ww, ax, aw)
    assert wy + wh <= ay + ah + 2, (wy, wh, ay, ah)


dev_a = Device("/dev/sdb", 32 * 1024**3, "Flash A", "Vendor", "usb", True, True, False, False, "SER-A")
dev_b = Device("/dev/sdc", 64 * 1024**3, "Flash B", "Vendor", "usb", True, True, False, False, "SER-B")

with patch("bootcrafter_linux.app.list_devices", return_value=[dev_a, dev_b]) as list_mock:
    app = BootCrafterApp()
    app.geometry("760x560")
    app.update()
    app.refresh_devices(log=False)

    # The fixed destructive-action footer must remain visible on a small desktop.
    assert_visible(app, app.start_btn)
    assert_visible(app, app.close_btn)
    assert app.start_btn.cget("text") == "START"

    # Raw mode: layout metadata comes from the image and must not pretend to be editable.
    assert str(app.scheme_combo.cget("state")) == "disabled"
    assert str(app.target_combo.cget("state")) == "disabled"
    assert str(app.fs_combo.cget("state")) == "disabled"
    assert str(app.label_entry.cget("state")) == "disabled"
    assert "come from the image" in app.mode_note_var.get()
    assert "disabled in raw image mode" in app.format_note_var.get()

    # Safety: discovery must not silently pick a destructive target.
    assert app.device_var.get() == DEVICE_PLACEHOLDER, app.device_var.get()
    app.device_var.set(dev_a.display)
    app._device_changed()
    assert app._selected_device() == dev_a

    # If the selected drive disappears, never auto-switch to another drive.
    list_mock.return_value = [dev_b]
    app.refresh_devices(log=False)
    assert app.device_var.get() == DEVICE_PLACEHOLDER, app.device_var.get()
    assert app._selected_device() is None

    # Windows mode: fixed MBR/UEFI/FAT32, editable volume label.
    app.mode_var.set("Windows installer ISO (UEFI)")
    app._mode_changed()
    app.update()
    assert_visible(app, app.start_btn)
    assert app.scheme_var.get() == "MBR"
    assert app.target_var.get() == "UEFI"
    assert app.fs_var.get() == "FAT32"
    assert str(app.label_entry.cget("state")) == "normal"
    assert str(app.scheme_combo.cget("state")) == "disabled"
    assert str(app.fs_combo.cget("state")) == "disabled"

    # Format mode: real backend-controlled format fields are editable.
    app.mode_var.set("Non bootable / Format only")
    app._mode_changed()
    app.update()
    assert_visible(app, app.start_btn)
    assert str(app.scheme_combo.cget("state")) == "readonly"
    assert str(app.fs_combo.cget("state")) == "readonly"
    assert str(app.label_entry.cget("state")) == "normal"
    # Unsupported cosmetic/extra formatting controls remain intentionally disabled.
    assert str(app.cluster_combo.cget("state")) == "disabled"
    assert str(app.badblocks_check.cget("state")) == "disabled"

    # Compact advanced/log panels must toggle without affecting backend state.
    app._toggle_advanced()
    app.update()
    assert app.advanced_frame.winfo_ismapped()
    app._toggle_advanced()
    app._toggle_log()
    app.update()
    assert app.log_panel.winfo_ismapped()
    app._toggle_log()

    # Busy state freezes every input that could diverge from the submitted helper command.
    app._set_controls_busy(True)
    assert str(app.image_entry.cget("state")) == "disabled"
    assert str(app.select_btn.cget("state")) == "disabled"
    assert str(app.refresh_btn.cget("state")) == "disabled"
    assert str(app.label_entry.cget("state")) == "disabled"
    assert str(app.close_btn.cget("state")) == "disabled"
    app._set_controls_busy(False)

    app.destroy()

print("UI smoke: Windows-style compact layout, fixed START/CLOSE footer, mode-aware real controls, explicit target selection and busy-state lock verified")
