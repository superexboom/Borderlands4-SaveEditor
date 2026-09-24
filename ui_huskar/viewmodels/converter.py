"""转换器页视图模型：移植 QtConverterTab 的三个转换/批量分组。

主线对应：
- tabs/qt_converter_tab.py：单条互转（300ms 防抖）、批量互转、批量写入背包。
- main_window.handle_batch_add / on_batch_add_finished：QThread 编排、自动保存挂起、完成提示。
- core.batch.add_serial_lines 直接复用。

worker 由主线 BatchConverterWorker（tabs）/ BatchAddWorker
移植到本模块并增加协作式取消（主线 worker 不支持取消，QML 页要求长任务可取消）；
未复用 main_window 类是为了避免引入其模块级副作用（stdout 重配置等）。

旧 IteratorViewModel API 暂留在文件底部用于存档兼容，转换器页面不再暴露该模块。
"""

from __future__ import annotations

import itertools
import time
from pathlib import Path
from typing import Any

import yaml

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication

from core import b_encoder, decoder_logic, resource_loader
from core.batch import add_serial_lines
from core.yaml_io import get_yaml_loader

from .base import PageViewModel, register

_FLAG_ORDER = ("1", "3", "5", "17", "33", "65", "129")
_SINGLE_READY = "ready"
_SINGLE_SUCCESS = "success"
_SINGLE_ERROR = "error"


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]


def _extract_yaml_serials(text: str) -> list[str]:
    """Extract serial values from a save/backpack-shaped YAML document.

    Batch add historically accepted one decoded serial per line.  Keep that
    path intact, but also accept the exact ``slot_*: {serial: ...}`` format
    produced by the save editor (including tagged Game YAML scalars).  We
    intentionally walk every mapping rather than assuming one fixed save
    root, so exported backpack snippets and full saves both work.
    """
    try:
        parsed_documents = list(yaml.load_all(text, Loader=get_yaml_loader()))
    except Exception:
        return []
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            serial = node.get("serial")
            if isinstance(serial, str) and serial.strip():
                found.append(serial.strip())
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    for parsed in parsed_documents:
        walk(parsed)
    return found


def _batch_input_lines(text: str) -> list[str]:
    """Return raw serial lines or serials extracted from a YAML snippet."""
    lines = _split_lines(text)
    # YAML documents with ``serial:`` should never be sent to the encoder as
    # decoded text; prefer extracted values when at least one is present.
    if any("serial:" in line.casefold() for line in lines):
        extracted = _extract_yaml_serials(text)
        if extracted:
            return extracted
    return lines


class _BatchConverterWorker(QObject):
    """批量互转 worker（移植自 tabs.qt_converter_tab.BatchConverterWorker，增加取消）。"""

    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(list)

    def __init__(self, lines, labels=None):
        super().__init__()
        self.lines = lines
        self.labels = labels or {}
        self._cancelled = False

    def request_cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        results: list[str] = []
        total = len(self.lines)
        error_template = self.labels.get("status_error", "Error: {error}")
        critical_template = self.labels.get("status_critical", "Critical Error: {error}")
        last_report = time.monotonic()
        self.progress.emit(0, total)
        for i, line in enumerate(self.lines):
            if self._cancelled:
                break
            mode = "deserialize" if line.strip().startswith("@U") else "serialize"
            try:
                if mode == "deserialize":
                    result, _blocks, error = decoder_logic.decode_serial_to_string(line)
                else:
                    result, error = b_encoder.encode_to_base85(line)
                output = result if not error else error_template.format(error=error)
            except Exception as exc:
                output = critical_template.format(error=exc)
            results.append(output)
            now = time.monotonic()
            if i + 1 == total or now - last_report >= 0.05:
                self.progress.emit(i + 1, total)
                last_report = now
        self.finished.emit(results)


class _BatchAddWorker(QObject):
    """批量写入背包 worker（移植自 main_window.BatchAddWorker，增加取消）。"""

    progress = pyqtSignal(int, int, int, int)  # current, total, success, fail
    finished = pyqtSignal(int, int)            # success, fail

    def __init__(self, controller, lines, flag):
        super().__init__()
        self.controller = controller
        self.lines = lines
        self.flag = flag
        self._cancelled = False

    def request_cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        success_count = fail_count = 0
        for current, total, success, fail in add_serial_lines(
                self.controller, self.lines, self.flag):
            self.progress.emit(current, total, success, fail)
            success_count, fail_count = success, fail
            if self._cancelled:
                break
        self.finished.emit(success_count, fail_count)


class _IteratorWorker(QObject):
    """迭代器 worker（移植自 main_window.IteratorWorker，增加进度信号与取消）。"""

    status_update = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # current, total（写背包 / 编码输出阶段）
    finished_generation = pyqtSignal(str)
    finished_add_to_backpack = pyqtSignal(int, int)

    def __init__(self, controller, params, loc_data):
        super().__init__()
        self.controller = controller
        self.params = params
        self.loc = loc_data
        self._cancelled = False

    def request_cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            is_add_to_backpack = self.params.get("add_to_backpack", False)
            deserialized_strings = self._generate_deserialized_list()
            if not deserialized_strings:
                self.status_update.emit(self.loc["no_data"])
                if is_add_to_backpack:
                    self.finished_add_to_backpack.emit(0, 0)
                else:
                    self.finished_generation.emit("")
                return
            if is_add_to_backpack:
                self._add_items_to_backpack(deserialized_strings)
            else:
                self._generate_output_text(deserialized_strings)
        except ValueError as exc:
            self.status_update.emit(f"{self.loc['error_prefix']}{exc}")
            if self.params.get("add_to_backpack"):
                self.finished_add_to_backpack.emit(0, 0)
            else:
                self.finished_generation.emit("")
        except Exception as exc:
            self.status_update.emit(f"{self.loc['error_prefix']}{exc}")
            if self.params.get("add_to_backpack"):
                self.finished_add_to_backpack.emit(0, 0)
            else:
                self.finished_generation.emit("")

    def _generate_deserialized_list(self) -> list[str]:
        self.status_update.emit(self.loc["generating"])
        base_data = self.params["base_data"].strip()
        if not base_data:
            raise ValueError(self.loc["base_empty"])

        strings: list[str] = []
        if self.params["is_combo"]:
            start, end = int(self.params["combo_start"]), int(self.params["combo_end"])
            size = int(self.params["combo_size"])
            if start > end:
                raise ValueError(self.loc["combo_error_range"])
            source_set = range(start, end + 1)
            if len(source_set) < size:
                raise ValueError(self.loc["combo_error_size"])
            for combo in itertools.combinations(source_set, size):
                strings.append(f"{base_data} {' '.join(f'{{{c}}}' for c in combo)}|")
        else:
            start, end = int(self.params["start"]), int(self.params["end"])
            if start > end:
                raise ValueError(self.loc["iter_error_range"])
            if self.params["is_skin"]:
                for i in range(start, end + 1):
                    strings.append(f'{base_data} | "c", {i}|')
            else:
                special_base = self.params["special_base"]
                is_special_combo = self.params.get("is_special_combo", False)
                combo_text = self.params.get("special_combo_text", "").strip()

                if (self.params["is_special"] or is_special_combo) and not special_base:
                    raise ValueError(self.loc["special_base_needed"])

                for i in range(start, end + 1):
                    if is_special_combo:
                        # 格式：{AAA:[98 99 B]}
                        part = f"{{{special_base}:[{combo_text} {i}]}}"
                    elif self.params["is_special"]:
                        part = f"{{{special_base}:{i}}}"
                    else:
                        part = f"{{{i}}}"
                    strings.append(f"{base_data}{part}|")
        return strings

    def _add_items_to_backpack(self, strings: list[str]) -> None:
        self.status_update.emit(self.loc["generated_writing"].format(count=len(strings)))
        success = fail = 0
        for done, total, success, fail in add_serial_lines(
                self.controller, strings, self.params["yaml_flag"]):
            self.status_update.emit(
                self.loc["writing_progress"].format(current=done, total=total))
            self.progress.emit(done, total)
            if self._cancelled:
                break
        self.finished_add_to_backpack.emit(success, fail)

    def _generate_output_text(self, strings: list[str]) -> None:
        self.status_update.emit(self.loc["generated_encoding"].format(count=len(strings)))
        final_output: list[str] = []
        total = len(strings)
        is_yaml = self.params["is_yaml"]
        yaml_flag = self.params["yaml_flag"]
        last_report = time.monotonic()
        self.status_update.emit(self.loc["encoding_progress"].format(current=0, total=total))
        self.progress.emit(0, total)

        for i, line in enumerate(strings):
            if self._cancelled:
                break
            result, error = b_encoder.encode_to_base85(line)
            if error:
                output_line = f"{self.loc['error_prefix']}{error}"
            elif is_yaml:
                output_line = f"        - serial: '{result}'\n          state_flags: {yaml_flag}"
            else:
                output_line = f"{line}  -->  {result}"
            final_output.append(output_line)
            now = time.monotonic()
            if i + 1 == total or now - last_report >= 0.05:
                self.status_update.emit(
                    self.loc["encoding_progress"].format(current=i + 1, total=total))
                self.progress.emit(i + 1, total)
                last_report = now
        self.finished_generation.emit("\n".join(final_output))


@register("converter", "ConverterPage.qml")
class ConverterViewModel(PageViewModel):
    STRINGS_SECTION = "converter_tab"

    dataChanged = pyqtSignal()
    serialResultReady = pyqtSignal(str)   # 单条互转结果回写：序列号输入框
    deserResultReady = pyqtSignal(str)    # 单条互转结果回写：反序列化输入框

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self._reload_flag_options()
        self._batch_add_flag_idx = _FLAG_ORDER.index("3")
        self._yaml_flag_idx = _FLAG_ORDER.index("33")

        # ---- 单条互转 ----
        self._serial_text = ""
        self._deser_text = ""
        self._active_field = ""        # "serial" | "deser" | ""
        self._suppress = False         # 回写期间屏蔽输入事件，防反馈环
        self._single_status = ""
        self._single_kind = ""
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._perform_single_conversion)

        # ---- 批量互转 ----
        self._batch_input = ""
        self._batch_output = ""
        self._batch_status = ""
        self._batch_running = False
        self._batch_percent = 0.0
        self._batch_thread: QThread | None = None
        self._batch_worker: _BatchConverterWorker | None = None

        # ---- 批量写入背包 ----
        self._batch_add_input = ""
        self._batch_add_status = ""
        self._batch_add_running = False
        self._batch_add_percent = 0.0
        self._batch_add_thread: QThread | None = None
        self._batch_add_worker: _BatchAddWorker | None = None

        # ---- 迭代器 ----
        self._base_data = "255, 0, 1, 50| 2, 969|| "
        self._iter_start = "1"
        self._iter_end = "99"
        self._special_base = "245"
        self._special_combo_text = ""
        self._combo_start = "1"
        self._combo_end = "10"
        self._combo_size = "2"
        self._is_skin = False
        self._is_combo = False
        self._is_special = False
        self._is_special_combo = False
        self._is_yaml = False
        self._iter_output = ""
        self._iter_status = ""
        self._iter_running = False
        self._iter_percent = 0.0
        self._iter_thread: QThread | None = None
        self._iter_worker: _IteratorWorker | None = None

    # ------------------------------------------------------------------
    # 本地化辅助
    # ------------------------------------------------------------------
    def _labels(self) -> dict[str, Any]:
        return self.strings.get("labels", {})

    def _dialogs(self) -> dict[str, Any]:
        return self.strings.get("dialogs", {})

    def _main_dialogs(self) -> dict[str, Any]:
        return self.app.localizer.section("main_window.dialogs")

    def _worker_loc(self) -> dict[str, Any]:
        return self.app.localizer.section("main_window.worker")

    def _status_ready(self) -> str:
        return self._labels().get("status_ready", "Ready")

    def _reload_flag_options(self) -> None:
        flags = resource_loader.get_flag_labels(self.app.language)
        self._flag_options = [
            {"label": flags.get(k, k), "value": k} for k in _FLAG_ORDER
        ]

    def on_language_changed(self) -> None:
        self._reload_flag_options()
        super().on_language_changed()

    # ------------------------------------------------------------------
    # 属性：Flag 选择
    # ------------------------------------------------------------------
    @pyqtProperty(list, notify=dataChanged)
    def flagOptions(self) -> list[dict[str, str]]:
        return self._flag_options

    @pyqtProperty(int, notify=dataChanged)
    def batchAddFlagIndex(self) -> int:
        return self._batch_add_flag_idx

    @pyqtProperty(int, notify=dataChanged)
    def yamlFlagIndex(self) -> int:
        return self._yaml_flag_idx

    @pyqtSlot(int)
    def setBatchAddFlagIndex(self, index: int) -> None:
        if 0 <= index < len(_FLAG_ORDER) and index != self._batch_add_flag_idx:
            self._batch_add_flag_idx = index
            self.dataChanged.emit()

    @pyqtSlot(int)
    def setYamlFlagIndex(self, index: int) -> None:
        if 0 <= index < len(_FLAG_ORDER) and index != self._yaml_flag_idx:
            self._yaml_flag_idx = index
            self.dataChanged.emit()

    # ------------------------------------------------------------------
    # 分组一：单条互转
    # ------------------------------------------------------------------
    @pyqtProperty(str, notify=dataChanged)
    def singleStatusText(self) -> str:
        return self._single_status or self._status_ready()

    @pyqtProperty(str, notify=dataChanged)
    def singleStatusKind(self) -> str:
        return self._single_kind

    @pyqtSlot(str)
    def onSerialEdited(self, text: str) -> None:
        if self._suppress:
            return
        self._serial_text = text
        self._active_field = "serial"
        self._debounce.start()

    @pyqtSlot(str)
    def onDeserEdited(self, text: str) -> None:
        if self._suppress:
            return
        self._deser_text = text
        self._active_field = "deser"
        self._debounce.start()

    def _push_single_result(self, target: str, value: str) -> None:
        self._suppress = True
        try:
            if target == "serial":
                self._serial_text = value
                self.serialResultReady.emit(value)
            else:
                self._deser_text = value
                self.deserResultReady.emit(value)
        finally:
            self._suppress = False

    def _perform_single_conversion(self) -> None:
        labels = self._labels()
        if self._active_field == "serial":
            value, target, mode = self._serial_text.strip(), "deser", "deserialize"
        elif self._active_field == "deser":
            value, target, mode = self._deser_text.strip(), "serial", "serialize"
        else:
            return

        if not value:
            self._push_single_result(target, "")
            self._single_status = labels.get("status_ready", "Ready")
            self._single_kind = ""
            self.dataChanged.emit()
            return

        try:
            if mode == "deserialize":
                result, _blocks, error = decoder_logic.decode_serial_to_string(value)
            else:
                result, error = b_encoder.encode_to_base85(value)
            if error:
                self._single_status = labels.get(
                    "status_error", "Error: {error}").format(error=error)
                self._single_kind = _SINGLE_ERROR
                self._push_single_result(target, "")
            else:
                self._push_single_result(target, result)
                self._single_status = labels.get("status_success", "Success!")
                self._single_kind = _SINGLE_SUCCESS
        except Exception as exc:
            self._single_status = labels.get(
                "status_critical", "Critical Error: {error}").format(error=exc)
            self._single_kind = _SINGLE_ERROR
            self._push_single_result(target, "")
        self.dataChanged.emit()

    @pyqtSlot()
    def clearSingle(self) -> None:
        self._debounce.stop()
        self._active_field = ""
        self._push_single_result("serial", "")
        self._push_single_result("deser", "")
        self._single_status = ""
        self._single_kind = ""
        self.dataChanged.emit()

    @pyqtSlot()
    def copySerial(self) -> None:
        QGuiApplication.clipboard().setText(self._serial_text)

    @pyqtSlot()
    def copyDeser(self) -> None:
        QGuiApplication.clipboard().setText(self._deser_text)

    # ------------------------------------------------------------------
    # 分组二：批量互转
    # ------------------------------------------------------------------
    @pyqtProperty(bool, notify=dataChanged)
    def batchRunning(self) -> bool:
        return self._batch_running

    @pyqtProperty(str, notify=dataChanged)
    def batchStatusText(self) -> str:
        return self._batch_status or self._status_ready()

    @pyqtProperty(float, notify=dataChanged)
    def batchPercent(self) -> float:
        return self._batch_percent

    @pyqtProperty(str, notify=dataChanged)
    def batchOutputText(self) -> str:
        return self._batch_output

    @pyqtSlot(str)
    def setBatchInput(self, text: str) -> None:
        self._batch_input = text

    @pyqtSlot()
    def startBatch(self) -> None:
        if self._batch_running:
            return
        labels = self._labels()
        lines = _split_lines(self._batch_input)
        if not lines:
            self._batch_status = labels.get("status_empty", "Empty input.")
            self.dataChanged.emit()
            return

        self._batch_running = True
        self._batch_percent = 0.0
        self._batch_output = ""
        self._batch_status = labels.get(
            "status_progress", "Processing {current}/{total}...").format(
                current=0, total=len(lines))
        self.dataChanged.emit()

        worker = _BatchConverterWorker(lines, labels)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_batch_progress)
        worker.finished.connect(self._on_batch_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._batch_worker = worker
        self._batch_thread = thread
        thread.start()

    def _on_batch_progress(self, current: int, total: int) -> None:
        self._batch_percent = (current / total * 100.0) if total else 0.0
        self._batch_status = self._labels().get(
            "status_progress", "Processing {current}/{total}...").format(
                current=current, total=total)
        self.dataChanged.emit()

    def _on_batch_finished(self, results: list[str]) -> None:
        self._batch_running = False
        self._batch_worker = None
        self._batch_thread = None
        self._batch_percent = 100.0
        self._batch_output = "\n".join(results)
        self._batch_status = self._labels().get("status_complete", "Complete!")
        self.dataChanged.emit()

    @pyqtSlot()
    def cancelBatch(self) -> None:
        if self._batch_worker is not None:
            self._batch_worker.request_cancel()

    @pyqtSlot()
    def exportBatch(self) -> None:
        dialogs = self._dialogs()
        content = self._batch_output
        if not content:
            self.app.toast(dialogs.get("no_export", "Nothing to export"), "warning")
            return
        self._export_text(content, dialogs.get("export_batch_title", "Export"),
                          dialogs.get("text_filter", "Text Files (*.txt);;All Files (*)"))

    def _export_text(self, content: str, title: str, file_filter: str) -> None:
        from PyQt6.QtWidgets import QFileDialog
        dialogs = self._dialogs()
        path, _ = QFileDialog.getSaveFileName(None, title, "", file_filter)
        if not path:
            return
        try:
            Path(path).write_text(content, encoding="utf-8")
            self.app.toast(dialogs.get(
                "export_success", "Saved to {path}").format(path=path), "success")
        except Exception as exc:
            self.app.toast(dialogs.get(
                "write_fail", "Write failed: {error}").format(error=exc), "error")

    # ------------------------------------------------------------------
    # 分组三：批量写入背包
    # ------------------------------------------------------------------
    @pyqtProperty(bool, notify=dataChanged)
    def batchAddRunning(self) -> bool:
        return self._batch_add_running

    @pyqtProperty(str, notify=dataChanged)
    def batchAddStatusText(self) -> str:
        return self._batch_add_status or self._status_ready()

    @pyqtProperty(float, notify=dataChanged)
    def batchAddPercent(self) -> float:
        return self._batch_add_percent

    @pyqtProperty(str, notify=dataChanged)
    def batchAddInput(self) -> str:
        return self._batch_add_input

    @pyqtSlot(str)
    def setBatchAddInput(self, text: str) -> None:
        self._batch_add_input = text

    @pyqtSlot()
    def importBatchAddYaml(self) -> None:
        """Load a backpack/full-save YAML snippet into the batch input box."""
        from PyQt6.QtWidgets import QFileDialog

        title = self._dialogs().get("import_yaml", "Import backpack YAML")
        path, _filter = QFileDialog.getOpenFileName(
            None, title, "", "YAML Files (*.yaml *.yml);;All Files (*)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
            serials = _extract_yaml_serials(text)
        except Exception as exc:
            self.app.toast(
                self._dialogs().get("import_yaml_failed", "YAML import failed: {error}").format(error=exc),
                "error")
            return
        if not serials:
            self.app.toast(
                self._dialogs().get("import_yaml_empty", "No serial fields found in YAML"),
                "warning")
            return
        self._batch_add_input = "\n".join(serials)
        self._batch_add_status = self._labels().get(
            "status_yaml_imported", "Imported {count} serials.").format(count=len(serials))
        self.dataChanged.emit()

    @pyqtSlot()
    def startBatchAdd(self) -> None:
        if self._batch_add_running:
            return
        dialogs = self._main_dialogs()
        labels = self._labels()
        lines = _batch_input_lines(self._batch_add_input)
        if not lines:
            self.app.toast(dialogs.get("batch_add_empty", "Input empty"), "warning")
            return
        if not self.controller.yaml_obj:
            self.app.toast(
                f"{dialogs.get('no_save', 'No save')}: "
                f"{dialogs.get('decrypt_save_first', 'Decrypt a save first')}",
                "error")
            self._batch_add_status = labels.get(
                "status_batch_add_complete", "Complete").format(success=0, fail=len(lines))
            self.dataChanged.emit()
            return

        flag = _FLAG_ORDER[self._batch_add_flag_idx]
        self._batch_add_running = True
        self._batch_add_percent = 0.0
        self._batch_add_status = labels.get("status_prepare", "Preparing...")
        self.dataChanged.emit()

        worker = _BatchAddWorker(self.controller, lines, flag)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_batch_add_progress)
        worker.finished.connect(self._on_batch_add_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._batch_add_worker = worker
        self._batch_add_thread = thread
        self.app.suspend_autosave(True)
        thread.start()

    def _on_batch_add_progress(self, current: int, total: int,
                               success: int, fail: int) -> None:
        self._batch_add_percent = (current / total * 100.0) if total else 0.0
        self._batch_add_status = self._labels().get(
            "status_batch_add_progress", "Progress: {current}/{total}").format(
                current=current, total=total, success=success, fail=fail)
        self.dataChanged.emit()

    def _on_batch_add_finished(self, success: int, fail: int) -> None:
        self._batch_add_running = False
        self._batch_add_worker = None
        self._batch_add_thread = None
        self.app.suspend_autosave(False)
        dialogs = self._main_dialogs()
        labels = self._labels()
        if success > 0:
            self.app.toast(dialogs.get(
                "batch_success", "Added {count} items.").format(count=success),
                "success")
            self.app._mark_items_stale()
        else:
            self.app.toast(dialogs.get(
                "batch_fail_msg", "Failed to add {count} items.").format(count=fail),
                "warning")
        self._batch_add_percent = 100.0
        self._batch_add_status = labels.get(
            "status_batch_add_complete", "Complete").format(success=success, fail=fail)
        self.dataChanged.emit()

    @pyqtSlot()
    def cancelBatchAdd(self) -> None:
        if self._batch_add_worker is not None:
            self._batch_add_worker.request_cancel()

    # ------------------------------------------------------------------
    # 分组四：迭代器
    # ------------------------------------------------------------------
    # -- 输入状态 --
    @pyqtProperty(str, notify=dataChanged)
    def baseData(self) -> str:
        return self._base_data

    @pyqtProperty(str, notify=dataChanged)
    def iterStart(self) -> str:
        return self._iter_start

    @pyqtProperty(str, notify=dataChanged)
    def iterEnd(self) -> str:
        return self._iter_end

    @pyqtProperty(str, notify=dataChanged)
    def specialBase(self) -> str:
        return self._special_base

    @pyqtProperty(str, notify=dataChanged)
    def specialComboText(self) -> str:
        return self._special_combo_text

    @pyqtProperty(str, notify=dataChanged)
    def comboStart(self) -> str:
        return self._combo_start

    @pyqtProperty(str, notify=dataChanged)
    def comboEnd(self) -> str:
        return self._combo_end

    @pyqtProperty(str, notify=dataChanged)
    def comboSize(self) -> str:
        return self._combo_size

    @pyqtSlot(str)
    def setBaseData(self, text: str) -> None:
        self._base_data = text

    @pyqtSlot(str)
    def setIterStart(self, text: str) -> None:
        self._iter_start = text

    @pyqtSlot(str)
    def setIterEnd(self, text: str) -> None:
        self._iter_end = text

    @pyqtSlot(str)
    def setSpecialBase(self, text: str) -> None:
        self._special_base = text

    @pyqtSlot(str)
    def setSpecialComboText(self, text: str) -> None:
        self._special_combo_text = text

    @pyqtSlot(str)
    def setComboStart(self, text: str) -> None:
        self._combo_start = text

    @pyqtSlot(str)
    def setComboEnd(self, text: str) -> None:
        self._combo_end = text

    @pyqtSlot(str)
    def setComboSize(self, text: str) -> None:
        self._combo_size = text

    # -- 模式开关（互斥/联动逻辑对齐主线 update_iterator_ui） --
    @pyqtProperty(bool, notify=dataChanged)
    def isSkin(self) -> bool:
        return self._is_skin

    @pyqtProperty(bool, notify=dataChanged)
    def isCombo(self) -> bool:
        return self._is_combo

    @pyqtProperty(bool, notify=dataChanged)
    def isSpecial(self) -> bool:
        return self._is_special

    @pyqtProperty(bool, notify=dataChanged)
    def isSpecialCombo(self) -> bool:
        return self._is_special_combo

    @pyqtProperty(bool, notify=dataChanged)
    def isYaml(self) -> bool:
        return self._is_yaml

    @pyqtSlot(bool)
    def setSkinMode(self, on: bool) -> None:
        on = bool(on)
        if on and self._is_combo:
            self._is_combo = False
        if self._is_skin != on:
            self._is_skin = on
            if on:
                self._is_special = False
            self.dataChanged.emit()

    @pyqtSlot(bool)
    def setComboMode(self, on: bool) -> None:
        on = bool(on)
        if on and self._is_skin:
            self._is_skin = False
        if self._is_combo != on:
            self._is_combo = on
            if on:
                self._is_special = False
            self.dataChanged.emit()

    @pyqtSlot(bool)
    def setSpecialFormat(self, on: bool) -> None:
        on = bool(on)
        if self._is_skin or self._is_combo:
            on = False
        if self._is_special != on:
            self._is_special = on
            self.dataChanged.emit()

    @pyqtSlot(bool)
    def setSpecialCombo(self, on: bool) -> None:
        on = bool(on)
        if self._is_special_combo != on:
            self._is_special_combo = on
            self.dataChanged.emit()

    @pyqtSlot(bool)
    def setYamlFormat(self, on: bool) -> None:
        on = bool(on)
        if self._is_yaml != on:
            self._is_yaml = on
            self.dataChanged.emit()

    # -- 联动可见性/可用性（对齐主线 update_iterator_ui） --
    @pyqtProperty(bool, notify=dataChanged)
    def iterRangeEnabled(self) -> bool:
        return not self._is_combo

    @pyqtProperty(bool, notify=dataChanged)
    def specialFormatEnabled(self) -> bool:
        return not self._is_skin and not self._is_combo

    @pyqtProperty(bool, notify=dataChanged)
    def specialOptionsVisible(self) -> bool:
        return self._is_special and self.specialFormatEnabled

    @pyqtProperty(bool, notify=dataChanged)
    def specialComboInputVisible(self) -> bool:
        return self._is_special_combo and self.specialOptionsVisible

    @pyqtProperty(bool, notify=dataChanged)
    def comboOptionsVisible(self) -> bool:
        return self._is_combo

    @pyqtProperty(bool, notify=dataChanged)
    def yamlFlagVisible(self) -> bool:
        return self._is_yaml

    @pyqtProperty(bool, notify=dataChanged)
    def iterStartVisible(self) -> bool:
        return not self._is_yaml

    @pyqtProperty(bool, notify=dataChanged)
    def iterWriteVisible(self) -> bool:
        return self._is_yaml

    # -- 运行状态 --
    @pyqtProperty(bool, notify=dataChanged)
    def iterRunning(self) -> bool:
        return self._iter_running

    @pyqtProperty(str, notify=dataChanged)
    def iterStatusText(self) -> str:
        return self._iter_status or self._status_ready()

    @pyqtProperty(float, notify=dataChanged)
    def iterPercent(self) -> float:
        return self._iter_percent

    @pyqtProperty(str, notify=dataChanged)
    def iterOutputText(self) -> str:
        return self._iter_output

    def _iterator_params(self, add_to_backpack: bool) -> dict[str, Any]:
        params = {
            "base_data": self._base_data,
            "is_yaml": self._is_yaml,
            "yaml_flag": _FLAG_ORDER[self._yaml_flag_idx],
            "is_special": self._is_special,
            "special_base": self._special_base,
            "is_special_combo": self._is_special_combo,
            "special_combo_text": self._special_combo_text,
            "is_skin": self._is_skin,
            "is_combo": self._is_combo,
            "start": self._iter_start,
            "end": self._iter_end,
            "combo_start": self._combo_start,
            "combo_end": self._combo_end,
            "combo_size": self._combo_size,
            "add_to_backpack": add_to_backpack,
        }
        return params

    @pyqtSlot()
    def startIterator(self) -> None:
        self._start_iterator(add_to_backpack=False)

    @pyqtSlot()
    def startIteratorWrite(self) -> None:
        self._start_iterator(add_to_backpack=True)

    def _start_iterator(self, add_to_backpack: bool) -> None:
        if self._iter_running:
            return
        dialogs = self._main_dialogs()
        labels = self._labels()
        if add_to_backpack and not self.controller.yaml_obj:
            self.app.toast(
                f"{dialogs.get('no_save', 'No save')}: "
                f"{dialogs.get('decrypt_save_first', 'Decrypt a save first')}",
                "error")
            self._iter_status = labels.get(
                "status_batch_add_complete", "Complete").format(success=0, fail=0)
            self.dataChanged.emit()
            return

        self._iter_running = True
        self._iter_percent = 0.0
        self._iter_output = ""
        self._iter_status = (labels.get("status_prepare", "Preparing...")
                             if add_to_backpack
                             else labels.get("status_generating", "Generating..."))
        self.dataChanged.emit()

        worker = _IteratorWorker(self.controller, self._iterator_params(add_to_backpack),
                                 self._worker_loc())
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.status_update.connect(self._on_iter_status)
        worker.progress.connect(self._on_iter_progress)
        if add_to_backpack:
            worker.finished_add_to_backpack.connect(self._on_iter_add_finished)
        else:
            worker.finished_generation.connect(self._on_iter_gen_finished)
        worker.finished_generation.connect(thread.quit)
        worker.finished_add_to_backpack.connect(thread.quit)
        worker.finished_generation.connect(worker.deleteLater)
        worker.finished_add_to_backpack.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._iter_worker = worker
        self._iter_thread = thread
        if add_to_backpack:
            self.app.suspend_autosave(True)
        thread.start()

    def _on_iter_status(self, message: str) -> None:
        self._iter_status = self._labels().get(
            "status_message", "Status: {message}").format(message=message)
        self.dataChanged.emit()

    def _on_iter_progress(self, current: int, total: int) -> None:
        self._iter_percent = (current / total * 100.0) if total else 0.0
        self.dataChanged.emit()

    def _on_iter_gen_finished(self, text: str) -> None:
        self._iter_running = False
        self._iter_worker = None
        self._iter_thread = None
        self._iter_percent = 100.0
        self._iter_output = text
        self._iter_status = self._labels().get(
            "status_gen_complete", "Generation Complete!")
        self.dataChanged.emit()

    def _on_iter_add_finished(self, success: int, fail: int) -> None:
        self._iter_running = False
        self._iter_worker = None
        self._iter_thread = None
        self.app.suspend_autosave(False)
        dialogs = self._main_dialogs()
        labels = self._labels()
        if success > 0:
            self.app.toast(dialogs.get(
                "iter_success", "Generated {count} items.").format(count=success),
                "success")
            self.app._mark_items_stale()
        else:
            self.app.toast(dialogs.get(
                "iter_fail_msg", "Failed to generate {count} items.").format(count=fail),
                "warning")
        self._iter_percent = 100.0
        self._iter_status = labels.get(
            "status_batch_add_complete", "Complete").format(success=success, fail=fail)
        self.dataChanged.emit()

    @pyqtSlot()
    def cancelIterator(self) -> None:
        if self._iter_worker is not None:
            self._iter_worker.request_cancel()

    @pyqtSlot()
    def exportIterator(self) -> None:
        dialogs = self._dialogs()
        content = self._iter_output
        if not content:
            self.app.toast(dialogs.get("no_export", "Nothing to export"), "warning")
            return
        is_yaml = self._is_yaml
        ext = ".yaml" if is_yaml else ".txt"
        title = dialogs.get("export_yaml" if is_yaml else "export_txt_title", "Export")
        filter_key = "yaml_filter" if is_yaml else "text_filter"
        fallback = f"{'YAML' if is_yaml else 'Text'} Files (*{ext});;All Files (*)"
        if not is_yaml:
            # 主线导出非 YAML 结果时询问“仅导出 Base85”（Yes/No/Cancel）；
            # QML 确认框为二值（确定=仅 Base85，取消=放弃），不再提供“完整导出”分支。
            def _do_export(base85_only: bool) -> None:
                if not base85_only:
                    return
                data = "\n".join(
                    line.split("-->")[1].strip()
                    for line in content.strip().split("\n") if "-->" in line)
                self._export_text(data, title, dialogs.get(filter_key, fallback))
            self.app._request_confirm(
                dialogs.get("export_opts", "Options"),
                dialogs.get("only_base85", "Base85 only?"),
                _do_export)
            return
        self._export_text(content, title, dialogs.get(filter_key, fallback))
