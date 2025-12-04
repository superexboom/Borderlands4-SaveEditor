from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QTreeWidget, QTreeWidgetItem, QStackedWidget, QGroupBox, QHBoxLayout, QPushButton, QMessageBox
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
import yaml
import resource_loader

def get_yaml_loader():
    class AnyTagLoader(yaml.SafeLoader): pass
    def _ignore_any(loader: AnyTagLoader, tag_suffix: str, node: 'yaml.Node'):
        if isinstance(node, yaml.ScalarNode): return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode): return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode): return loader.construct_mapping(node)
        return None
    AnyTagLoader.add_multi_constructor("", _ignore_any)
    return AnyTagLoader

class QtYamlEditorTab(QWidget):
    yaml_text_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        self._load_localization(self.current_lang)
        self.main_window = parent
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self._emit_yaml_change)
        
        # Main layout only holds the content widget
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.content_widget = None
        self._build_ui()

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self._load_localization(lang)
        
        # Save current state
        current_text = self.get_yaml_text()
        current_idx = self.stacked_widget.currentIndex() if hasattr(self, 'stacked_widget') else 0
        
        self._build_ui()
        
        # Restore state
        if current_text:
            self.set_yaml_text(current_text)
        if hasattr(self, 'stacked_widget'):
            self.stacked_widget.setCurrentIndex(current_idx)
            
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def _load_localization(self, lang='zh-CN'):
        file_name = resource_loader.get_ui_localization_file(lang)
        data = resource_loader.load_json_resource(file_name)
        if data and "yaml_tab" in data:
            self.loc = data["yaml_tab"]
        else:
            # Fallback
            self.loc = {
                "tree_headers": {"key": "Key", "value": "Value"},
                "buttons": {"yaml_view": "YAML View", "tree_view": "Tree View"},
                "dialogs": {"yaml_error": "YAML Error", "parse_error": "Parse Error: {error}"}
            }

    def _emit_yaml_change(self):
        self.yaml_text_changed.emit(self.get_yaml_text())

    def _build_ui(self):
        # Clean up old content widget
        if self.content_widget:
            self.main_layout.removeWidget(self.content_widget)
            self.content_widget.deleteLater()
            self.content_widget = None

        # Create new content widget
        self.content_widget = QWidget()
        content_layout = QVBoxLayout(self.content_widget)

        self.stacked_widget = QStackedWidget()

        # YAML Text Editor
        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        self.yaml_text = QTextEdit()
        self.yaml_text.textChanged.connect(self.on_text_changed)
        text_layout.addWidget(self.yaml_text)

        # YAML Tree View
        tree_widget = QWidget()
        tree_layout = QVBoxLayout(tree_widget)
        self.tree_view = QTreeWidget()
        self.tree_view.setHeaderLabels([self.loc['tree_headers']['key'], self.loc['tree_headers']['value']])
        self.tree_view.setColumnWidth(0, 240)
        tree_layout.addWidget(self.tree_view)

        self.stacked_widget.addWidget(text_widget)
        self.stacked_widget.addWidget(tree_widget)

        button_layout = QHBoxLayout()
        yaml_view_button = QPushButton(self.loc['buttons']['yaml_view'])
        yaml_view_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))
        tree_view_button = QPushButton(self.loc['buttons']['tree_view'])
        tree_view_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))
        
        button_layout.addWidget(yaml_view_button)
        button_layout.addWidget(tree_view_button)
        
        content_layout.addLayout(button_layout)
        content_layout.addWidget(self.stacked_widget)
        
        self.main_layout.addWidget(self.content_widget)

    def set_yaml_text(self, text):
        # 暂时断开信号避免在程序设置文本时触发不必要的更新
        self.yaml_text.blockSignals(True)
        self.yaml_text.setText(text)
        self.yaml_text.blockSignals(False)
        self.parse_yaml_to_tree()

    def on_text_changed(self):
        self.update_timer.start(500)  # 500ms延迟
        
    def get_yaml_text(self):
        return self.yaml_text.toPlainText()

    def parse_yaml_to_tree(self):
        self.tree_view.clear()
        try:
            data = yaml.load(self.get_yaml_text(), Loader=get_yaml_loader())
            if data:
                self.populate_tree(self.tree_view.invisibleRootItem(), data)
        except yaml.YAMLError as e:
            QMessageBox.critical(self, self.loc['dialogs']['yaml_error'], self.loc['dialogs']['parse_error'].format(error=e))

    def populate_tree(self, parent_item, data):
        if isinstance(data, dict):
            for key, value in data.items():
                child_item = QTreeWidgetItem([str(key)])
                self.populate_tree(child_item, value)
                parent_item.addChild(child_item)
        elif isinstance(data, list):
            for index, value in enumerate(data):
                child_item = QTreeWidgetItem([f"[{index}]"])
                self.populate_tree(child_item, value)
                parent_item.addChild(child_item)
        else:
            parent_item.setText(1, str(data))
