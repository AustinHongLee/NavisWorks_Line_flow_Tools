# -*- coding: utf-8 -*-
"""色彩管控系統 — 全體 Token + 模組私人 Token + 版面常數。

Modern Industrial Dashboard 風格。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.release_update import CURRENT_VERSION


# ============================================================
#  全體 Token（母 GUI 統一管控）
# ============================================================

@dataclass
class GlobalTokens:
    # ── Background layers ──
    bg_app: str = "#F1F5F9"
    bg_surface: str = "#F8FAFC"
    bg_card: str = "#FFFFFF"
    bg_input: str = "#F9FAFB"
    bg_dark: str = "#0F172A"
    bg_dark_border: str = "#1E293B"

    # ── Sidebar ──
    sidebar_bg: str = "#1E293B"
    sidebar_text: str = "#94A3B8"
    sidebar_text_hover: str = "#CBD5E1"
    sidebar_text_active: str = "#FFFFFF"
    sidebar_item_hover: str = "#334155"
    sidebar_item_active: str = "#2563EB"
    sidebar_divider: str = "#334155"
    sidebar_title: str = "#F1F5F9"

    # ── Text hierarchy ──
    text_heading: str = "#0F172A"
    text_primary: str = "#1E293B"
    text_secondary: str = "#475569"
    text_tertiary: str = "#64748B"
    text_muted: str = "#64748B"
    text_placeholder: str = "#94A3B8"
    text_on_dark: str = "#E2E8F0"

    # ── Borders ──
    border: str = "#E2E8F0"
    border_input: str = "#D1D5DB"
    border_hover: str = "#94A3B8"
    border_card_hover: str = "#CBD5E1"

    # ── Semantic colors ──
    danger: str = "#DC2626"
    warning: str = "#D97706"
    success: str = "#059669"

    # ── Radius ──
    radius_sm: str = "6px"
    radius: str = "8px"
    radius_lg: str = "10px"
    radius_xl: str = "12px"
    radius_pill: str = "20px"

    # ── Typography ──
    font_family: str = (
        '"Segoe UI", "Microsoft JhengHei UI", system-ui, sans-serif'
    )
    font_mono: str = (
        '"Cascadia Code", Consolas, "Microsoft JhengHei UI", monospace'
    )
    font_size_xs: str = "11px"
    font_size_sm: str = "12px"
    font_size_base: str = "13px"
    font_size_lg: str = "14px"
    font_size_xl: str = "16px"
    font_size_2xl: str = "18px"

    # ── Sidebar dimension ──
    sidebar_width: int = 220


# ============================================================
#  模組私人 Token
# ============================================================

@dataclass
class ModuleTokens:
    # Primary (blue)
    primary: str = "#2563EB"
    primary_hover: str = "#1D4ED8"
    primary_light: str = "#3B82F6"
    primary_bg: str = "#EFF6FF"
    primary_bg_hover: str = "#DBEAFE"
    primary_border: str = "#93C5FD"
    primary_selection: str = "#BFDBFE"
    primary_dark: str = "#1E40AF"
    primary_gradient_end: str = "#60A5FA"

    # Success (green)
    success: str = "#059669"
    success_light: str = "#10B981"
    success_hover: str = "#047857"
    success_bg: str = "#DCFCE7"
    success_text: str = "#166534"

    # Accent (purple)
    accent: str = "#7C3AED"
    accent_hover: str = "#6D28D9"
    accent_bg: str = "#F5F3FF"
    accent_border: str = "#C4B5FD"

    # Error badge
    error_bg: str = "#FEE2E2"
    error_text: str = "#991B1B"

    # Warning badge
    warn_bg: str = "#FFF7ED"
    warn_text: str = "#C2410C"
    warn_border: str = "#FDBA74"
    warn_bg_hover: str = "#FFEDD5"

    # Neutral badge
    neutral_bg: str = "#F1F5F9"


# ============================================================
#  組合主題
# ============================================================

@dataclass
class Theme:
    g: GlobalTokens = field(default_factory=GlobalTokens)
    m: ModuleTokens = field(default_factory=ModuleTokens)


DEFAULT_THEME = Theme()

# ── 應用程式常數 ──
APP_TITLE = f"管線流程工具 v{CURRENT_VERSION.split('.', 1)[0]}"
WINDOW_W, WINDOW_H = 1200, 900
SIDEBAR_W = DEFAULT_THEME.g.sidebar_width

# ── 快捷色彩常數 ──
C_PRIMARY = DEFAULT_THEME.m.primary
C_SUCCESS = DEFAULT_THEME.m.success
C_ERROR = DEFAULT_THEME.g.danger
C_NOTE = DEFAULT_THEME.m.accent
C_WARN = DEFAULT_THEME.g.warning
