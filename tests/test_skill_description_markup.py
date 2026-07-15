import unittest

from tabs.qt_class_mod_editor_tab import QtClassModEditorTab


class SkillDescriptionMarkupTest(unittest.TestCase):
    def test_official_styles_and_safe_fallbacks(self):
        html = QtClassModEditorTab._skill_description_html(
            "[primary]Amon[/primary] deals [nowrap][fire_icon][fire]Fire[/fire][/nowrap]"
            "[newline][flavor]<unsafe>[/flavor] [rd_color]Fortune[/rd_color]."
        )
        self.assertIn("color: #EB7300", html)
        self.assertIn("color: #FF5224", html)
        self.assertIn("font-style: italic", html)
        self.assertIn("white-space: nowrap", html)
        self.assertNotIn("fire_icon", html)
        self.assertNotIn("rd_color", html)
        self.assertIn("Fortune", html)
        self.assertIn("&lt;unsafe&gt;", html)
        self.assertNotIn("<unsafe>", html)


if __name__ == '__main__':
    unittest.main()
