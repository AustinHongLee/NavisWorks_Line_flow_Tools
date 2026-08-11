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
    color: {g.sidebar_title}; font-size: {g.font_size_lg}; font-weight: 700;
}}
QLabel#sidebarVersion {{
    color: {g.sidebar_text}; font-size: {g.font_size_xs};
}}
QLabel#sidebarUpdateStatus {{
    color: #94A3B8; font-size: {g.font_size_xs};
    min-height: 14px; background: transparent;
}}
QLabel#sidebarUpdateStatus[update-state="checking"] {{ color: #CBD5E1; }}
QLabel#sidebarUpdateStatus[update-state="current"] {{ color: #86EFAC; }}
QLabel#sidebarUpdateStatus[update-state="available"] {{
    color: #FDE68A; font-weight: 700;
}}
QLabel#sidebarUpdateStatus[update-state="ahead"] {{ color: #67E8F9; }}
QLabel#sidebarUpdateStatus[update-state="unknown"] {{ color: #94A3B8; }}
QLabel#sidebarBrandIcon {{
    color: {g.sidebar_title}; background: #F8FAFC;
    border: 1px solid #CBD5E1; border-radius: 11px;
    font-size: {g.font_size_lg}; font-weight: 800;
}}
QLabel#sidebarSection {{
    color: {g.sidebar_text}; font-size: {g.font_size_xs};
    font-weight: 600;
}}

/* Sidebar nav */
QPushButton[class="sidebar-nav"] {{
    background: transparent; color: {g.sidebar_text};
    border: 2px solid transparent;
    border-radius: {g.radius}; padding: 8px 12px;
    font-size: {g.font_size_base}; font-weight: 500; text-align: left;
}}
QPushButton[class="sidebar-nav"]:hover {{
    background: {g.sidebar_item_hover}; color: {g.sidebar_text_hover};
}}
QPushButton[class="sidebar-nav"]:pressed {{
    background: #172033; color: {g.sidebar_text_active};
    padding: 9px 11px 7px 13px;
}}
QPushButton[class="sidebar-nav"]:focus {{ border-color: #60A5FA; }}
QPushButton[class="sidebar-nav"]:checked {{
    background: {g.sidebar_item_active}; color: {g.sidebar_text_active};
    font-weight: 600;
}}
QPushButton[class="sidebar-nav"]:checked:hover {{ background: #1D4ED8; }}
QPushButton[class="sidebar-nav"]:checked:pressed {{ background: #1E40AF; }}
QLabel#sidebarNavState {{
    background: transparent; font-size: {g.font_size_sm}; font-weight: 800;
}}
QLabel#sidebarNavState[nav-state="current"] {{ color: #93C5FD; }}
QLabel#sidebarNavState[nav-state="done"] {{ color: #86EFAC; }}
QLabel#sidebarNavState[nav-state="attention"] {{ color: #FDE68A; }}
QLabel#sidebarNavState[nav-state="available"] {{ color: #CBD5E1; }}
QLabel#sidebarNavState[nav-state="pending"] {{ color: #64748B; }}

/* Sidebar actions */
QPushButton#sidebarRunAll {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {m.primary}, stop:1 #167493);
    color: white; border: 2px solid transparent;
    border-radius: {g.radius}; padding: 8px 12px;
    font-size: {g.font_size_base}; font-weight: 600;
}}
QPushButton#sidebarRunAll:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {m.primary_hover}, stop:1 #12647F);
}}
QPushButton#sidebarRunAll:pressed {{
    background: {m.primary_dark}; padding: 9px 11px 7px 13px;
}}
QPushButton#sidebarRunAll:focus {{ border-color: #BFDBFE; }}
QPushButton#sidebarRunAll:disabled {{
    background: {g.sidebar_item_hover}; color: {g.sidebar_text};
    border-color: transparent;
}}
QPushButton#sidebarCleanup {{
    background: transparent; color: {g.sidebar_text};
    border: 2px solid {g.sidebar_divider}; border-radius: {g.radius};
    padding: 7px 13px; font-size: {g.font_size_sm};
}}
QPushButton#sidebarCleanup:hover {{
    background: {g.sidebar_item_hover}; color: {g.sidebar_text_hover};
}}
QPushButton#sidebarCleanup:pressed {{
    background: #172033; color: {g.sidebar_text_active};
    padding: 8px 12px 6px 14px;
}}
QPushButton#sidebarCleanup:focus {{ border-color: #60A5FA; }}
QPushButton#sidebarCleanup:disabled {{
    background: transparent; color: #64748B; border-color: #334155;
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
QLabel[class="sb-err"]     {{ color: #F87171;           font-size: {g.font_size_xs}; padding: 2px 0; }}
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
    background: {m.primary}; color: white; border: 2px solid transparent;
    border-radius: {g.radius_pill}; padding: 6px 18px;
    font-size: {g.font_size_sm}; font-weight: 700;
}}
QPushButton[step-state="active"]:hover {{ background: {m.primary_hover}; }}
QPushButton[step-state="active"]:pressed {{ background: {m.primary_dark}; }}
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
    background: {g.bg_card}; border: 2px solid {g.border_input};
    border-radius: {g.radius}; padding: 7px 17px;
    font-size: {g.font_size_sm}; font-weight: 500; color: {g.text_secondary};
}}
QPushButton:hover {{
    background: {g.bg_surface}; border-color: {g.border_hover};
    color: {g.text_primary};
}}
QPushButton:pressed {{
    background: {g.border}; padding: 8px 16px 6px 18px;
}}
QPushButton:focus {{
    border-color: {m.primary_light};
}}
QPushButton:disabled {{
    background: {g.bg_app}; color: {g.text_placeholder};
    border-color: {g.border};
}}

/* Primary */
QPushButton[class="btn-primary"] {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {m.primary}, stop:1 #167493);
    color: white; border: 2px solid transparent;
    font-weight: 600; padding: 6px 18px; border-radius: {g.radius};
}}
QPushButton[class="btn-primary"]:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {m.primary_hover}, stop:1 #12647F);
}}
QPushButton[class="btn-primary"]:pressed {{
    background: {m.primary_dark}; padding: 7px 17px 5px 19px;
}}
QPushButton[class="btn-primary"]:focus {{ border-color: #BFDBFE; }}
QPushButton[class="btn-primary"]:disabled {{
    background: {g.text_placeholder}; border-color: transparent;
}}

/* Tertiary (text button) */
QPushButton[class="btn-tertiary"] {{
    background: transparent; color: {m.primary};
    border: 2px solid transparent;
    font-weight: 500; padding: 6px 14px;
}}
QPushButton[class="btn-tertiary"]:hover {{
    background: {m.primary_bg}; color: {m.primary_hover};
}}
QPushButton[class="btn-tertiary"]:pressed {{
    background: {m.primary_bg_hover};
    padding: 7px 13px 5px 15px;
}}
QPushButton[class="btn-tertiary"]:focus {{ border-color: {m.primary}; }}
QPushButton[class="btn-tertiary"]:disabled {{
    background: transparent; color: {g.text_placeholder};
}}

/* Accent */
QPushButton[class="btn-accent"] {{
    background: {m.primary_bg}; color: {m.primary_hover};
    border: 2px solid {m.primary_border};
    padding: 6px 14px; font-size: {g.font_size_sm}; border-radius: {g.radius};
}}
QPushButton[class="btn-accent"]:hover {{ background: {m.primary_bg_hover}; }}
QPushButton[class="btn-accent"]:pressed {{
    background: {m.primary_selection}; padding: 7px 13px 5px 15px;
}}
QPushButton[class="btn-accent"]:focus {{ border-color: {m.primary}; }}
QPushButton[class="btn-accent"]:disabled {{
    background: {g.bg_app}; color: {g.text_placeholder};
    border-color: {g.border};
}}

/* Outline */
QPushButton[class="btn-outline"] {{
    background: transparent; color: {m.primary};
    border: 2px solid {m.primary_border};
    padding: 6px 14px; border-radius: {g.radius};
}}
QPushButton[class="btn-outline"]:hover {{ background: {m.primary_bg}; }}
QPushButton[class="btn-outline"]:pressed {{
    background: {m.primary_bg_hover}; padding: 7px 13px 5px 15px;
}}
QPushButton[class="btn-outline"]:focus {{ border-color: {m.primary}; }}
QPushButton[class="btn-outline"]:disabled {{
    background: transparent; color: {g.text_placeholder};
    border-color: {g.border};
}}

/* Ghost (dashed border, muted) */
QPushButton[class="btn-ghost"] {{
    background: transparent; color: {m.primary};
    border: 2px dashed {m.primary_border};
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
    padding: 10px 30px; border-radius: {g.radius_lg};
    border: 2px solid transparent;
}}
QPushButton#btnRunAll:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {m.primary_hover}, stop:1 {m.primary});
}}
QPushButton#btnRunAll:pressed {{
    background: {m.primary_dark}; padding: 11px 29px 9px 31px;
}}
QPushButton#btnRunAll:focus {{ border-color: #BFDBFE; }}
QPushButton#btnRunAll:disabled {{
    background: {g.text_placeholder}; border-color: transparent;
}}

/* Export */
QPushButton#btnExport {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {m.success}, stop:1 {m.success_light});
    color: white; font-size: {g.font_size_base}; font-weight: 600;
    padding: 8px 22px; border-radius: {g.radius_lg};
    border: 2px solid transparent;
}}
QPushButton#btnExport:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {m.success_hover}, stop:1 {m.success});
}}
QPushButton#btnExport:pressed {{
    background: {m.success_hover}; padding: 9px 21px 7px 23px;
}}
QPushButton#btnExport:focus {{ border-color: #A7F3D0; }}
QPushButton#btnExport:disabled {{
    background: {g.border}; color: {g.text_muted}; border-color: transparent;
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
QCheckBox:focus, QRadioButton:focus {{
    color: {m.primary_dark}; background: {m.primary_bg};
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
