"""Dark/light theme preference: saved choice, else the Windows app theme."""

import sys

from PyQt6.QtCore import QSettings


class ThemeManager:
    DARK = 'dark'
    LIGHT = 'light'

    def __init__(self, settings=None):
        self.settings = settings or QSettings('SuperExboom', 'BL4SaveEditor')
        saved = self.settings.value('theme', None)
        self._current_theme = saved if saved in (self.DARK, self.LIGHT) else self._detect_system_theme()

    @property
    def current(self):
        return self._current_theme

    def _detect_system_theme(self):
        """Windows 'AppsUseLightTheme'; dark when unknown."""
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
        return self.DARK

    def set_theme(self, theme_name):
        if theme_name in (self.DARK, self.LIGHT):
            self._current_theme = theme_name
            self.settings.setValue('theme', theme_name)

    def toggle_theme(self):
        new_theme = self.LIGHT if self._current_theme == self.DARK else self.DARK
        self.set_theme(new_theme)
        return new_theme

    def is_dark(self):
        return self._current_theme == self.DARK
