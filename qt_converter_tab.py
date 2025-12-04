import time
import itertools
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QTextEdit, QMessageBox, QFileDialog, QComboBox,
    QCheckBox, QScrollArea
)
from PyQt6.QtCore import pyqtSignal, QTimer, Qt, QObject, QThread

import decoder_logic
import b_encoder
import resource_loader

class BatchConverterWorker(QObject):
    """后台工作线程，用于批量转换"""
    progress = pyqtSignal(int, int) # current, total
    finished = pyqtSignal(list)
    
    def __init__(self, lines, loc_data=None):
        super().__init__()
        self.lines = lines
        self.loc = loc_data

    def run(self):
        results = []
        total = len(self.lines)
        err_prefix = "Error: "
        crit_prefix = "Critical Error: "
        
        if self.loc:
            # Extract simple prefixes if possible, or just use default English
            # Since loc has templates like "状态: 错误: {error}", we just want "错误: "
            pass 

        for i, line in enumerate(self.lines):
            mode = 'deserialize' if line.strip().startswith('@U') else 'serialize'
            try:
                if mode == 'deserialize':
                    result, _, error = decoder_logic.decode_serial_to_string(line)
                else: # serialize
                    result, error = b_encoder.encode_to_base85(line)
                
                output = result if not error else f"{err_prefix}{error}"
            except Exception as e:
                output = f"{crit_prefix}{e}"
            results.append(output)
            self.progress.emit(i + 1, total)
            time.sleep(0.01) # 避免UI完全冻结
        self.finished.emit(results)


class QtConverterTab(QWidget):
    batch_add_requested = pyqtSignal(list, str)
    iterator_requested = pyqtSignal(dict)
    iterator_add_to_backpack_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        self._load_localization()
        
        self.ui_labels = {}
        self.ui_buttons = {}
        self.ui_groups = {}
        self.ui_placeholders = {}
        self.ui_checkboxes = {}

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        
        container_widget = QWidget()
        scroll_area.setWidget(container_widget)
        
        main_layout = QVBoxLayout(container_widget)

        # The main layout for the tab itself, which will only contain the scroll area
        tab_layout = QVBoxLayout(self)
        tab_layout.addWidget(scroll_area)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- Single Converter ---
        self._create_single_converter_group(main_layout)

        # --- Batch Converter ---
        self._create_batch_converter_group(main_layout)

        # --- Batch Add to Backpack ---
        self._create_batch_add_group(main_layout)
        
        # --- Iterator ---
        self._create_iterator_group(main_layout)

        main_layout.addStretch()
        self.update_iterator_ui()

    def _create_single_converter_group(self, main_layout):
        self.ui_groups['single'] = QGroupBox(self.loc['groups']['single'])
        single_layout = QGridLayout(self.ui_groups['single'])
        
        self.ui_labels['base85'] = QLabel(self.loc['labels']['base85'])
        single_layout.addWidget(self.ui_labels['base85'], 0, 0)
        
        self.base85_input = QLineEdit()
        self.base85_input.setPlaceholderText(self.loc['placeholders']['base85'])
        self.base85_input.textChanged.connect(self.on_single_input_changed)
        self.ui_placeholders['base85_input'] = self.base85_input
        single_layout.addWidget(self.base85_input, 0, 1)

        self.ui_labels['deserialize'] = QLabel(self.loc['labels']['deserialize'])
        single_layout.addWidget(self.ui_labels['deserialize'], 1, 0)
        
        self.deserialized_input = QLineEdit()
        self.deserialized_input.setPlaceholderText(self.loc['placeholders']['deserialize'])
        self.deserialized_input.textChanged.connect(self.on_single_input_changed)
        self.ui_placeholders['deserialized_input'] = self.deserialized_input
        single_layout.addWidget(self.deserialized_input, 1, 1)

        self.single_status_label = QLabel(self.loc['labels']['status_ready'])
        self.ui_labels['single_status'] = self.single_status_label # Track status label
        single_layout.addWidget(self.single_status_label, 2, 0)

        self.ui_buttons['clear'] = QPushButton(self.loc['buttons']['clear'])
        self.ui_buttons['clear'].clicked.connect(self.clear_single_converter)
        single_layout.addWidget(self.ui_buttons['clear'], 2, 1, alignment=Qt.AlignmentFlag.AlignRight)

        main_layout.addWidget(self.ui_groups['single'])
        
        # Debounce timer for single converter
        self.debounce_timer = QTimer(self)
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.timeout.connect(self.perform_single_conversion)
        self.active_input_widget = None

    def _create_batch_converter_group(self, main_layout):
        self.ui_groups['batch'] = QGroupBox(self.loc['groups']['batch'])
        batch_layout = QGridLayout(self.ui_groups['batch'])

        self.ui_labels['input_batch'] = QLabel(self.loc['labels']['input_batch'])
        batch_layout.addWidget(self.ui_labels['input_batch'], 0, 0)
        
        self.batch_input = QTextEdit()
        self.batch_input.setMinimumHeight(200)
        batch_layout.addWidget(self.batch_input, 1, 0)

        output_header_layout = QHBoxLayout()
        self.ui_labels['output'] = QLabel(self.loc['labels']['output'])
        output_header_layout.addWidget(self.ui_labels['output'])
        output_header_layout.addStretch()
        
        self.ui_buttons['export_txt'] = QPushButton(self.loc['buttons']['export_txt'])
        self.ui_buttons['export_txt'].clicked.connect(self.export_batch_results)
        output_header_layout.addWidget(self.ui_buttons['export_txt'])
        batch_layout.addLayout(output_header_layout, 0, 1)

        self.batch_output = QTextEdit()
        self.batch_output.setReadOnly(True)
        self.batch_output.setMinimumHeight(200)
        batch_layout.addWidget(self.batch_output, 1, 1)

        self.batch_process_btn = QPushButton(self.loc['buttons']['start_batch'])
        self.batch_process_btn.clicked.connect(self.start_batch_processing)
        self.ui_buttons['start_batch'] = self.batch_process_btn
        batch_layout.addWidget(self.batch_process_btn, 2, 0, 1, 2)
        
        self.batch_status_label = QLabel(self.loc['labels']['status_ready'])
        self.ui_labels['batch_status'] = self.batch_status_label # Track status label
        batch_layout.addWidget(self.batch_status_label, 3, 0, 1, 2)

        main_layout.addWidget(self.ui_groups['batch'])

    def _create_batch_add_group(self, main_layout):
        self.ui_groups['batch_add'] = QGroupBox(self.loc['groups']['batch_add'])
        layout = QVBoxLayout(self.ui_groups['batch_add'])

        self.ui_labels['input_batch_add'] = QLabel(self.loc['labels']['input_batch_add'])
        layout.addWidget(self.ui_labels['input_batch_add'])
        
        self.batch_add_input = QTextEdit()
        self.batch_add_input.setMinimumHeight(150)
        layout.addWidget(self.batch_add_input)

        controls_layout = QHBoxLayout()
        self.batch_add_btn = QPushButton(self.loc['buttons']['batch_add'])
        self.batch_add_btn.clicked.connect(self.start_batch_add)
        self.ui_buttons['batch_add'] = self.batch_add_btn
        controls_layout.addWidget(self.batch_add_btn)
        
        controls_layout.addStretch()
        
        self.ui_labels['select_flag'] = QLabel(self.loc['labels']['select_flag'])
        controls_layout.addWidget(self.ui_labels['select_flag'])
        
        self.batch_add_flag_combo = QComboBox()
        self._populate_batch_flags()
        controls_layout.addWidget(self.batch_add_flag_combo)
        layout.addLayout(controls_layout)

        self.batch_add_status_label = QLabel(self.loc['labels']['status_ready'])
        self.ui_labels['batch_add_status'] = self.batch_add_status_label # Track status label
        layout.addWidget(self.batch_add_status_label)

        main_layout.addWidget(self.ui_groups['batch_add'])
    
    def _populate_batch_flags(self):
        self.batch_add_flag_combo.clear()
        flags = self.loc['flags']
        flag_values = [flags["1"], flags["3"], flags["5"], flags["17"], flags["33"], flags["65"], flags["129"]]
        self.batch_add_flag_combo.addItems(flag_values)
        self.batch_add_flag_combo.setCurrentText(flags["3"])

    def on_single_input_changed(self):
        sender = self.sender()
        if not self.base85_input.signalsBlocked() and not self.deserialized_input.signalsBlocked():
            self.active_input_widget = sender
            self.debounce_timer.start(300) # 300ms delay

    def perform_single_conversion(self):
        if self.active_input_widget is self.base85_input:
            source_widget, target_widget = self.base85_input, self.deserialized_input
            mode = "deserialize"
        elif self.active_input_widget is self.deserialized_input:
            source_widget, target_widget = self.deserialized_input, self.base85_input
            mode = "serialize"
        else:
            return

        value = source_widget.text().strip()
        
        # Block signals to prevent feedback loop
        target_widget.blockSignals(True)

        if not value:
            target_widget.clear()
            self.single_status_label.setText(self.loc['labels']['status_ready'])
            target_widget.blockSignals(False)
            return

        self.single_status_label.setText(self.loc['labels']['status_processing'])
        
        try:
            if mode == 'deserialize':
                result, _, error = decoder_logic.decode_serial_to_string(value)
            else: # serialize
                result, error = b_encoder.encode_to_base85(value)
            
            if error:
                self.single_status_label.setText(self.loc['labels']['status_error'].format(error=error))
                self.single_status_label.setStyleSheet("color: red;")
                target_widget.clear()
            else:
                target_widget.setText(result)
                self.single_status_label.setText(self.loc['labels']['status_success'])
                self.single_status_label.setStyleSheet("color: green;")
        except Exception as e:
            self.single_status_label.setText(self.loc['labels']['status_critical'].format(error=e))
            self.single_status_label.setStyleSheet("color: red;")
            target_widget.clear()
        finally:
            target_widget.blockSignals(False)

    def start_batch_processing(self):
        lines = [line.strip() for line in self.batch_input.toPlainText().split('\n') if line.strip()]
        if not lines:
            self.batch_status_label.setText(self.loc['labels']['status_empty'])
            return

        self.batch_process_btn.setEnabled(False)
        self.batch_process_btn.setText(self.loc['buttons']['processing'])
        self.batch_output.clear()
        
        self.thread = QThread()
        self.worker = BatchConverterWorker(lines, self.loc['labels'])
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_batch_finished)
        self.worker.progress.connect(self.on_batch_progress)
        
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()

    def on_batch_progress(self, current, total):
        self.batch_status_label.setText(self.loc['labels']['status_progress'].format(current=current, total=total))

    def on_batch_finished(self, results):
        self.batch_output.setText('\n'.join(results))
        self.batch_status_label.setText(self.loc['labels']['status_complete'])
        self.batch_process_btn.setEnabled(True)
        self.batch_process_btn.setText(self.loc['buttons']['start_batch'])

    def export_batch_results(self):
        content = self.batch_output.toPlainText()
        if not content:
            QMessageBox.warning(self, self.loc['dialogs']['no_content'], self.loc['dialogs']['no_export'])
            return
        
        filepath, _ = QFileDialog.getSaveFileName(self, self.loc['dialogs']['export_batch_title'], "", "Text Files (*.txt);;All Files (*)")
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                QMessageBox.information(self, self.loc['dialogs']['success'], self.loc['dialogs']['export_success'].format(path=filepath))
            except Exception as e:
                QMessageBox.critical(self, self.loc['dialogs']['export_fail'], self.loc['dialogs']['write_fail'].format(error=e))

    def clear_single_converter(self):
        self.base85_input.blockSignals(True)
        self.deserialized_input.blockSignals(True)
        
        self.base85_input.clear()
        self.deserialized_input.clear()
        self.single_status_label.setText(self.loc['labels']['status_ready'])
        self.single_status_label.setStyleSheet("") # Reset color
        
        self.base85_input.blockSignals(False)
        self.deserialized_input.blockSignals(False)

    def start_batch_add(self):
        lines = [line.strip() for line in self.batch_add_input.toPlainText().split('\n') if line.strip()]
        if not lines:
            QMessageBox.warning(self, self.loc['dialogs']['no_input'], self.loc['dialogs']['batch_add_empty'])
            return
        
        flag = self.batch_add_flag_combo.currentText().split(" ")[0]
        self.batch_add_btn.setEnabled(False)
        self.batch_add_btn.setText(self.loc['buttons']['adding'])
        self.batch_add_status_label.setText(self.loc['labels']['status_prepare'])
        
        self.batch_add_requested.emit(lines, flag)

    def update_batch_add_status(self, current, total, success_count, fail_count):
        self.batch_add_status_label.setText(self.loc['labels']['status_batch_add_progress'].format(current=current, total=total, success=success_count, fail=fail_count))

    def finalize_batch_add(self, success_count, fail_count):
        self.batch_add_status_label.setText(self.loc['labels']['status_batch_add_complete'].format(success=success_count, fail=fail_count))
        self.batch_add_btn.setEnabled(True)
        self.batch_add_btn.setText(self.loc['buttons']['batch_add'])

    def _create_iterator_group(self, main_layout):
        self.ui_groups['iterator'] = QGroupBox(self.loc['groups']['iterator'])
        layout = QVBoxLayout(self.ui_groups['iterator'])
        
        # --- Base Data ---
        self.ui_labels['base_data'] = QLabel(self.loc['labels']['base_data'])
        layout.addWidget(self.ui_labels['base_data'])
        self.iterator_base = QLineEdit('255, 0, 1, 50| 2, 969|| ')
        layout.addWidget(self.iterator_base)

        # --- Normal Iterator ---
        normal_iterator_layout = QGridLayout()
        self.ui_labels['iter_start'] = QLabel(self.loc['labels']['iter_start'])
        normal_iterator_layout.addWidget(self.ui_labels['iter_start'], 0, 0)
        self.iterator_start = QLineEdit("1")
        normal_iterator_layout.addWidget(self.iterator_start, 1, 0)
        self.ui_labels['iter_end'] = QLabel(self.loc['labels']['iter_end'])
        normal_iterator_layout.addWidget(self.ui_labels['iter_end'], 0, 1)
        self.iterator_end = QLineEdit("99")
        normal_iterator_layout.addWidget(self.iterator_end, 1, 1)
        layout.addLayout(normal_iterator_layout)

        # --- Special Format ---
        self.special_format_check = QCheckBox(self.loc['checkboxes']['special_format'])
        self.special_format_check.clicked.connect(self.update_iterator_ui)
        self.ui_checkboxes['special_format'] = self.special_format_check
        layout.addWidget(self.special_format_check)
        
        self.special_format_options = QWidget()
        special_options_layout = QHBoxLayout(self.special_format_options)
        self.ui_labels['special_base'] = QLabel(self.loc['labels']['special_base'])
        special_options_layout.addWidget(self.ui_labels['special_base'])
        self.iterator_special_base = QLineEdit("245")
        special_options_layout.addWidget(self.iterator_special_base)
        
        # New Special Combo Checkbox and Input
        self.special_combo_check = QCheckBox(self.loc['checkboxes']['special_combo'])
        self.special_combo_check.clicked.connect(self.update_iterator_ui)
        self.ui_checkboxes['special_combo'] = self.special_combo_check
        special_options_layout.addWidget(self.special_combo_check)

        self.ui_labels['special_combo_input'] = QLabel(self.loc['labels']['special_combo_input'])
        special_options_layout.addWidget(self.ui_labels['special_combo_input'])
        
        self.special_combo_input = QLineEdit()
        self.special_combo_input.setPlaceholderText("98 99")
        self.ui_placeholders['special_combo_input'] = self.special_combo_input
        special_options_layout.addWidget(self.special_combo_input)

        special_options_layout.addStretch()
        layout.addWidget(self.special_format_options)

        # --- Modes ---
        mode_layout = QHBoxLayout()
        self.skin_mode_check = QCheckBox(self.loc['checkboxes']['skin_mode'])
        self.skin_mode_check.clicked.connect(self.update_iterator_ui)
        self.ui_checkboxes['skin_mode'] = self.skin_mode_check
        mode_layout.addWidget(self.skin_mode_check)
        
        self.combination_mode_check = QCheckBox(self.loc['checkboxes']['combo_mode'])
        self.combination_mode_check.clicked.connect(self.update_iterator_ui)
        self.ui_checkboxes['combo_mode'] = self.combination_mode_check
        mode_layout.addWidget(self.combination_mode_check)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)

        # --- Combination Options ---
        self.combination_options = QWidget()
        combo_options_layout = QGridLayout(self.combination_options)
        self.ui_labels['combo_start'] = QLabel(self.loc['labels']['combo_start'])
        combo_options_layout.addWidget(self.ui_labels['combo_start'], 0, 0)
        self.combination_start = QLineEdit("1")
        combo_options_layout.addWidget(self.combination_start, 1, 0)
        
        self.ui_labels['combo_end'] = QLabel(self.loc['labels']['combo_end'])
        combo_options_layout.addWidget(self.ui_labels['combo_end'], 0, 1)
        self.combination_end = QLineEdit("10")
        combo_options_layout.addWidget(self.combination_end, 1, 1)
        
        self.ui_labels['combo_size'] = QLabel(self.loc['labels']['combo_size'])
        combo_options_layout.addWidget(self.ui_labels['combo_size'], 0, 2)
        self.combination_size = QLineEdit("2")
        combo_options_layout.addWidget(self.combination_size, 1, 2)
        layout.addWidget(self.combination_options)

        # --- YAML Output ---
        yaml_layout = QHBoxLayout()
        self.yaml_format_check = QCheckBox(self.loc['checkboxes']['yaml_format'])
        self.yaml_format_check.clicked.connect(self.update_iterator_ui)
        self.ui_checkboxes['yaml_format'] = self.yaml_format_check
        yaml_layout.addWidget(self.yaml_format_check)
        
        self.yaml_flag_label = QLabel(self.loc['labels']['select_flag'])
        self.ui_labels['yaml_flag'] = self.yaml_flag_label
        yaml_layout.addWidget(self.yaml_flag_label)
        
        self.yaml_flag_combo = QComboBox()
        self._populate_yaml_flags()
        yaml_layout.addWidget(self.yaml_flag_combo)
        yaml_layout.addStretch()
        layout.addLayout(yaml_layout)

        # --- Results and Buttons ---
        self.ui_labels['generated_result'] = QLabel(self.loc['labels']['generated_result'])
        layout.addWidget(self.ui_labels['generated_result'])
        self.iterator_output = QTextEdit()
        self.iterator_output.setReadOnly(True)
        self.iterator_output.setMinimumHeight(200)
        layout.addWidget(self.iterator_output)
        
        button_layout = QHBoxLayout()
        self.iterator_start_btn = QPushButton(self.loc['buttons']['start_iter'])
        self.iterator_start_btn.clicked.connect(self.start_iterator_processing)
        self.ui_buttons['start_iter'] = self.iterator_start_btn
        button_layout.addWidget(self.iterator_start_btn)
        
        self.iterator_export_btn = QPushButton(self.loc['buttons']['export_result'])
        self.iterator_export_btn.clicked.connect(self.export_iterator_results)
        self.ui_buttons['export_result'] = self.iterator_export_btn
        button_layout.addWidget(self.iterator_export_btn)
        
        self.iterator_add_to_backpack_btn = QPushButton(self.loc['buttons']['gen_write'])
        self.iterator_add_to_backpack_btn.clicked.connect(self.start_iterator_add_to_backpack)
        self.ui_buttons['gen_write'] = self.iterator_add_to_backpack_btn
        button_layout.addWidget(self.iterator_add_to_backpack_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.iterator_status_label = QLabel(self.loc['labels']['status_ready'])
        self.ui_labels['iterator_status'] = self.iterator_status_label # Track status label
        layout.addWidget(self.iterator_status_label)

        main_layout.addWidget(self.ui_groups['iterator'])

    def _populate_yaml_flags(self):
        self.yaml_flag_combo.clear()
        flags = self.loc['flags']
        flag_values = [flags["1"], flags["3"], flags["5"], flags["17"], flags["33"], flags["65"], flags["129"]]
        self.yaml_flag_combo.addItems(flag_values)
        self.yaml_flag_combo.setCurrentText(flags["33"])

    def update_iterator_ui(self):
        is_skin = self.skin_mode_check.isChecked()
        is_combo = self.combination_mode_check.isChecked()
        is_yaml = self.yaml_format_check.isChecked()

        if self.sender() == self.skin_mode_check and is_skin:
            self.combination_mode_check.setChecked(False)
            is_combo = False
        if self.sender() == self.combination_mode_check and is_combo:
            self.skin_mode_check.setChecked(False)
            is_skin = False

        iterator_enabled = not is_combo
        self.iterator_start.setEnabled(iterator_enabled)
        self.iterator_end.setEnabled(iterator_enabled)

        special_format_enabled = not is_skin and not is_combo
        self.special_format_check.setEnabled(special_format_enabled)
        if not special_format_enabled:
            self.special_format_check.setChecked(False)
        
        self.special_format_options.setVisible(self.special_format_check.isChecked() and special_format_enabled)
        
        is_special_combo = self.special_combo_check.isChecked()
        self.ui_labels['special_combo_input'].setVisible(is_special_combo)
        self.special_combo_input.setVisible(is_special_combo)
        
        self.combination_options.setVisible(is_combo)
        
        self.yaml_flag_label.setVisible(is_yaml)
        self.yaml_flag_combo.setVisible(is_yaml)

        self.iterator_start_btn.setVisible(not is_yaml)
        self.iterator_add_to_backpack_btn.setVisible(is_yaml)

    def start_iterator_processing(self):
        params = self._get_iterator_params()
        self.iterator_start_btn.setEnabled(False)
        self.iterator_start_btn.setText(self.loc['buttons']['generating'])
        self.iterator_output.clear()
        self.iterator_status_label.setText(self.loc['labels']['status_generating'])
        self.iterator_requested.emit(params)

    def start_iterator_add_to_backpack(self):
        params = self._get_iterator_params()
        self.iterator_add_to_backpack_btn.setEnabled(False)
        self.iterator_add_to_backpack_btn.setText(self.loc['buttons']['gen_writing'])
        self.iterator_status_label.setText(self.loc['labels']['status_prepare'])
        self.iterator_add_to_backpack_requested.emit(params)

    def _get_iterator_params(self):
        return {
            "base_data": self.iterator_base.text(),
            "is_yaml": self.yaml_format_check.isChecked(),
            "yaml_flag": self.yaml_flag_combo.currentText().split(" ")[0],
            "is_special": self.special_format_check.isChecked(),
            "special_base": self.iterator_special_base.text(),
            "is_special_combo": self.special_combo_check.isChecked(),
            "special_combo_text": self.special_combo_input.text(),
            "is_skin": self.skin_mode_check.isChecked(),
            "is_combo": self.combination_mode_check.isChecked(),
            "start": self.iterator_start.text(),
            "end": self.iterator_end.text(),
            "combo_start": self.combination_start.text(),
            "combo_end": self.combination_end.text(),
            "combo_size": self.combination_size.text()
        }

    def update_iterator_status(self, message):
        self.iterator_status_label.setText(f"Status: {message}") # Simplified as message often comes localized or as data

    def finalize_iterator_processing(self, result_text):
        self.iterator_output.setText(result_text)
        self.iterator_start_btn.setEnabled(True)
        self.iterator_start_btn.setText(self.loc['buttons']['start_iter'])
        self.iterator_status_label.setText(self.loc['labels']['status_gen_complete'])

    def finalize_iterator_add_to_backpack(self, success, fail):
        self.iterator_add_to_backpack_btn.setEnabled(True)
        self.iterator_add_to_backpack_btn.setText(self.loc['buttons']['gen_write'])
        self.iterator_status_label.setText(self.loc['labels']['status_batch_add_complete'].format(success=success, fail=fail))

    def export_iterator_results(self):
        content = self.iterator_output.toPlainText()
        if not content:
            QMessageBox.warning(self, self.loc['dialogs']['no_content'], self.loc['dialogs']['no_export'])
            return
        
        is_yaml = self.yaml_format_check.isChecked()
        ext = ".yaml" if is_yaml else ".txt"
        title = self.loc['dialogs']['export_yaml'] if is_yaml else self.loc['dialogs']['export_txt_title']
        
        filepath, _ = QFileDialog.getSaveFileName(self, title, "", f"{title}(*{ext});;All Files (*)")
        if filepath:
            if not is_yaml:
                reply = QMessageBox.question(self, self.loc['dialogs']['export_opts'], self.loc['dialogs']['only_base85'], 
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
                if reply == QMessageBox.StandardButton.Cancel:
                    return
                if reply == QMessageBox.StandardButton.Yes:
                    content = '\n'.join([line.split('-->')[1].strip() for line in content.strip().split('\n') if '-->' in line])
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                QMessageBox.information(self, self.loc['dialogs']['success'], self.loc['dialogs']['export_success'].format(path=filepath))
            except Exception as e:
                QMessageBox.critical(self, self.loc['dialogs']['export_fail'], self.loc['dialogs']['write_fail'].format(error=e))
    
    def _load_localization(self):
        filename = resource_loader.get_ui_localization_file(self.current_lang)
        data = resource_loader.load_json_resource(filename)
        if data and "converter_tab" in data:
            self.loc = data["converter_tab"]
        else:
            # Fallback
            self.loc = {
                "groups": {"single": "Single", "batch": "Batch", "batch_add": "Batch Add", "iterator": "Iterator"},
                "labels": {"base85": "Base85:", "deserialize": "Deserialize:", "status_ready": "Ready", "input_batch": "Input:", "output": "Output:", 
                           "status_processing": "Processing...", "status_error": "Error: {error}", "status_success": "Success!", "status_critical": "Critical Error: {error}",
                           "status_empty": "Empty input.", "status_progress": "Processing {current}/{total}...", "status_complete": "Complete!", "input_batch_add": "Input:",
                           "select_flag": "Flag:", "status_prepare": "Preparing...", "status_batch_add_progress": "Progress: {current}/{total}", "status_batch_add_complete": "Complete",
                           "base_data": "Base Data:", "iter_start": "Start:", "iter_end": "End:", "special_base": "Special Base:", "combo_start": "Combo Start:", "combo_end": "Combo End:",
                           "combo_size": "Size:", "generated_result": "Result:", "special_combo_input": "Combo Input:", "status_generating": "Generating...", "status_gen_complete": "Generation Complete!"},
                "placeholders": {"base85": "Enter Base85...", "deserialize": "Enter deserialized..."},
                "buttons": {"clear": "Clear", "export_txt": "Export .txt", "start_batch": "Start Batch", "batch_add": "Batch Add", "adding": "Adding...", "processing": "Processing...",
                            "start_iter": "Start Iterator", "export_result": "Export Result", "gen_write": "Generate & Write", "generating": "Generating...", "gen_writing": "Writing..."},
                "checkboxes": {"special_format": "Special Format", "skin_mode": "Skin Mode", "combo_mode": "Combo Mode", "special_combo": "Special Combo", "yaml_format": "YAML Format"},
                "flags": {"1": "1", "3": "3", "5": "5", "17": "17", "33": "33", "65": "65", "129": "129"},
                "dialogs": {"no_content": "No content", "no_export": "Nothing to export", "export_batch_title": "Export", "success": "Success", "export_success": "Saved to {path}", "export_fail": "Failed",
                            "write_fail": "Write failed: {error}", "no_input": "No input", "batch_add_empty": "Input empty", "export_yaml": "Export YAML", "export_txt_title": "Export TXT",
                            "export_opts": "Options", "only_base85": "Base85 only?"}
            }

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self._load_localization()
        
        # Groups
        self.ui_groups['single'].setTitle(self.loc['groups']['single'])
        self.ui_groups['batch'].setTitle(self.loc['groups']['batch'])
        self.ui_groups['batch_add'].setTitle(self.loc['groups']['batch_add'])
        self.ui_groups['iterator'].setTitle(self.loc['groups']['iterator'])
        
        # Labels
        self.ui_labels['base85'].setText(self.loc['labels']['base85'])
        self.ui_labels['deserialize'].setText(self.loc['labels']['deserialize'])
        self.ui_labels['input_batch'].setText(self.loc['labels']['input_batch'])
        self.ui_labels['output'].setText(self.loc['labels']['output'])
        self.ui_labels['input_batch_add'].setText(self.loc['labels']['input_batch_add'])
        self.ui_labels['select_flag'].setText(self.loc['labels']['select_flag'])
        self.ui_labels['base_data'].setText(self.loc['labels']['base_data'])
        self.ui_labels['iter_start'].setText(self.loc['labels']['iter_start'])
        self.ui_labels['iter_end'].setText(self.loc['labels']['iter_end'])
        self.ui_labels['special_base'].setText(self.loc['labels']['special_base'])
        self.ui_labels['combo_start'].setText(self.loc['labels']['combo_start'])
        self.ui_labels['combo_end'].setText(self.loc['labels']['combo_end'])
        self.ui_labels['combo_size'].setText(self.loc['labels']['combo_size'])
        self.ui_labels['yaml_flag'].setText(self.loc['labels']['select_flag'])
        self.ui_labels['generated_result'].setText(self.loc['labels']['generated_result'])
        self.ui_labels['special_combo_input'].setText(self.loc['labels']['special_combo_input'])
        
        # Update status labels to "Ready" or localized equivalent of their current state if simple
        for key in ['single_status', 'batch_status', 'batch_add_status', 'iterator_status']:
            if key in self.ui_labels:
                self.ui_labels[key].setText(self.loc['labels']['status_ready'])

        # Placeholders
        self.ui_placeholders['base85_input'].setPlaceholderText(self.loc['placeholders']['base85'])
        self.ui_placeholders['deserialized_input'].setPlaceholderText(self.loc['placeholders']['deserialize'])
        
        # Buttons
        self.ui_buttons['clear'].setText(self.loc['buttons']['clear'])
        self.ui_buttons['export_txt'].setText(self.loc['buttons']['export_txt'])
        self.ui_buttons['start_batch'].setText(self.loc['buttons']['start_batch'])
        self.ui_buttons['batch_add'].setText(self.loc['buttons']['batch_add'])
        self.ui_buttons['start_iter'].setText(self.loc['buttons']['start_iter'])
        self.ui_buttons['export_result'].setText(self.loc['buttons']['export_result'])
        self.ui_buttons['gen_write'].setText(self.loc['buttons']['gen_write'])
        
        # Checkboxes
        self.ui_checkboxes['special_format'].setText(self.loc['checkboxes']['special_format'])
        self.ui_checkboxes['special_combo'].setText(self.loc['checkboxes']['special_combo'])
        self.ui_checkboxes['skin_mode'].setText(self.loc['checkboxes']['skin_mode'])
        self.ui_checkboxes['combo_mode'].setText(self.loc['checkboxes']['combo_mode'])
        self.ui_checkboxes['yaml_format'].setText(self.loc['checkboxes']['yaml_format'])
        
        # Combo boxes (refresh items)
        self._populate_batch_flags()
        self._populate_yaml_flags()
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")
