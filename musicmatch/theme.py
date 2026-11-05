"""Visual design: light, Apple-inspired palette plus Poppins.

Only flat fills, 1px borders and corner radii are used, since that is what
CustomTkinter can draw.
"""
import ctypes

import customtkinter as ctk

from .paths import ASSETS

# ---- palette -------------------------------------------------------------
BG = "#F2F2F7"          # window (iOS system grouped background)
CARD = "#FFFFFF"
SEP = "#E5E5EA"         # hairlines
FIELD = "#F2F2F7"       # inputs inside cards
TRACK = "#E9E9EB"       # progress / segmented / switch track
TEXT = "#1C1C1E"
MUTED = "#8E8E93"
ACCENT = "#007AFF"
ACCENT_HOVER = "#0A6AE0"
TINT = "#E5F0FF"        # tinted (secondary) buttons and banner
TINT_HOVER = "#D2E5FF"
GREEN = "#34C759"
GREEN_TEXT = "#23883E"
RED = "#FF3B30"
RED_TEXT = "#D12B21"
RED_TINT = "#FFEAE8"
RED_TINT_HOVER = "#FFD9D6"

# ---- fonts ---------------------------------------------------------------
_FAMILIES = {"regular": "Poppins", "medium": "Poppins Medium", "semibold": "Poppins SemiBold"}
_FALLBACK = "Segoe UI"
_have_poppins = False
_cache = {}


def load_fonts() -> bool:
    """Register the bundled Poppins TTFs for this process only (no install)."""
    global _have_poppins
    added = 0
    try:
        for ttf in sorted((ASSETS / "fonts").glob("Poppins-*.ttf")):
            added += ctypes.windll.gdi32.AddFontResourceExW(str(ttf), 0x10, 0)  # FR_PRIVATE
    except Exception:
        added = 0
    _have_poppins = added >= 3
    return _have_poppins


def font(size: int = 12, weight: str = "regular") -> ctk.CTkFont:
    key = (size, weight)
    if key not in _cache:
        if _have_poppins:
            _cache[key] = ctk.CTkFont(family=_FAMILIES[weight], size=size)
        else:
            _cache[key] = ctk.CTkFont(family=_FALLBACK, size=size,
                                      weight="bold" if weight == "semibold" else "normal")
    return _cache[key]


# ---- widget helpers ------------------------------------------------------
def primary_button(master, text, command, width=110, height=34, **kw):
    return ctk.CTkButton(master, text=text, command=command, width=width, height=height,
                         corner_radius=height // 2, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                         text_color="#FFFFFF", text_color_disabled="#BFD9FF",
                         font=font(12, "semibold"), **kw)


def tinted_button(master, text, command, width=90, height=34, danger=False, **kw):
    return ctk.CTkButton(master, text=text, command=command, width=width, height=height,
                         corner_radius=height // 2,
                         fg_color=RED_TINT if danger else TINT,
                         hover_color=RED_TINT_HOVER if danger else TINT_HOVER,
                         text_color=RED_TEXT if danger else ACCENT, text_color_disabled=MUTED,
                         font=font(12, "medium"), **kw)


def circle_button(master, text, command, size=26):
    return ctk.CTkButton(master, text=text, command=command, width=size, height=size,
                         corner_radius=size // 2, fg_color=TRACK, hover_color="#DCDCE1",
                         text_color=MUTED, font=font(12, "medium"))


def segmented(master, values, command=None, width=110, height=30):
    return ctk.CTkSegmentedButton(
        master, values=values, command=command, width=width, height=height, corner_radius=9,
        border_width=2, fg_color=TRACK, selected_color=CARD, selected_hover_color=CARD,
        unselected_color=TRACK, unselected_hover_color="#DEDEE3", text_color=TEXT,
        text_color_disabled=MUTED, font=font(12, "medium"))


def option_menu(master, values, command, width=80, height=30):
    return ctk.CTkOptionMenu(
        master, values=values, command=command, width=width, height=height, corner_radius=10,
        fg_color=FIELD, button_color=FIELD, button_hover_color=SEP, text_color=TEXT,
        dropdown_fg_color=CARD, dropdown_text_color=TEXT, dropdown_hover_color=FIELD,
        font=font(12), dropdown_font=font(12))


def entry(master, width=64, height=30, placeholder="", on_card=True, **kw):
    return ctk.CTkEntry(master, width=width, height=height, corner_radius=10,
                        fg_color=FIELD if on_card else CARD,
                        border_width=0 if on_card else 1, border_color=SEP,
                        text_color=TEXT, placeholder_text=placeholder,
                        placeholder_text_color=MUTED, font=font(12), **kw)


def switch(master, text):
    """iOS-style switch: the whole track turns green when on."""
    off = "#D9D9DE"
    sw = ctk.CTkSwitch(master, text=text, switch_width=40, switch_height=22, border_width=0,
                       fg_color=off, progress_color=GREEN, button_color="#FFFFFF",
                       button_hover_color="#FFFFFF", text_color=TEXT, font=font(12))
    sw.configure(command=lambda: sw.configure(fg_color=GREEN if sw.get() else off))
    return sw


def label(master, text="", size=12, weight="regular", color=TEXT, **kw):
    return ctk.CTkLabel(master, text=text, font=font(size, weight), text_color=color, **kw)


def rounded(img, radius: int):
    """Round an image's corners (anti-aliased) by giving it an alpha mask."""
    from PIL import Image, ImageDraw
    w, h = img.size
    k = 4
    mask = Image.new("L", (w * k, h * k), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius * k, fill=255)
    img = img.convert("RGBA")
    img.putalpha(mask.resize((w, h), Image.LANCZOS))
    return img
