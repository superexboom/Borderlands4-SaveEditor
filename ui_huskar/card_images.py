"""Item card image support for QML: tinted textures and the card fonts.

The game tints grey/white card textures per rarity with
``filter: coh-color-matrix(...)`` - a per-channel RGB multiply. QML has no such
filter, so ``image://cardtint/<r>,<g>,<b>/<relative path>`` returns the texture
multiplied by those factors (alpha untouched); ``?clip=x,y,w,h`` crops it (Qt
does not apply ``sourceClipRect`` to provider images, so 9-slice pieces pass
their rect here). Paths are relative to the resource root and may not leave it.

Fonts: the game's own faces (Industry, MFDianHei) are commercial and not
shipped. When the player drops the extracted font files into a ``card_fonts``
folder (next to the executable or in the user config dir) they are loaded;
otherwise the card uses close system fonts.
"""

from __future__ import annotations

import os
import sys
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QSize, QStandardPaths
from PyQt6.QtGui import QFontDatabase, QImage
from PyQt6.QtQuick import QQuickImageProvider

from core import resource_loader

PROVIDER_ID = "cardtint"
_CACHE_LIMIT = 256


def _resource_root() -> Path:
    return resource_loader.get_resource_path("").resolve()


def tint_image(image: QImage, factors: tuple[float, float, float]) -> QImage:
    """RGB * factors with alpha kept (the diagonal of a coh-color-matrix)."""
    source = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = source.width(), source.height()
    if width <= 0 or height <= 0:
        return source
    stride = source.bytesPerLine()
    buffer = np.frombuffer(source.constBits().asstring(source.sizeInBytes()), dtype=np.uint8)
    pixels = buffer.reshape(height, stride)[:, :width * 4].reshape(height, width, 4).astype(np.float32)
    pixels[..., :3] *= np.asarray(factors, dtype=np.float32)
    out = np.ascontiguousarray(np.clip(pixels + 0.5, 0, 255).astype(np.uint8))
    return QImage(out.data, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()


class CardTintProvider(QQuickImageProvider):
    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._cache: OrderedDict[str, QImage] = OrderedDict()
        self._root = _resource_root()

    def _resolve(self, rel: str) -> Path | None:
        path = (self._root / rel).resolve()
        try:
            path.relative_to(self._root)
        except ValueError:
            return None
        return path if path.is_file() else None

    def requestImage(self, image_id: str, requested_size: QSize):  # noqa: N802 - Qt API
        image = self._cache.get(image_id)
        if image is None:
            image = self._build(image_id)
            self._cache[image_id] = image
            if len(self._cache) > _CACHE_LIMIT:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(image_id)
        return image, image.size()

    def _build(self, image_id: str) -> QImage:
        base, _, query = image_id.partition("?")
        if query.startswith("clip="):  # 9-slice piece: crop the (cached) tinted texture
            full = self.requestImage(base, QSize())[0]
            try:
                x, y, w, h = (int(part) for part in query[5:].split(","))
            except ValueError:
                return full
            return full.copy(x, y, w, h)
        factors_text, _, rel = base.partition("/")
        path = self._resolve(rel)
        if path is None:
            return QImage()
        try:
            factors = tuple(float(part) for part in factors_text.split(","))[:3]
        except ValueError:
            factors = (1.0, 1.0, 1.0)
        image = QImage(str(path))
        return tint_image(image, factors) if len(factors) == 3 and not image.isNull() else image


# --------------------------------------------------------------------------- #
# fonts
# --------------------------------------------------------------------------- #
# Latin / CJK fallbacks close to the game's Industry and MFDianHei faces.
SYSTEM_LATIN = "Bahnschrift"
SYSTEM_CJK = "Microsoft YaHei UI"


def font_dirs() -> list[Path]:
    dirs = []
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else _resource_root()
    dirs.append(exe_dir / "card_fonts")
    config = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    if config:
        dirs.append(Path(config) / "card_fonts")
    if os.environ.get("BL4_CARD_FONTS"):
        dirs.insert(0, Path(os.environ["BL4_CARD_FONTS"]))
    return dirs


def load_card_fonts() -> dict[str, str]:
    """Register the game's card fonts when present; family names for the card."""
    families = {"demi": SYSTEM_LATIN, "medium": SYSTEM_LATIN, "italic": SYSTEM_LATIN,
                "cjk_bold": SYSTEM_CJK, "cjk_medium": SYSTEM_CJK, "game_fonts": ""}
    wanted = {
        "demi": ("Industry-Demi.ttf",), "medium": ("Industry-Medium.ttf",), "italic": ("Industry-MediumItalic.ttf",),
        "cjk_bold": ("MFDianHei-Bold.ttf",), "cjk_medium": ("MFDianHei-Medium.ttf",),
    }
    for folder in font_dirs():
        if not folder.is_dir():
            continue
        files = {path.name.casefold(): path for path in folder.rglob("*.ttf")}
        for role, names in wanted.items():
            for name in names:
                path = files.get(name.casefold())
                if path is None:
                    continue
                font_id = QFontDatabase.addApplicationFont(str(path))
                loaded = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
                if loaded:
                    # One file registers several names; the one equal to the file stem
                    # ("Industry-Demi") is unique per weight, otherwise the first one is.
                    families[role] = next((name for name in loaded if name == path.stem), loaded[0])
                    families["game_fonts"] = str(folder)
        if families["game_fonts"]:
            break
    return families
