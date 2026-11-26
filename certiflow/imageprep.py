"""Turn a scanned stamp / signature (white paper background) into a clean
transparent PNG: ink keeps its colour, paper becomes transparent, specks and
scanner edge lines are removed, and the result is cropped to the ink."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def remove_background(src: Path, out: Path, *, min_component_px: int | None = None, pad: int = 4,
                      ink_floor: float = 0.10) -> dict:
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(np.float32)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    sat = a.max(axis=2) - a.min(axis=2)

    paper = float(np.percentile(lum, 90))                 # background brightness of this scan
    ink = float(np.percentile(lum[lum < paper - 40], 10)) if (lum < paper - 40).any() else 0.0
    alpha = np.clip((paper - 8 - lum) / max(1.0, paper - 8 - ink), 0, 1)
    # coloured ink (blue stamps) counts as ink even where it is fairly light
    alpha = np.maximum(alpha, np.clip((sat - 25) / 90, 0, 1))
    alpha[alpha < ink_floor] = 0

    # drop specks and thin scanner lines: keep components that are large enough
    mask = (alpha > 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    h, w = mask.shape
    min_px = min_component_px or max(12, int(h * w * 0.00004))
    keep = np.zeros(n, bool)
    ink_sat = sat[mask > 0]
    coloured = ink_sat.size and float(np.median(ink_sat)) > 60      # e.g. a blue stamp
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        thin_edge_line = (bw <= 4 and bh > h * 0.2) or (bh <= 4 and bw > w * 0.2 and (y < 6 or y > h - 10))
        grey_on_colour = coloured and float(sat[lab == i].mean()) < 35   # scanner lines, dust
        keep[i] = area >= min_px and not thin_edge_line and not grey_on_colour
    alpha = np.where(keep[lab], alpha, 0)

    # un-mix the paper: recover the ink colour where alpha < 1
    al = np.maximum(alpha, 1e-3)[..., None]
    rgb = np.clip((a - (1 - al) * 255.0) / al, 0, 255)
    rgba = np.dstack([rgb, alpha * 255]).astype(np.uint8)

    ys, xs = np.nonzero(alpha > 0)
    if not len(xs):
        raise ValueError(f"{src}: no ink found")
    x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + pad + 1)
    y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + pad + 1)
    Image.fromarray(rgba[y0:y1, x0:x1], "RGBA").save(out, optimize=True)
    return {"crop": (int(x0), int(y0), int(x1), int(y1)), "size": (int(x1 - x0), int(y1 - y0)), "source_size": (w, h)}
