# -*- coding: utf-8 -*-
"""從 Theme tokens 生成完整 Qt stylesheet。

Modern Industrial Dashboard 風格。
所有色值/尺寸均來自 Theme dataclass，不硬編碼。
"""
from __future__ import annotations

from gui.theme import Theme, DEFAULT_THEME


def build_stylesheet(theme: Theme | None = None) -> str:
    t = theme or DEFAULT_THEME
    g = t.g
    m = t.m

    return f"""
/* ═══════════════  GLOBAL  ═══════════════ */
* {{ font-family: {g.font_family}; font-size: {g.font_size_base}; }}
QMainWindow {{ background: {g.bg_app}; }}

/* ═══ Scrollbar ═══ */
QScrollBar:vertical {{
    background: transparent; width: 6px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {g.border_input}; border-radius: 3px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {g.border_hover}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 6px; margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {g.border_input}; border-radius: 3px; min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {g.border_hover}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ═══════════════  SIDEBAR  ═══════════════ */
QFrame#sidebar {{
    background: {g.sidebar_bg}; border: none;
    border-right: 1px solid {g.sidebar_divider};
}}
QLabel#sidebarTitle {{
    color: {g.sidebar_title}; font-size: {g.font_size_xl}; font-weight: 700;
}}
QLabel#sidebarVersion {{
    color: {g.sidebar_text}; font-size: {g.font_size_xs};
}}
QLabel#sidebarSection {{
    color: {g.sidebar_text}; font-size: {g.font_size_xs};
    font-weight: 600;
}}

/* Sidebar nav */
QPushButton[class="sidebar-nav"] {{
    background: transparent; color: {g.sidebar_text}; border: none;
    border-radius: {g.radius}; padding: 10px 14px;
    font-size: {g.font_size_base}; font-weight: 500; text-align: left;
}}
QPushButton[class="sidebar-nav"]:hover {{
    background: {g.sidebar_item_hover}; color: {g.sidebar_text_hover};
}}
QPushButton[class="sidebar-nav"]:checked {{
    background: {g.sidebar_item_active}; color: {g.sidebar_text_active};
    font-weight: 600;
}}

/* Sidebar actions */
QPushButton#sidebarRunAll {{
    background: {m.primary}; color: white; border: none;
    border-radius: {g.radius}; padding: 10px 14px;
    font-size: {g.font_size_base}; font-weight: 600;
}}
QPushButton#sidebarRunAll:hover {{ background: {m.primary_hover}; }}
QPushButton#sidebarRunAll:disabled {{
    background: {g.sidebar_item_hover}; color: {g.sidebar_text};
}}
QPushButton#sidebarCleanup {{
    background: transparent; color: {g.sidebar_text};
    border: 1px solid {g.sidebar_divider}; border-radius: {g.radius};
    padding: 8px 14px; font-size: {g.font_size_sm};
}}
QPushButton#sidebarCleanup:hover {{
    background: {g.sidebar_item_hover}; color: {g.sidebar_text_hover};
}}
QCheckBox#sidebarCheck {{
    color: {g.sidebar_text}; font-size: {g.font_size_xs}; spacing: 6px;
}}
QCheckBox#sidebarCheck::indicator {{
    width: 14px; height: 14px; border-radius: 3px;
    border: 1px solid {g.sidebar_divider}; background: transparent;
}}
QCheckBox#sidebarCheck::indicator:checked {{
    background: {m.primary}; border-color: {m.primary};
}}

/* Sidebar status badges */
QLabel[class="sb-ok"]      {{ color: {m.success_light}; font-size: {g.font_size_xs}; padding: 2px 0; }}
QLabel[class="sb-err"]     {{ color: {g.danger};        font-size: {g.font_size_xs}; padding: 2px 0; }}
QLabel[class="sb-neutral"] {{ color: {g.sidebar_text};  font-size: {g.font_size_xs}; padding: 2px 0; }}
QLabel[class="sb-ready"]   {{ color: {m.primary_light}; font-size: {g.font_size_sm}; font-weight: 600; padding: 4px 0; }}

QFrame[class="sidebar-divider"] {{
    background: {g.sidebar_divider}; max-height: 1px; min-height: 1px;
}}

/* ═══════════════  STEPPER  ═══════════════ */
QWidget[class="stepper-bar"] {{
    background: {g.bg_card}; border: 1px solid {g.border};
    border-radius: {g.radius_xl};
}}
QPushButton[step-state="active"] {{
    background: {m.primary}; color: white; border: none;
    border-radius: {g.radius_pill}; padding: 8px 20px;
    font-size: {g.font_size_sm}; font-weight: 700;
}}
QPushButton[step-state="active"]:hover {{ background: {m.primary_hover}; }}
QPushButton[step-state="completed"] {{
    background: {m.success_bg}; color: {m.success_text}; border: none;
    border-radius: {g.radius_pill}; padding: 8px 20px;
    font-size: {g.font_size_sm}; font-weight: 600;
}}
QPushButton[step-state="upcoming"] {{
    background: {g.bg_surface}; color: {g.text_muted};
    border: 1px solid {g.border}; border-radius: {g.radius_pill};
    padding: 8px 20px; font-size: {g.font_size_sm}; font-weight: 500;
}}
QPushButton[step-state="upcoming"]:hover {{
    background: {g.bg_app}; color: {g.text_secondary};
}}
QFrame[class="stepper-conn"]            {{ background: {g.border}; }}
QFrame[class="stepper-conn"][state="done"] {{ background: {m.success}; }}

/* ═══════════════  CARDS / PANELS  ═══════════════ */
QFrame[class="card"], QFrame[class="panel"] {{
    background: {g.bg_card}; border: 1px solid {g.border};
    border-radius: {g.radius_xl};
}}
QFrame[class="card"]:hover, QFrame[class="panel"]:hover {{
    border-color: {g.border_card_hover};
}}
QFrame[class="panel-blue"] {{
    background: {g.bg_card}; border: 1px solid {g.border};
    border-radius: {g.radius_xl}; border-left: 3px solid {m.primary};
}}
QFrame[class="panel-blue"]:hover {{
    border-color: {g.border_card_hover}; border-left-color: {m.primary};
}}
QFrame[class="panel-green"] {{
    background: {g.bg_card}; border: 1px solid {g.border};
    border-radius: {g.radius_xl}; border-left: 3px solid {m.success};
}}
QFrame[class="panel-green"]:hover {{
    border-color: {g.border_card_hover}; border-left-color: {m.success};
}}
QFrame[class="panel-status"] {{
    background: {g.bg_card}; border: 1px solid {g.border};
    border-radius: {g.radius_xl};
}}

/* ═══════════════  TYPOGRAPHY (role) ═══════════════ */
QLabel[role="card-title"] {{
    font-size: {g.font_size_xl}; font-weight: 600; color: {g.text_heading};
}}
QLabel[role="section-header"] {{
    font-size: {g.font_size_lg}; font-weight: 600; color: {g.text_heading};
}}
QLabel[role="section-desc"] {{
    font-size: {g.font_size_sm}; color: {g.text_muted};
}}
QLabel[role="field-label"] {{
    font-size: {g.font_size_sm}; font-weight: 600; color: {g.text_tertiary};
}}
QLabel[role="note"] {{
    font-size: {g.font_size_xs}; color: {g.text_muted};
}}

/* ═══════════════  INPUTS  ═══════════════ */
QLineEdit, QComboBox {{
    background: {g.bg_input}; border: 1.5px solid {g.border_input};
    border-radius: {g.radius}; padding: 8px 12px;
    font-size: {g.font_size_base}; color: {g.text_primary};
    selection-background-color: {m.primary_selection};
}}
QLineEdit:hover, QComboBox:hover {{
    border-color: {g.border_hover}; background: {g.bg_card};
}}
QLineEdit:focus, QComboBox:focus, QComboBox:on {{
    border-color: {m.primary}; background: {g.bg_card};
}}
QLineEdit:disabled, QComboBox:disabled {{
    background: {g.bg_app}; color: {g.text_muted}; border-color: {g.border};
}}
QLineEdit:read-only {{ background: {g.bg_app}; color: {g.text_muted}; }}
QLineEdit::placeholder {{ color: {g.text_placeholder}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent; border-right: 5px solid transparent;
    border-top: 6px solid {g.text_muted};
}}
QComboBox QAbstractItemView {{
    background: {g.bg_card}; color: {g.text_primary};
    border: 1px solid {g.border};
    border-radius: {g.radius}; padding: 4px;
    selection-background-color: {m.primary_bg};
    selection-color: {m.primary_dark};
}}

/* ═══════════════  BUTTONS (3-tier)  ═══════════════ */
/* Secondary (default) */
QPushButton {{
    background: {g.bg_card}; border: 1.5px solid {g.border_input};
    border-radius: {g.radius}; padding: 8px 18px;
    font-size: {g.font_size_sm}; font-weight: 500; color: {g.text_secondary};
}}
QPushButton:hover {{
    background: {g.bg_surface}; border-color: {g.border_hover};
    color: {g.text_primary};
}}
QPushButton:pressed {{ background: {g.border}; }}
QPushButton:disabled {{
    background: {g.bg_app}; color: {g.text_placeholder};
    border-color: {g.border};
}}

/* Primary */
QPushButton[class="btn-primary"] {{
    background: {m.primary}; color: white; border: none;
    font-weight: 600; padding: 8px 20px; border-radius: {g.radius};
}}
QPushButton[class="btn-primary"]:hover {{ background: {m.primary_hover}; }}
QPushButton[class="btn-primary"]:pressed {{ background: {m.primary_dark}; }}
QPushButton[class="btn-primary"]:disabled {{ background: {g.text_placeholder}; }}

/* Tertiary (text button) */
QPushButton[class="btn-tertiary"] {{
    background: transparent; color: {m.primary}; border: none;
    font-weight: 500; padding: 8px 16px;
}}
QPushButton[class="btn-tertiary"]:hover {{
    background: {m.primary_bg}; color: {m.primary_hover};
}}

/* Accent */
QPushButton[class="btn-accent"] {{
    background: {m.primary_bg}; color: {m.primary_hover};
    border: 1.5px solid {m.primary_border};
    padding: 6px 14px; font-size: {g.font_size_sm}; border-radius: {g.radius};
}}
QPushButton[class="btn-accent"]:hover {{ background: {m.primary_bg_hover}; }}

/* Outline */
QPushButton[class="btn-outline"] {{
    background: transparent; color: {m.primary};
    border: 1.5px solid {m.primary_border};
    padding: 6px 14px; border-radius: {g.radius};
}}
QPushButton[class="btn-outline"]:hover {{ background: {m.primary_bg}; }}

/* Ghost (dashed border, muted) */
QPushButton[class="btn-ghost"] {{
    background: transparent; color: {m.primary};
    border: 1.5px dashed {m.primary_border};
    padding: 8px 20px; border-radius: {g.radius};
    font-weight: 600;
}}
QPushButton[class="btn-ghost"]:hover {{
    background: {m.primary_bg}; border-style: solid;
}}
QPushButton[class="btn-ghost"]:pressed {{ background: {m.primary_bg_hover}; }}
QPushButton[class="btn-ghost"]:disabled {{
    color: {g.text_placeholder}; border-color: {g.border};
}}

/* Run All (kept for non-sidebar contexts / dialogs) */
QPushButton#btnRunAll {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {m.primary}, stop:1 {m.primary_light});
    color: white; font-size: {g.font_size_lg}; font-weight: 700;
    padding: 12px 32px; border-radius: {g.radius_lg}; border: none;
}}
QPushButton#btnRunAll:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {m.primary_hover}, stop:1 {m.primary});
}}
QPushButton#btnRunAll:disabled {{ background: {g.text_placeholder}; }}

/* Export */
QPushButton#btnExport {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {m.success}, stop:1 {m.success_light});
    color: white; font-size: {g.font_size_base}; font-weight: 600;
    padding: 10px 24px; border-radius: {g.radius_lg}; border: none;
}}
QPushButton#btnExport:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {m.success_hover}, stop:1 {m.success});
}}

/* Cleanup */
QPushButton#btnCleanup {{
    background: {m.warn_bg}; color: {m.warn_text};
    font-size: {g.font_size_sm}; padding: 8px 18px;
    border-radius: {g.radius}; border: 1px solid {m.warn_border};
}}
QPushButton#btnCleanup:hover {{ background: {m.warn_bg_hover}; }}

/* ═══════════════  CHECKBOX  ═══════════════ */
QCheckBox {{
    spacing: 8px; font-size: {g.font_size_sm}; color: {g.text_secondary};
}}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 4px;
    border: 1.5px solid {g.border_input}; background: {g.bg_card};
}}
QCheckBox::indicator:hover {{ border-color: {m.primary}; }}
QCheckBox::indicator:checked {{
    background: {m.primary}; border-color: {m.primary};
}}

/* ═══════════════  BADGES  ═══════════════ */
QLabel[class="badge-ok"] {{
    background: {m.success_bg}; color: {m.success_text};
    border-radius: {g.radius}; padding: 6px 12px;
    font-size: {g.font_size_xs}; font-weight: 600;
}}
QLabel[class="badge-err"] {{
    background: {m.error_bg}; color: {m.error_text};
    border-radius: {g.radius}; padding: 6px 12px;
    font-size: {g.font_size_xs}; font-weight: 600;
}}
QLabel[class="badge-neutral"] {{
    background: {m.neutral_bg}; color: {g.text_muted};
    border-radius: {g.radius}; padding: 6px 12px;
    font-size: {g.font_size_xs};
}}

/* ═══════════════  COLLAPSIBLE  ═══════════════ */
QToolButton[class="collapsible-toggle"] {{
    border: none; font-size: {g.font_size_base}; color: {g.text_secondary};
    padding: 8px 4px; font-weight: 600;
}}
QToolButton[class="collapsible-toggle"]:hover {{
    color: {m.primary}; background: {m.primary_bg};
    border-radius: {g.radius_sm};
}}

/* ═══════════════  GROUPBOX  ═══════════════ */
QGroupBox {{
    font-weight: 600; font-size: {g.font_size_base};
    border: 1px solid {g.border}; border-radius: {g.radius_xl};
    margin-top: 16px; padding-top: 24px; background: {g.bg_card};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 16px; padding: 0 8px;
    color: {g.text_heading};
}}

/* ═══════════════  SEPARATOR  ═══════════════ */
QFrame[class="separator"] {{
    background: {g.border}; max-height: 1px; min-height: 1px;
}}

/* ═══════════════  LOG  ═══════════════ */
QTextEdit#logBox {{
    font-family: {g.font_mono}; font-size: {g.font_size_xs};
    background: {g.bg_dark}; color: {g.text_on_dark};
    border-radius: {g.radius_lg}; padding: 12px;
    border: 1px solid {g.bg_dark_border};
    selection-background-color: {g.text_secondary};
}}

/* ═══════════════  PROGRESS BAR  ═══════════════ */
QProgressBar {{
    border: none; border-radius: {g.radius}; text-align: center;
    height: 22px; background: {g.border};
    font-size: {g.font_size_xs}; color: {g.text_tertiary};
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {m.primary}, stop:1 {m.primary_gradient_end});
    border-radius: {g.radius};
}}

/* ═══════════════  LIST WIDGET  ═══════════════ */
QListWidget {{
    background: {g.bg_input}; color: {g.text_primary};
    border: 1.5px solid {g.border_input};
    border-radius: {g.radius}; padding: 4px;
    font-size: {g.font_size_sm};
}}
QListWidget:focus {{ border-color: {m.primary}; }}
QListWidget::item {{ padding: 4px 8px; border-radius: 4px; }}
QListWidget::item:selected {{
    background: #BFDBFE; color: {m.primary_dark};
    font-weight: 600;
}}
QListWidget::item:hover:!selected {{ background: {g.bg_surface}; }}

/* ═══════════════  SPLITTER  ═══════════════ */
QSplitter::handle {{ background: {g.border}; width: 1px; }}
QSplitter::handle:hover {{ background: {m.primary}; }}

/* ═══════════════  TOOLTIP  ═══════════════ */
QToolTip {{
    background: {g.bg_dark}; color: {g.text_on_dark};
    border: 1px solid {g.bg_dark_border}; border-radius: {g.radius_sm};
    padding: 6px 10px; font-size: {g.font_size_xs};
}}
"""
