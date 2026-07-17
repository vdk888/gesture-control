"""Screenshot capture via Core Graphics (CGDisplayCreateImage).

Pure PyObjC -- no subprocess, no screencapture CLI.
Saves PNG to ~/.cache/gesture-control/screenshots/voice_{timestamp}.png.
"""

import logging
import os
from datetime import datetime
from pathlib import Path

log = logging.getLogger("gesture-control.voice.screenshot")


def capture_screenshot() -> str:
    """
    Capture the primary display and save as PNG.

    Uses Quartz CGDisplayCreateImage to grab the main display, then
    AppKit NSBitmapImageRep to encode as PNG bytes and write to disk.

    Returns:
        Absolute path to the saved PNG file.

    Raises:
        RuntimeError: if the display capture or PNG encode fails.
    """
    import Quartz
    import AppKit

    # Grab the main display
    display_id = Quartz.CGMainDisplayID()
    cg_image = Quartz.CGDisplayCreateImage(display_id)
    if cg_image is None:
        raise RuntimeError("CGDisplayCreateImage returned None -- cannot capture display")

    # Encode as PNG via NSBitmapImageRep
    rep = AppKit.NSBitmapImageRep.alloc().initWithCGImage_(cg_image)
    if rep is None:
        raise RuntimeError("NSBitmapImageRep.initWithCGImage_ returned None")

    png_data = rep.representationUsingType_properties_(
        AppKit.NSPNGFileType, None
    )
    if png_data is None:
        raise RuntimeError("representationUsingType_properties_ returned None for PNG")

    # Write to disk
    out_dir = Path(os.path.expanduser("~/.cache/gesture-control/screenshots"))
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"voice_{ts}.png"

    success = png_data.writeToFile_atomically_(str(path), True)
    if not success:
        raise RuntimeError(f"Failed to write screenshot to {path}")

    log.info("Screenshot saved: %s (%.0f KB)", path.name, os.path.getsize(path) / 1024)
    return str(path)
