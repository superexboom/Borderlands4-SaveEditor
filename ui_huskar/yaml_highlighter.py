"""YAML syntax highlighting for the YAML editor's source view (a QML TextArea document)."""

import re

from PyQt6.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat

from core.yaml_model import COLOR_BOOL, COLOR_KEY, COLOR_NULL, COLOR_NUM, COLOR_STR


class YamlHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        self._build_rules(COLOR_KEY, COLOR_STR, COLOR_NUM, COLOR_BOOL, COLOR_NULL)

    def _build_rules(self, c_key, c_str, c_num, c_bool, c_null):
        fmt_key = QTextCharFormat(); fmt_key.setForeground(c_key); fmt_key.setFontWeight(QFont.Weight.Medium)
        fmt_str = QTextCharFormat(); fmt_str.setForeground(c_str)
        fmt_num = QTextCharFormat(); fmt_num.setForeground(c_num)
        fmt_bool = QTextCharFormat(); fmt_bool.setForeground(c_bool)
        fmt_comment = QTextCharFormat(); fmt_comment.setForeground(c_null); fmt_comment.setFontItalic(True)
        self.rules = [
            (re.compile(r'^\s*-\s+[^:#\s][^:]*(?=:\s)'), fmt_key),
            (re.compile(r'^\s*[^:#\s][^:]*(?=:\s|$)'), fmt_key),
            (re.compile(r'"[^"\n]*"|\'[^\'\n]*\''), fmt_str),
            (re.compile(r'(?<=:\s)-?\d+(\.\d+)?\s*$'), fmt_num),
            (re.compile(r'(?<=:\s)(true|false|null|~)\s*$'), fmt_bool),
            (re.compile(r'#.*$'), fmt_comment),
        ]

    def apply_theme(self, colors: dict):
        """用模型同款配色重建规则并重刷全文。"""
        self._build_rules(colors["key"], colors["str"], colors["num"],
                          colors["bool"], colors["null"])
        self.rehighlight()

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
