"""
Theme Manager for BL4 Save Editor
Handles dark/light theme switching with frosted glass effects.
"""

import sys
from pathlib import Path
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from . import resource_loader


class ThemeManager:
    """Manages application themes (dark/light) with frosted glass styling."""
    
    DARK = 'dark'
    LIGHT = 'light'
    
    # Color palettes for each theme
    THEMES = {
        'dark': {
            # Backgrounds with transparency for frosted glass effect (reduced opacity for better background visibility)
            'bg_primary': 'rgba(30, 30, 35, 0.35)',
            'bg_secondary': 'rgba(40, 40, 48, 0.32)',
            'bg_panel': 'rgba(35, 35, 42, 0.30)',
            'bg_input': 'rgba(50, 50, 58, 0.45)',
            'bg_header': 'rgba(22, 22, 28, 0.50)',
            
            # Solid backgrounds (no transparency)
            'sidebar_bg': '#3a3a45',  # Same as button_bg for consistency
            'dropdown_bg': '#2a2a32',
            'button_bg': '#3a3a45',
            'button_hover': '#4a4a58',
            'button_pressed': '#4a90e2',
            
            # Text colors
            'text_primary': '#e8e8ec',
            'text_secondary': '#a0a0a8',
            'text_disabled': '#606068',
            
            # Borders
            'border_color': 'rgba(80, 80, 95, 0.6)',
            'border_focus': '#4a90e2',
            
            # Accent
            'accent': '#4a90e2',
            'accent_hover': '#5a9ff0',
            
            # Special
            'scrollbar_bg': '#2a2a32',
            'scrollbar_handle': '#5a5a68',
            'selection_bg': '#4a90e2',
        },
        'light': {
            # Backgrounds with transparency for frosted glass effect (reduced opacity for better background visibility)
            'bg_primary': 'rgba(255, 255, 255, 0.35)',
            'bg_secondary': 'rgba(248, 248, 252, 0.32)',
            'bg_panel': 'rgba(252, 252, 255, 0.30)',
            'bg_input': 'rgba(255, 255, 255, 0.50)',
            'bg_header': 'rgba(240, 240, 248, 0.50)',
            
            # Solid backgrounds (no transparency)
            'sidebar_bg': '#e8e8f0',
            'dropdown_bg': '#ffffff',
            'button_bg': '#e0e0e8',
            'button_hover': '#d0d0d8',
            'button_pressed': '#4a90e2',
            
            # Text colors
            'text_primary': '#1a1a24',
            'text_secondary': '#5a5a68',
            'text_disabled': '#a0a0a8',
            
            # Borders
            'border_color': 'rgba(180, 180, 200, 0.5)',
            'border_focus': '#4a90e2',
            
            # Accent
            'accent': '#4a90e2',
            'accent_hover': '#3a80d2',
            
            # Special
            'scrollbar_bg': '#e8e8f0',
            'scrollbar_handle': '#c0c0c8',
            'selection_bg': '#4a90e2',
        }
    }
    
    def __init__(self):
        self.settings = QSettings('SuperExboom', 'BL4SaveEditor')
        self._current_theme = self._load_saved_theme()
        self._stylesheet_template = self._load_stylesheet_template()
    
    @property
    def current(self):
        """Returns the current theme name."""
        return self._current_theme
    
    def _load_saved_theme(self):
        """Load saved theme preference or detect system theme."""
        saved = self.settings.value('theme', None)
        if saved in (self.DARK, self.LIGHT):
            return saved
        return self._detect_system_theme()
    
    def _detect_system_theme(self):
        """Detect Windows system theme (dark/light mode)."""
        try:
            if sys.platform == 'win32':
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
                )
                value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
                winreg.CloseKey(key)
                return self.LIGHT if value == 1 else self.DARK
        except Exception:
            pass
        return self.DARK  # Default to dark theme
    
    def _load_stylesheet_template(self):
        """Load the stylesheet template from file."""
        content = resource_loader.load_text_resource("assets/stylesheet.qss")
        if content:
            return content
        return ""
    
    def set_theme(self, theme_name):
        """Set the current theme and save preference."""
        if theme_name in (self.DARK, self.LIGHT):
            self._current_theme = theme_name
            self.settings.setValue('theme', theme_name)
    
    def toggle_theme(self):
        """Toggle between dark and light themes."""
        new_theme = self.LIGHT if self._current_theme == self.DARK else self.DARK
        self.set_theme(new_theme)
        return new_theme
    
    def get_colors(self):
        """Get the color dictionary for the current theme."""
        return self.THEMES.get(self._current_theme, self.THEMES[self.DARK])
    
    def get_stylesheet(self):
        """Generate the stylesheet for the current theme."""
        colors = self.get_colors()
        
        # Replace placeholders in template with actual colors
        stylesheet = self._stylesheet_template
        for key, value in colors.items():
            placeholder = '{' + key + '}'
            stylesheet = stylesheet.replace(placeholder, value)
        
        return stylesheet
    
    def is_dark(self):
        """Check if current theme is dark."""
        return self._current_theme == self.DARK
    
    def get_theme_icon(self):
        """Get the appropriate icon for the theme toggle button."""
        return "☀️" if self._current_theme == self.DARK else "🌙"
    
    def get_background_overlay_color(self):
        """Get the color for the background overlay based on theme."""
        if self._current_theme == self.DARK:
            return "rgba(0, 0, 0, 0.3)"
        else:
            return "rgba(255, 255, 255, 0.2)"
