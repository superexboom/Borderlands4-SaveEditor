
import sys
import time
import itertools
import os
from pathlib import Path

VERSION = "3.4"
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QMessageBox, QFileDialog,
    QStatusBar, QStackedWidget, QButtonGroup, QSizeGrip, QInputDialog,
    QMenu, QGraphicsBlurEffect, QStackedLayout, QFrame
)
from PyQt6.QtGui import QAction, QIcon, QPixmap, QPainter, QBrush, QColor
from PyQt6.QtCore import pyqtSlot, QPropertyAnimation, QEasingCurve, Qt, QTimer, QObject, QThread, pyqtSignal

import b_encoder
import resource_loader
import bl4_functions as bl4f

from save_game_controller import SaveGameController
from save_selector_widget import SaveSelectorWidget
from qt_character_tab import QtCharacterTab
from qt_items_tab import QtItemsTab
from qt_weapon_generator_tab import QtWeaponGeneratorTab
from qt_converter_tab import QtConverterTab
from qt_class_mod_editor_tab import QtClassModEditorTab
from qt_heavy_weapon_editor_tab import QtHeavyWeaponEditorTab
from qt_shield_editor_tab import QtShieldEditorTab
from qt_grenade_editor_tab import QtGrenadeEditorTab
from qt_repkit_editor_tab import QtRepkitEditorTab
from qt_yaml_editor_tab import QtYamlEditorTab
from qt_enhancement_editor_tab import QtEnhancementEditorTab
from qt_weapon_editor_tab import WeaponEditorTab as QtWeaponEditorTab
from theme_manager import ThemeManager


class BackgroundWidget(QLabel):
    """Widget that displays a blurred background image for frosted glass effect."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("backgroundLayer")
        self._original_pixmap = None
        self._corner_radius = 20  # Match the window corner radius
        # Prevent the background from affecting window size
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._load_background_image()
        
    def _load_background_image(self):
        """Load and apply the background image with blur effect."""
        bg_path = resource_loader.get_resource_path("bg.jpg")
        if bg_path and bg_path.exists():
            self._original_pixmap = QPixmap(str(bg_path))
            self._apply_blur()
        else:
            # Fallback: solid dark background
            self.setStyleSheet("background-color: #1a1a20;")
    
    def _apply_blur(self):
        """Apply blur effect to the background."""
        if self._original_pixmap:
            blur = QGraphicsBlurEffect(self)
            blur.setBlurRadius(15)
            blur.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
            self.setGraphicsEffect(blur)
            # Don't set pixmap directly here, let resizeEvent handle scaling
            self.setScaledContents(True)
    
    def resizeEvent(self, event):
        """Handle resize to scale background - maintains aspect ratio, crops to fill."""
        super().resizeEvent(event)
        if self._original_pixmap:
            # Use KeepAspectRatioByExpanding to maintain aspect ratio and crop excess
            scaled_pixmap = self._original_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            # Crop to center if larger than widget size
            if scaled_pixmap.size() != self.size():
                x = (scaled_pixmap.width() - self.width()) // 2
                y = (scaled_pixmap.height() - self.height()) // 2
                scaled_pixmap = scaled_pixmap.copy(x, y, self.width(), self.height())
            self.setPixmap(scaled_pixmap)
        # Note: Mask is applied at the central widget level in MainWindow.resizeEvent


class IteratorWorker(QObject):
    status_update = pyqtSignal(str)
    finished_generation = pyqtSignal(str)
    finished_add_to_backpack = pyqtSignal(int, int)

    def __init__(self, controller, params, loc_data):
        super().__init__()
        self.controller = controller
        self.params = params
        self.loc = loc_data

    def run(self):
        try:
            is_add_to_backpack = self.params.get('add_to_backpack', False)
            
            deserialized_strings = self._generate_deserialized_list()
            if not deserialized_strings:
                self.status_update.emit(self.loc['no_data'])
                if is_add_to_backpack:
                    self.finished_add_to_backpack.emit(0, 0)
                else:
                    self.finished_generation.emit("")
                return

            if is_add_to_backpack:
                self._add_items_to_backpack(deserialized_strings)
            else:
                self._generate_output_text(deserialized_strings)

        except ValueError as e:
            self.status_update.emit(f"{self.loc['error_prefix']}{e}")
            if self.params.get('add_to_backpack'): self.finished_add_to_backpack.emit(0, 0)
            else: self.finished_generation.emit("")
        except Exception as e:
            self.status_update.emit(f"{self.loc['error_prefix']}{e}")
            if self.params.get('add_to_backpack'): self.finished_add_to_backpack.emit(0, 0)
            else: self.finished_generation.emit("")

    def _generate_deserialized_list(self):
        self.status_update.emit(self.loc['generating'])
        base_data = self.params['base_data'].strip()
        if not base_data: raise ValueError(self.loc['base_empty'])
        
        strings = []
        if self.params['is_combo']:
            start, end, size = int(self.params['combo_start']), int(self.params['combo_end']), int(self.params['combo_size'])
            if start > end: raise ValueError(self.loc['combo_error_range'])
            source_set = list(range(start, end + 1))
            if len(source_set) < size: raise ValueError(self.loc['combo_error_size'])
            combos = list(itertools.combinations(source_set, size))
            for combo in combos:
                strings.append(f"{base_data} {' '.join(f'{{{c}}}' for c in combo)}|")
        else:
            start, end = int(self.params['start']), int(self.params['end'])
            if start > end: raise ValueError(self.loc['iter_error_range'])
            if self.params['is_skin']:
                for i in range(start, end + 1):
                    strings.append(f'{base_data} | "c", {i}|')
            else:
                special_base = self.params['special_base']
                is_special_combo = self.params.get('is_special_combo', False)
                combo_text = self.params.get('special_combo_text', "").strip()

                if (self.params['is_special'] or is_special_combo) and not special_base:
                    raise ValueError(self.loc['special_base_needed'])
                
                for i in range(start, end + 1):
                    if is_special_combo:
                        # Format: {AAA:[98 99 B]}
                        part = f"{{{special_base}:[{combo_text} {i}]}}"
                    elif self.params['is_special']:
                        part = f"{{{special_base}:{i}}}"
                    else:
                        part = f"{{{i}}}"
                    strings.append(f"{base_data}{part}|")
        return strings

    def _add_items_to_backpack(self, strings):
        self.status_update.emit(self.loc['generated_writing'].format(count=len(strings)))
        success, fail = 0, 0
        total = len(strings)
        flag = self.params['yaml_flag']

        for i, line in enumerate(strings):
            self.status_update.emit(self.loc['writing_progress'].format(current=i + 1, total=total))
            try:
                serial, err = b_encoder.encode_to_base85(line)
                if err:
                    fail += 1
                    continue
                if self.controller.add_item_to_backpack(serial, flag):
                    success += 1
                else:
                    fail += 1
            except Exception:
                fail += 1
            time.sleep(0.01)
        self.finished_add_to_backpack.emit(success, fail)

    def _generate_output_text(self, strings):
        self.status_update.emit(self.loc['generated_encoding'].format(count=len(strings)))
        final_output = []
        total = len(strings)
        is_yaml = self.params['is_yaml']
        yaml_flag = self.params['yaml_flag']

        for i, line in enumerate(strings):
            if (i+1) % 20 == 0:
                self.status_update.emit(self.loc['encoding_progress'].format(current=i + 1, total=total))

            result, error = b_encoder.encode_to_base85(line)
            if error:
                output_line = f"{self.loc['error_prefix']}{error}"
            elif is_yaml:
                output_line = f"        - serial: '{result}'\n          state_flags: {yaml_flag}"
            else:
                output_line = f"{line}  -->  {result}"
            final_output.append(output_line)
            time.sleep(0.005)
        self.finished_generation.emit('\n'.join(final_output))

class BatchAddWorker(QObject):
    progress = pyqtSignal(int, int, int, int) # current, total, success, fail
    finished = pyqtSignal(int, int) # success, fail

    def __init__(self, controller, lines, flag):
        super().__init__()
        self.controller = controller
        self.lines = lines
        self.flag = flag

    def run(self):
        success_count = 0
        fail_count = 0
        total = len(self.lines)
        for i, line in enumerate(self.lines):
            try:
                if line.strip().startswith('@U'):
                    serial = line
                else:
                    serial, err = b_encoder.encode_to_base85(line)
                    if err:
                        fail_count += 1
                        continue
                
                if self.controller.add_item_to_backpack(serial, self.flag):
                    success_count += 1
                else:
                    fail_count += 1
            except Exception:
                fail_count += 1
            finally:
                self.progress.emit(i + 1, total, success_count, fail_count)
        
        self.finished.emit(success_count, fail_count)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_language = 'zh-CN'
        self._load_localization()
        
        # Initialize theme manager
        self.theme_manager = ThemeManager()
        
        self.setWindowTitle(self.loc['window_title'].format(version=VERSION))
        icon_path = resource_loader.get_resource_path("BL4.ico")
        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setGeometry(100, 100, 1600, 900)

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.old_pos = None

        self.controller = SaveGameController()
        self.is_nav_bar_expanded = True
        self.nav_bar_width_expanded = 150
        self.nav_bar_width_collapsed = 60

        # Apply themed stylesheet
        self._apply_themed_stylesheet()

        self._create_actions()

        # Create central widget with background support
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        central_widget.setObjectName("centralWidget")
        
        # Use stacked layout for background + content overlay
        stacked_layout = QStackedLayout(central_widget)
        stacked_layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stacked_layout.setContentsMargins(0, 0, 0, 0)
        
        # Background layer (blurred image)
        self.background_widget = BackgroundWidget()
        stacked_layout.addWidget(self.background_widget)
        
        # Content layer (on top of background)
        content_container = QWidget()
        content_container.setObjectName("contentWrapper")
        content_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        root_layout = QVBoxLayout(content_container)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        stacked_layout.addWidget(content_container)
        
        # Ensure content is on top
        stacked_layout.setCurrentWidget(content_container)

        self._create_header_bar()
        root_layout.addWidget(self.header_bar)

        main_content_layout = QHBoxLayout()
        main_content_layout.setSpacing(0)
        
        self.content_stack = QStackedWidget()
        self._create_nav_bar()

        main_content_layout.addWidget(self.nav_bar)
        main_content_layout.addWidget(self.content_stack)
        
        root_layout.addLayout(main_content_layout)

        # Custom footer
        self.footer = QWidget()
        self.footer.setObjectName("footer")
        self.footer.setFixedHeight(25)
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(15, 0, 15, 0)
        self.status_label = QLabel(self.loc['status']['welcome'])
        self.status_label.setObjectName("statusLabel")
        footer_layout.addWidget(self.status_label)
        footer_layout.addStretch()
        root_layout.addWidget(self.footer)

        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(20, 20)
        
        self._add_tabs()
        self.scan_for_saves()
        self.update_action_states()
    
    def _load_localization(self):
        lang_map = {
            'zh-CN': "ui_localization.json",
            'en-US': "ui_localization_EN.json",
            'ru': "ui_localization_RU.json",
            'ua': "ui_localization_UA.json"
        }
        filename = lang_map.get(self.current_language, "ui_localization_EN.json")
        data = resource_loader.load_json_resource(filename)
        if data and "main_window" in data:
            self.loc = data["main_window"]
        else:
            # Fallback if file missing (or partial)
            self.loc = {
                "window_title": "Borderlands 4 Save Editor V{version}",
                "subtitle": "By SuperExboom",
                "header": {"title": "BL4 Save Editor", "open": "Open", "save": "Save", "save_as": "Save As..."},
                "menu": {"open_selector": "Open Selector", "save": "Save", "save_as": "Save As..."},
                "status": {"welcome": "Welcome"},
                "tabs": {
                    "select_save": "Select Save", "character": "Character", "items": "Items", 
                    "converter": "Converter", "yaml_editor": "YAML", "class_mod": "Class Mod", 
                    "enhancement": "Enhancement", "weapon_editor": "Weapon Edit", 
                    "weapon_generator": "Weapon Gen", "grenade": "Grenade", "shield": "Shield", 
                    "repkit": "RepKit", "heavy_weapon": "Heavy"
                },
                "dialogs": {
                    "success": "Success", "error": "Error", "critical": "Critical", "warning": "Warning", "cancel": "Cancel"
                },
                "worker": {
                    "no_data": "No data.", "error_prefix": "Error: "
                }
            }

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.header_bar.underMouse():
            self.old_pos = event.globalPosition().toPoint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.size_grip.move(self.width() - self.size_grip.width(), self.height() - self.size_grip.height())
        self.size_grip.raise_()
        
        # Apply rounded corner mask to central widget to clip all child widgets including blur effect
        central = self.centralWidget()
        if central:
            from PyQt6.QtGui import QBitmap, QPainter
            corner_radius = 20
            
            bitmap = QBitmap(central.width(), central.height())
            bitmap.fill(Qt.GlobalColor.white)  # White = transparent in mask
            
            painter = QPainter(bitmap)
            painter.setBrush(Qt.GlobalColor.black)  # Black = visible in mask
            painter.setPen(Qt.GlobalColor.black)
            painter.drawRoundedRect(0, 0, central.width(), central.height(), 
                                    corner_radius, corner_radius)
            painter.end()
            
            central.setMask(bitmap)

    def mouseMoveEvent(self, event):
        if self.old_pos is not None and event.buttons() == Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = None
            
    def _create_actions(self):
        self.open_action = QAction(self.loc['menu']['open_selector'], self)
        self.open_action.triggered.connect(self.browse_and_open_save)
        
        self.save_action = QAction(self.loc['menu']['save'], self)
        self.save_action.triggered.connect(self.encrypt_and_save)

        self.save_as_action = QAction(self.loc['menu']['save_as'], self)
        self.save_as_action.triggered.connect(lambda: self.encrypt_and_save(save_as=True))

    def _create_header_bar(self):
        self.header_bar = QWidget()
        self.header_bar.setObjectName("headerBar")
        header_layout = QHBoxLayout(self.header_bar)
        header_layout.setContentsMargins(15, 5, 10, 5)
        header_layout.setSpacing(10)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(0) 
        
        title_label = QLabel(self.loc['header']['title'])
        title_label.setObjectName("titleLabel")
        
        subtitle_label = QLabel(self.loc['subtitle'])
        subtitle_label.setObjectName("subtitleLabel")
        
        title_vbox.addWidget(title_label)
        title_vbox.addWidget(subtitle_label)

        header_layout.addLayout(title_vbox)
        header_layout.addStretch()

        self.open_button = QPushButton(self.loc['header']['open'])
        self.open_button.clicked.connect(self.open_action.trigger)
        self.save_button = QPushButton(self.loc['header']['save'])
        self.save_button.clicked.connect(self.save_action.trigger)
        self.save_as_button = QPushButton(self.loc['header']['save_as'])
        self.save_as_button.clicked.connect(self.save_as_action.trigger)

        header_layout.addWidget(self.open_button)
        header_layout.addWidget(self.save_button)
        header_layout.addWidget(self.save_as_button)

        self.lang_button = QPushButton(self._get_lang_button_text())
        self.lang_button.setFixedWidth(60)
        
        self.lang_menu = QMenu(self)
        
        # Define languages
        languages = [
            ("简体中文", "zh-CN"),
            ("English", "en-US"),
            ("Русский", "ru"),
            ("Українська", "ua")
        ]
        
        for label, code in languages:
            action = QAction(label, self)
            # Use default parameter to capture 'code' value in lambda closure
            action.triggered.connect(lambda checked, c=code: self.change_language(c))
            self.lang_menu.addAction(action)

        self.lang_button.setMenu(self.lang_menu)
        header_layout.addWidget(self.lang_button)

        # Theme toggle button (next to language button)
        self.theme_button = QPushButton(self.theme_manager.get_theme_icon())
        self.theme_button.setObjectName("themeButton")
        self.theme_button.setFixedWidth(45)
        self.theme_button.setToolTip(self._get_theme_tooltip())
        self.theme_button.clicked.connect(self.toggle_theme)
        header_layout.addWidget(self.theme_button)

        header_layout.addStretch()

        self.minimize_button = QPushButton("—")
        self.minimize_button.setObjectName("minimizeButton")
        self.minimize_button.clicked.connect(self.showMinimized)

        self.maximize_button = QPushButton("⬜")
        self.maximize_button.setObjectName("maximizeButton")
        self.maximize_button.clicked.connect(self.toggle_maximize_restore)

        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("closeButton")
        self.close_button.clicked.connect(self.close)

        header_layout.addWidget(self.minimize_button)
        header_layout.addWidget(self.maximize_button)
        header_layout.addWidget(self.close_button)

    def toggle_maximize_restore(self):
        if self.isMaximized():
            self.showNormal()
            self.maximize_button.setText("⬜")
        else:
            self.showMaximized()
            self.maximize_button.setText("❐")

    def _create_nav_bar(self):
        self.nav_bar = QWidget()
        self.nav_bar.setObjectName("nav_bar")
        self.nav_bar.setFixedWidth(self.nav_bar_width_expanded)
        self.nav_bar_layout = QVBoxLayout(self.nav_bar)
        self.nav_bar_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.nav_bar_layout.setContentsMargins(5, 5, 5, 5)
        self.nav_bar_layout.setSpacing(5)

        self.toggle_button = QPushButton("👈")
        self.toggle_button.setObjectName("toggleButton")
        self.toggle_button.clicked.connect(self.toggle_nav_bar)
        self.nav_bar_layout.addWidget(self.toggle_button)

        self.nav_button_group = QButtonGroup(self)
        self.nav_button_group.setExclusive(True)
        self.nav_button_group.idClicked.connect(self.handle_nav_click)
    
    def _add_tabs(self):
        self.selector_page = SaveSelectorWidget()
        self.selector_page.open_save_requested.connect(self.open_save_from_selector)
        self.selector_page.refresh_button.clicked.connect(self.scan_for_saves)
        self.add_tab(self.selector_page, self.loc['tabs']['select_save'], "📁")

        self.character_tab = QtCharacterTab()
        self.character_tab.character_data_changed.connect(self.handle_character_update)
        self.character_tab.sync_levels_requested.connect(self.handle_sync_levels)
        self.character_tab.unlock_requested.connect(self.handle_unlock_request)
        self.add_tab(self.character_tab, self.loc['tabs']['character'], "👤")

        self.items_tab = QtItemsTab()
        self.items_tab.add_item_requested.connect(self.handle_add_to_backpack)
        self.items_tab.update_item_requested.connect(self.handle_update_item)
        self.add_tab(self.items_tab, self.loc['tabs']['items'], "🎒")

        self.converter_tab = QtConverterTab()
        self.converter_tab.batch_add_requested.connect(self.handle_batch_add)
        self.converter_tab.iterator_requested.connect(self.handle_iterator_request)
        self.converter_tab.iterator_add_to_backpack_requested.connect(self.handle_iterator_add_to_backpack)
        self.add_tab(self.converter_tab, self.loc['tabs']['converter'], "🔧")

        self.yaml_editor_tab = QtYamlEditorTab()
        self.yaml_editor_tab.yaml_text_changed.connect(self.handle_yaml_update)
        self.add_tab(self.yaml_editor_tab, self.loc['tabs']['yaml_editor'], "📄")

        self.class_mod_tab = QtClassModEditorTab()
        self.class_mod_tab.add_to_backpack_requested.connect(self.handle_add_to_backpack)
        self.add_tab(self.class_mod_tab, self.loc['tabs']['class_mod'], "🌟")

        self.enhancement_tab = QtEnhancementEditorTab()
        self.enhancement_tab.add_to_backpack_requested.connect(self.handle_add_to_backpack)
        self.add_tab(self.enhancement_tab, self.loc['tabs']['enhancement'], "✨")

        self.weapon_editor_tab = QtWeaponEditorTab(self)
        self.weapon_editor_tab.add_to_backpack_requested.connect(self.handle_add_to_backpack)
        self.weapon_editor_tab.update_item_requested.connect(self.handle_update_item)
        self.add_tab(self.weapon_editor_tab, self.loc['tabs']['weapon_editor'], "🔧")

        self.weapon_generator_tab = QtWeaponGeneratorTab()
        self.weapon_generator_tab.add_to_backpack_requested.connect(self.handle_add_to_backpack)
        self.add_tab(self.weapon_generator_tab, self.loc['tabs']['weapon_generator'], "🔫")

        self.grenade_tab = QtGrenadeEditorTab()
        self.grenade_tab.add_to_backpack_requested.connect(self.handle_add_to_backpack)
        self.add_tab(self.grenade_tab, self.loc['tabs']['grenade'], "💣")

        self.shield_tab = QtShieldEditorTab()
        self.shield_tab.add_to_backpack_requested.connect(self.handle_add_to_backpack)
        self.add_tab(self.shield_tab, self.loc['tabs']['shield'], "🛡️")

        self.repkit_tab = QtRepkitEditorTab()
        self.repkit_tab.add_to_backpack_requested.connect(self.handle_add_to_backpack)
        self.add_tab(self.repkit_tab, self.loc['tabs']['repkit'], "🛠️")

        self.heavy_weapon_tab = QtHeavyWeaponEditorTab()
        self.heavy_weapon_tab.add_to_backpack_requested.connect(self.handle_add_to_backpack)
        self.add_tab(self.heavy_weapon_tab, self.loc['tabs']['heavy_weapon'], "🚀")


        if self.nav_button_group.buttons():
            self.nav_button_group.buttons()[0].click()

    def add_tab(self, widget: QWidget, text: str, icon_char: str):
        index = self.content_stack.addWidget(widget)
        button = QPushButton(f" {icon_char}   {text}")
        button.setProperty("fullText", f" {icon_char}   {text}")
        button.setProperty("iconChar", icon_char)
        button.setCheckable(True)
        self.nav_bar_layout.addWidget(button)
        self.nav_button_group.addButton(button, index)
    
    def switch_to_tab(self, index: int):
        if 0 <= index < self.content_stack.count():
            self.content_stack.setCurrentIndex(index)
            
            # The button group `idClicked` signal is connected to `handle_nav_click`,
            # which already calls `setCurrentIndex`. To avoid recursion and redundant calls,
            # we directly update the button's checked state and styles.
            button_to_check = self.nav_button_group.button(index)
            if button_to_check and not button_to_check.isChecked():
                # Manually set the button as checked. This will not emit `idClicked`.
                button_to_check.setChecked(True)
            self.update_action_states()

    @pyqtSlot(int)
    def handle_nav_click(self, index: int):
        self.content_stack.setCurrentIndex(index)
        self.update_action_states()

    def browse_and_open_save(self):
        """
        打开文件选择对话框，让用户手动选择存档文件。
        """
        # 尝试定位到默认的存档路径作为起始目录
        custom_save = self.selector_page.get_custom_save_path()
        if custom_save and os.path.exists(custom_save):
            initial_path = custom_save
        else:
            start_dir = os.path.expanduser('~/Documents')
            possible_paths = [
                os.path.join(start_dir, "My Games", "Borderlands 4", "Saved", "SaveGames"),
                start_dir
            ]
            initial_path = start_dir
            for p in possible_paths:
                if os.path.exists(p):
                    initial_path = p
                    break

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.loc['header']['open'], 
            initial_path,
            "Borderlands 4 Save (*.sav);;All Files (*.*)"
        )

        if not file_path:
            return

        path_obj = Path(file_path)
        # 尝试从路径中回溯获取ID
        # 这里的逻辑参考了存档结构：.../SaveGames/<ID>/Profiles/client/...
        # 我们向上遍历父文件夹，寻找符合ID特征的文件夹名
        inferred_id = ""
        current_path = path_obj.parent
        
        # 防止死循环，最多向上查找5层 (SaveGames -> ID -> Profiles -> client -> save)
        for _ in range(5):
            dirname = current_path.name
            # 简单检查是否符合ID特征 (参考 save_game_controller.validate_user_id)
            # Steam ID: 17位数字
            # Epic ID: 较长的字母数字组合 (通常 > 10)
            # 排除常见文件夹名如 "Profiles", "client", "SaveGames" (有些虽然是字母但长度不够)
            
            is_valid_format = False
            if dirname.isdigit() and 10 <= len(dirname) <= 20:
                is_valid_format = True
            elif dirname.replace('-', '').replace('_', '').isalnum() and 10 <= len(dirname) <= 50:
                # 排除一些特定的短名字，虽然上面长度判断可能已经排除了一部分
                if dirname.lower() not in ["profiles", "client", "savegames", "saved", "config"]:
                    is_valid_format = True
            
            if is_valid_format:
                inferred_id = dirname
                break
            
            if current_path.parent == current_path: # 到达根目录
                break
            current_path = current_path.parent

        self.open_save_from_selector(file_path, inferred_id)

    @pyqtSlot()
    def toggle_nav_bar(self):
        self.is_nav_bar_expanded = not self.is_nav_bar_expanded
        target_width = self.nav_bar_width_expanded if self.is_nav_bar_expanded else self.nav_bar_width_collapsed

        # Set a dynamic property to reflect the collapsed state
        collapsed = not self.is_nav_bar_expanded
        self.nav_bar.setProperty("navCollapsed", collapsed)
        # Switch ObjectName to allow simpler ID selectors in QSS
        self.nav_bar.setObjectName("nav_bar_collapsed" if collapsed else "nav_bar")
        
        self.nav_bar.style().unpolish(self.nav_bar)
        self.nav_bar.style().polish(self.nav_bar)

        for button in self.nav_button_group.buttons():
            if self.is_nav_bar_expanded:
                button.setText(button.property("fullText"))
            else:
                button.setText(button.property("iconChar"))
            
            # Force style update for the button to recognize parent ObjectName change
            button.style().unpolish(button)
            button.style().polish(button)
        
        self.toggle_button.setText("👈" if self.is_nav_bar_expanded else "👉")

        self.animation = QPropertyAnimation(self.nav_bar, b"minimumWidth")
        self.animation.setDuration(250)
        self.animation.setStartValue(self.nav_bar.width())
        self.animation.setEndValue(target_width)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.animation.start()

    @pyqtSlot(str, str)
    def open_save_from_selector(self, file_path_str: str, user_id: str):
        file_path = Path(file_path_str)
        current_user_id = user_id
        
        custom_backup_path = self.selector_page.get_custom_backup_path()
        
        # 标记是否是第一次尝试，用于控制错误信息的显示
        # 如果一开始就没有ID，不算是一次"失败"的尝试，直接提示输入
        first_attempt = True

        while True:
            try:
                _, platform, backup_name = self.controller.decrypt_save(file_path, current_user_id, custom_backup_path)
                
                # Success
                QMessageBox.information(self, self.loc['dialogs']['success'], 
                                        self.loc['dialogs']['decrypt_success'].format(platform=platform.upper(), backup_name=backup_name))
                self.setWindowTitle(f"{self.loc['window_title'].format(version=VERSION)} - {file_path.name}")
                
                QTimer.singleShot(0, self.refresh_all_tabs)
                self.switch_to_tab(1)  # Switch to character tab
                return # Break loop and exit

            except Exception as e:
                # Prepare dialog message
                dialog_title = self.loc['dialogs']['user_id_needed']
                dialog_msg = self.loc['dialogs']['enter_user_id']
                
                # 如果是尝试过一次（且不是因为ID为空导致的验证错误），或者ID本身就不为空但失败了
                if (not first_attempt) or (current_user_id and str(e) != "User ID cannot be empty"):
                     # 简化错误信息显示，只显示第一行关键信息
                    err_lines = str(e).split('\n')
                    short_err = err_lines[0] if err_lines else str(e)
                    
                    dialog_title = self.loc['dialogs']['decrypt_failed']
                    dialog_msg = self.loc['dialogs']['decrypt_failed_msg'].format(user_id=current_user_id, error=short_err)

                # Popup input dialog
                text, ok = QInputDialog.getText(self, dialog_title, dialog_msg, QLineEdit.EchoMode.Normal, current_user_id)
                
                if ok:
                    current_user_id = text.strip()
                    first_attempt = False
                else:
                    # User cancelled
                    # If it was a critical failure during the first automated attempt, maybe show the error?
                    # But usually cancel means "I give up".
                    if not first_attempt: # If user gave up after a retry
                        QMessageBox.warning(self, self.loc['dialogs']['cancel'], self.loc['dialogs']['open_cancelled'])
                    return

    def update_action_states(self):
        is_editor_active = self.content_stack.currentIndex() > 0
        self.save_action.setEnabled(is_editor_active)
        self.save_as_action.setEnabled(is_editor_active)

    @pyqtSlot()
    def scan_for_saves(self):
        custom_path = self.selector_page.get_custom_save_path()
        saves = self.controller.scan_save_folders(custom_path)
        self.selector_page.update_view(saves)

    def refresh_all_tabs(self):
        if not self.controller.yaml_obj: return
        self.log("Main window: Starting to refresh all tabs.")
        try:
            self.character_tab.update_fields(self.controller.get_character_data())
            self.log("  - Character tab refreshed.")
            self.items_tab.update_tree(self.controller.get_all_items())
            self.log("  - Items tab refreshed.")
            if hasattr(self, 'weapon_editor_tab'):
                self.log("  - Refreshing weapon editor tab...")
                self.weapon_editor_tab.refresh_backpack_items()
                self.log("  - Weapon editor tab refreshed.")
            self.yaml_editor_tab.set_yaml_text(self.controller.get_yaml_string())
            self.log("  - YAML editor tab refreshed.")
        except Exception as e:
            self.log(f"CRITICAL: An exception occurred during refresh_all_tabs: {e}", force_popup=True)
        self.log("Main window: Finished refreshing all tabs.")

    def log(self, message, force_popup=False):
        self.status_label.setText(message)
        if force_popup:
            QMessageBox.critical(self, self.loc['dialogs']['critical'], str(message))

    @pyqtSlot(str, str)
    def handle_add_to_backpack(self, serial_input: str, flag: str):
        if not self.controller.yaml_obj: 
            QMessageBox.warning(self, self.loc['dialogs']['no_save'], self.loc['dialogs']['load_save_first'])
            return
        
        try:
            if serial_input.strip().startswith('@U'):
                final_serial = serial_input
            else:
                encoded_serial, err = b_encoder.encode_to_base85(serial_input)
                if err:
                    QMessageBox.critical(self, self.loc['dialogs']['encode_failed'], 
                                         self.loc['dialogs']['encode_failed_msg'].format(error=err))
                    return
                final_serial = encoded_serial
            
            path = self.controller.add_item_to_backpack(final_serial, flag)
            if path:
                QMessageBox.information(self, self.loc['dialogs']['success'], self.loc['dialogs']['add_success'])
                self.refresh_all_tabs()
            else:
                QMessageBox.critical(self, self.loc['dialogs']['error'], self.loc['dialogs']['add_fail'])

        except Exception as e:
            self.log(self.loc['dialogs']['add_error'].format(error=e), force_popup=True)
    
    @pyqtSlot(dict)
    def handle_update_item(self, payload: dict):
        if not self.controller.yaml_obj:
            QMessageBox.warning(self, self.loc['dialogs']['no_save'], self.loc['dialogs']['load_save_first'])
            return
        try:
            # The controller's update_item method is designed to handle the logic 
            # of whether to re-encode based on changed data.
            msg = self.controller.update_item(
                item_path=payload['item_path'],
                original_item_data=payload['original_item_data'],
                new_item_data=payload['new_item_data']
            )
            final_msg = payload.get("success_msg", msg)
            QMessageBox.information(self, self.loc['dialogs']['success'], final_msg)
            self.refresh_all_tabs()
        except Exception as e:
            # Catch potential crashes from C-extensions and show an error dialog
            self.log(self.loc['dialogs']['update_error'].format(error=e), force_popup=True)

    @pyqtSlot(dict)
    def handle_character_update(self, data: dict):
        if not self.controller.yaml_obj: return
        paths = data.pop('cur_paths', {})
        if self.controller.apply_character_data(data, paths):
            QMessageBox.information(self, self.loc['dialogs']['success'], self.loc['dialogs']['char_applied'])
            self.refresh_all_tabs()
        else:
            QMessageBox.critical(self, self.loc['dialogs']['error'], self.loc['dialogs']['char_apply_error'])

    @pyqtSlot()
    def handle_sync_levels(self):
        if not self.controller.yaml_obj: return
        reply = QMessageBox.question(self, self.loc['dialogs']['warning'], self.loc['dialogs']['confirm_sync'], QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            success, fail, info = self.controller.sync_inventory_levels()
            msg = self.loc['dialogs']['sync_msg'].format(success=success, fail=fail)
            if fail > 0:
                details = '/n'.join(info)
                QMessageBox.warning(self, self.loc['dialogs']['sync_partial'], f"{msg}{self.loc['dialogs']['sync_fail_details'].format(details=details)}")
            else:
                QMessageBox.information(self, self.loc['dialogs']['sync_title'], msg)
            
            if success > 0: self.refresh_all_tabs()

    @pyqtSlot(str, dict)
    def handle_unlock_request(self, preset_name: str, params: dict):
        if not self.controller.yaml_obj: 
            QMessageBox.warning(self, self.loc['dialogs']['no_save'], self.loc['dialogs']['load_save_first'])
            return
        
        # Ask for confirmation? Maybe not for all, but "unlock_max_everything" is big.
        # For now, direct apply as in original tool.
        
        if self.controller.apply_unlock_preset(preset_name, params):
            QMessageBox.information(self, self.loc['dialogs']['success'], self.loc['dialogs']['preset_applied'].format(name=preset_name))
            self.refresh_all_tabs()
        else:
            QMessageBox.critical(self, self.loc['dialogs']['error'], self.loc['dialogs']['preset_fail'].format(name=preset_name))

    @pyqtSlot(str)
    def handle_yaml_update(self, yaml_string: str):
        if self.controller.update_yaml_object(yaml_string):
            self.refresh_all_tabs()

    @pyqtSlot(list, str)
    def handle_batch_add(self, lines: list, flag: str):
        if not self.controller.yaml_obj:
            QMessageBox.critical(self, self.loc['dialogs']['no_save'], self.loc['dialogs']['decrypt_save_first'])
            self.converter_tab.finalize_batch_add(0, 0)
            return

        self.batch_add_thread = QThread()
        self.batch_add_worker = BatchAddWorker(self.controller, lines, flag)
        self.batch_add_worker.moveToThread(self.batch_add_thread)

        self.batch_add_thread.started.connect(self.batch_add_worker.run)
        self.batch_add_worker.finished.connect(self.on_batch_add_finished)
        self.batch_add_worker.progress.connect(self.converter_tab.update_batch_add_status)

        self.batch_add_worker.finished.connect(self.batch_add_thread.quit)
        self.batch_add_worker.finished.connect(self.batch_add_worker.deleteLater)
        self.batch_add_thread.finished.connect(self.batch_add_thread.deleteLater)
        
        self.batch_add_thread.start()

    def on_batch_add_finished(self, success_count, fail_count):
        self.converter_tab.finalize_batch_add(success_count, fail_count)
        if success_count > 0:
            QMessageBox.information(self, self.loc['dialogs']['batch_complete'], 
                                    self.loc['dialogs']['batch_success'].format(count=success_count))
            self.refresh_all_tabs()
        else:
            QMessageBox.warning(self, self.loc['dialogs']['batch_fail'], 
                                self.loc['dialogs']['batch_fail_msg'].format(count=fail_count))

    def _start_iterator_worker(self, params, add_to_backpack=False):
        if not self.controller.yaml_obj and add_to_backpack:
            QMessageBox.critical(self, self.loc['dialogs']['no_save'], self.loc['dialogs']['decrypt_save_first'])
            self.converter_tab.finalize_iterator_add_to_backpack(0,0)
            return

        params['add_to_backpack'] = add_to_backpack
        self.iterator_thread = QThread()
        self.iterator_worker = IteratorWorker(self.controller, params, self.loc['worker'])
        self.iterator_worker.moveToThread(self.iterator_thread)

        self.iterator_thread.started.connect(self.iterator_worker.run)
        self.iterator_worker.status_update.connect(self.converter_tab.update_iterator_status)

        if add_to_backpack:
            self.iterator_worker.finished_add_to_backpack.connect(self.on_iterator_add_finished)
        else:
            self.iterator_worker.finished_generation.connect(self.converter_tab.finalize_iterator_processing)

        self.iterator_worker.finished_generation.connect(self.iterator_thread.quit)
        self.iterator_worker.finished_add_to_backpack.connect(self.iterator_thread.quit)
        self.iterator_worker.finished_generation.connect(self.iterator_worker.deleteLater)
        self.iterator_worker.finished_add_to_backpack.connect(self.iterator_worker.deleteLater)
        self.iterator_thread.finished.connect(self.iterator_thread.deleteLater)
        
        self.iterator_thread.start()

    @pyqtSlot(dict)
    def handle_iterator_request(self, params: dict):
        self._start_iterator_worker(params, add_to_backpack=False)

    @pyqtSlot(dict)
    def handle_iterator_add_to_backpack(self, params: dict):
        self._start_iterator_worker(params, add_to_backpack=True)

    def on_iterator_add_finished(self, success, fail):
        self.converter_tab.finalize_iterator_add_to_backpack(success, fail)
        if success > 0:
            QMessageBox.information(self, self.loc['dialogs']['iter_complete'], 
                                    self.loc['dialogs']['iter_success'].format(count=success))
            self.refresh_all_tabs()
        else:
            QMessageBox.warning(self, self.loc['dialogs']['iter_fail'], 
                                self.loc['dialogs']['iter_fail_msg'].format(count=fail))
            
    @pyqtSlot(bool)
    def encrypt_and_save(self, save_as=False):
        if not self.controller.yaml_obj: return
        
        path_to_save = self.controller.save_path
        if save_as or not path_to_save:
            path, _ = QFileDialog.getSaveFileName(self, self.loc['dialogs']['save_encrypted_title'], str(path_to_save), "BL4 存档 (*.sav)")
            if not path: return
            path_to_save = Path(path)
        
        try:
            data = self.controller.encrypt_save(self.controller.get_yaml_string())
            path_to_save.write_bytes(data)
            QMessageBox.information(self, self.loc['dialogs']['success'], 
                                    self.loc['dialogs']['save_saved'].format(path=path_to_save))
        except Exception as e:
            QMessageBox.critical(self, self.loc['dialogs']['encrypt_failed'], str(e))

    def _get_lang_button_text(self):
        code_map = {
            'zh-CN': "CN",
            'en-US': "EN",
            'ru': "RU",
            'ua': "UA"
        }
        return f"🌐 {code_map.get(self.current_language, 'EN')}"

    def change_language(self, lang_code):
        if self.current_language == lang_code:
            return

        print(f"DEBUG: change_language started. New: {lang_code}")
        self.current_language = lang_code
        
        # Update backend localization
        bl4f.set_language(self.current_language)

        self.lang_button.setText(self._get_lang_button_text())
        
        self._load_localization()
        self.update_ui_text()
        
        # Update tabs
        tabs_to_update = [
            self.grenade_tab, self.shield_tab, self.repkit_tab, self.heavy_weapon_tab, 
            self.weapon_editor_tab, self.weapon_generator_tab,
            self.character_tab, self.selector_page, self.items_tab, self.converter_tab,
            self.yaml_editor_tab, self.class_mod_tab, self.enhancement_tab
        ]
        for tab in tabs_to_update:
            if hasattr(tab, 'update_language'):
                print(f"DEBUG: Updating language for tab {tab.__class__.__name__}")
                try:
                    tab.update_language(self.current_language)
                    print(f"DEBUG: Updated language for tab {tab.__class__.__name__}")
                except Exception as e:
                    print(f"DEBUG: Error updating language for tab {tab.__class__.__name__}: {e}")
        
        # Refresh all tabs to re-fetch items with new localization
        self.refresh_all_tabs()
        
        print("DEBUG: change_language finished")
        
    def update_ui_text(self):
        self.setWindowTitle(self.loc['window_title'])
        self.header_bar.findChild(QLabel, "titleLabel").setText(self.loc['header']['title'])
        self.header_bar.findChild(QLabel, "subtitleLabel").setText(self.loc['subtitle'])
        self.open_button.setText(self.loc['header']['open'])
        self.save_button.setText(self.loc['header']['save'])
        self.save_as_button.setText(self.loc['header']['save_as'])
        self.open_action.setText(self.loc['menu']['open_selector'])
        self.save_action.setText(self.loc['menu']['save'])
        self.save_as_action.setText(self.loc['menu']['save_as'])
        self.status_label.setText(self.loc['status']['welcome'])
        self.lang_button.setText(self._get_lang_button_text())
        
        # Update tab titles
        tab_keys = [
            'select_save', 'character', 'items', 'converter', 'yaml_editor',
            'class_mod', 'enhancement', 'weapon_editor', 'weapon_generator',
            'grenade', 'shield', 'repkit', 'heavy_weapon'
        ]

        for i, key in enumerate(tab_keys):
            button = self.nav_button_group.button(i)
            if button:
                icon_char = button.property("iconChar")
                new_full_text = f" {icon_char}   {self.loc['tabs'][key]}"
                button.setProperty("fullText", new_full_text)
                if self.is_nav_bar_expanded:
                    button.setText(new_full_text)
                else:
                    # If collapsed, ensure we only show the icon (though it should already be correct)
                    button.setText(icon_char)

    def _apply_themed_stylesheet(self):
        """Apply the themed stylesheet from ThemeManager."""
        stylesheet = self.theme_manager.get_stylesheet()
        if stylesheet:
            self.setStyleSheet(stylesheet)
        else:
            print("Warning: stylesheet.qss not found or failed to load.")

    def toggle_theme(self):
        """Toggle between dark and light themes."""
        self.theme_manager.toggle_theme()
        self._apply_themed_stylesheet()
        self._update_theme_button()

    def _get_theme_tooltip(self):
        """Get the tooltip text for the theme button."""
        if self.theme_manager.is_dark():
            return self.loc.get('header', {}).get('theme_light', 'Switch to Light Mode')
        else:
            return self.loc.get('header', {}).get('theme_dark', 'Switch to Dark Mode')

    def _update_theme_button(self):
        """Update the theme button icon and tooltip."""
        self.theme_button.setText(self.theme_manager.get_theme_icon())
        self.theme_button.setToolTip(self._get_theme_tooltip())

def main():
    app = QApplication(sys.argv)
    icon_path = resource_loader.get_resource_path("BL4.ico")
    if icon_path:
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
