# -*- coding: utf-8 -*-
import customtkinter as ctk
from tkinter import messagebox, filedialog
import itertools
import threading
import time

# 假设这些模块存在于项目的根目录或Python路径中
import decoder_logic
import b_encoder
import bl4_functions

class ConverterTab(ctk.CTkFrame):
    def __init__(self, parent, main_app_instance):
        super().__init__(parent)
        self.main_app = main_app_instance

        # 主网格布局
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 添加可滚动框架
        scrollable_frame = ctk.CTkScrollableFrame(self, label_text="转换和遍历工具")
        scrollable_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        scrollable_frame.grid_columnconfigure(0, weight=1)

        # --- 单个转换器 ---
        single_frame = ctk.CTkFrame(scrollable_frame, corner_radius=8)
        single_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        single_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(single_frame, text="单个转换器 (Single Converter)", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="w")

        ctk.CTkLabel(single_frame, text="Base85:").grid(row=1, column=0, padx=(10,0), pady=2, sticky="w")
        self.base85_input = ctk.CTkEntry(single_frame, placeholder_text="输入Base85编码，例如: @Ug#2fK2}TYgOy&bRiHg)J)...")
        self.base85_input.grid(row=1, column=1, padx=10, pady=2, sticky="ew")
        self.base85_input.bind("<KeyRelease>", self.on_single_input_change)

        ctk.CTkLabel(single_frame, text="Deserialized:").grid(row=2, column=0, padx=(10,0), pady=2, sticky="w")
        self.deserialized_input = ctk.CTkEntry(single_frame, placeholder_text="输入解析后的数据，例如: 255, 0, 1, 50|...")
        self.deserialized_input.grid(row=2, column=1, padx=10, pady=2, sticky="ew")
        self.deserialized_input.bind("<KeyRelease>", self.on_single_input_change)

        self.single_status = ctk.CTkLabel(single_frame, text="状态: 就绪", text_color="gray")
        self.single_status.grid(row=3, column=0, padx=10, pady=(5, 10), sticky="w")
        
        clear_btn = ctk.CTkButton(single_frame, text="清除", width=80, command=self.clear_single_converter)
        clear_btn.grid(row=3, column=1, padx=10, pady=(5, 10), sticky="e")

        self.active_input = None
        self.debounce_timer = None

        # --- 批量转换器 ---
        batch_frame = ctk.CTkFrame(scrollable_frame, corner_radius=8)
        batch_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        batch_frame.grid_columnconfigure((0, 1), weight=1) # 两列等宽
        batch_frame.grid_rowconfigure(2, weight=1) # 让文本框可扩展

        ctk.CTkLabel(batch_frame, text="批量转换器 (Batch Converter)", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="w")

        ctk.CTkLabel(batch_frame, text="输入 (每行一个):").grid(row=1, column=0,  padx=10, pady=2, sticky="w")
        self.batch_input = ctk.CTkTextbox(batch_frame, height=200)
        self.batch_input.grid(row=2, column=0, padx=10, pady=2, sticky="nsew")

        output_header_frame = ctk.CTkFrame(batch_frame, fg_color="transparent")
        output_header_frame.grid(row=1, column=1, padx=10, pady=2, sticky="ew")
        ctk.CTkLabel(output_header_frame, text="输出结果:").pack(side="left")
        ctk.CTkButton(output_header_frame, text="导出为 .txt", width=100, command=self.export_batch_results).pack(side="right")

        self.batch_output = ctk.CTkTextbox(batch_frame, height=200, state="disabled")
        self.batch_output.grid(row=2, column=1, padx=10, pady=2, sticky="nsew")

        self.batch_process_btn = ctk.CTkButton(batch_frame, text="开始批量处理", command=self.start_batch_processing)
        self.batch_process_btn.grid(row=3, column=0, columnspan=2, padx=10, pady=10)
        self.batch_status = ctk.CTkLabel(batch_frame, text="状态: 就绪", text_color="gray")
        self.batch_status.grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="w")
        
        # --- 批量加入背包 ---
        batch_add_frame = ctk.CTkFrame(scrollable_frame, corner_radius=8)
        batch_add_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        batch_add_frame.grid_columnconfigure(0, weight=1)
        batch_add_frame.grid_rowconfigure(2, weight=1) # 让文本框可扩展

        ctk.CTkLabel(batch_add_frame, text="批量加入背包 (Batch Add to Backpack)", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="w")
        
        ctk.CTkLabel(batch_add_frame, text="输入 (每行一个):").grid(row=1, column=0, columnspan=2, padx=10, pady=2, sticky="w")
        self.batch_add_input = ctk.CTkTextbox(batch_add_frame, height=150)
        self.batch_add_input.grid(row=2, column=0, columnspan=2, padx=10, pady=2, sticky="nsew")

        batch_add_controls_frame = ctk.CTkFrame(batch_add_frame, fg_color="transparent")
        batch_add_controls_frame.grid(row=3, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        self.batch_add_btn = ctk.CTkButton(batch_add_controls_frame, text="批量加入背包", command=self.batch_add_to_backpack)
        self.batch_add_btn.pack(side="left")

        self.batch_add_flag_select = ctk.CTkComboBox(batch_add_controls_frame, values=["1 (普通)", "3 (收藏)", "5 (垃圾)", "17 (编组1)", "33 (编组2)", "65 (编组3)", "129 (编组4)"])
        self.batch_add_flag_select.set("3 (收藏)")
        self.batch_add_flag_select.pack(side="right")
        ctk.CTkLabel(batch_add_controls_frame, text="选择Flag:").pack(side="right", padx=(0, 5))
        
        self.batch_add_status = ctk.CTkLabel(batch_add_frame, text="状态: 就绪", text_color="gray")
        self.batch_add_status.grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="w")

        # --- 遍历生成器 ---
        iterator_frame = ctk.CTkFrame(scrollable_frame, corner_radius=8)
        iterator_frame.grid(row=3, column=0, padx=10, pady=10, sticky="nsew") 
        iterator_frame.grid_columnconfigure(0, weight=1)
        iterator_frame.grid_rowconfigure(9, weight=1) # 让输出框可以扩展

        ctk.CTkLabel(iterator_frame, text="遍历生成器 (Iterator)", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=4, padx=10, pady=(10,5), sticky="w")
        
        ctk.CTkLabel(iterator_frame, text="基础数据 (Deserialized):").grid(row=1, column=0, columnspan=4, padx=10, pady=(5,0), sticky="w")
        self.iterator_base = ctk.CTkEntry(iterator_frame, placeholder_text="在此输入不包含变量的基础数据部分")
        self.iterator_base.insert(0, "255, 0, 1, 50| 2, 969|| ")
        self.iterator_base.grid(row=2, column=0, columnspan=4, padx=10, pady=(0,10), sticky="ew")

        # --- 普通遍历 ---
        normal_iterator_frame = ctk.CTkFrame(iterator_frame, fg_color="transparent")
        normal_iterator_frame.grid(row=3, column=0, columnspan=4, padx=10, pady=5, sticky="ew")
        normal_iterator_frame.grid_columnconfigure((0,1), weight=1)
        
        ctk.CTkLabel(normal_iterator_frame, text="遍历起始值:").grid(row=0, column=0, padx=(0,5), pady=2, sticky="w")
        self.iterator_start = ctk.CTkEntry(normal_iterator_frame)
        self.iterator_start.insert(0, "1")
        self.iterator_start.grid(row=1, column=0, padx=(0,5), pady=2, sticky="ew")
        
        ctk.CTkLabel(normal_iterator_frame, text="遍历结束值:").grid(row=0, column=1, padx=(5,0), pady=2, sticky="w")
        self.iterator_end = ctk.CTkEntry(normal_iterator_frame)
        self.iterator_end.insert(0, "99")
        self.iterator_end.grid(row=1, column=1, padx=(5,0), pady=2, sticky="ew")

        # --- 特殊格式 ---
        self.special_format_check = ctk.CTkCheckBox(normal_iterator_frame, text="启用特殊格式 {基础值:变量}", command=self.update_iterator_ui)
        self.special_format_check.grid(row=2, column=0, columnspan=2, pady=(10,0), sticky="w")
        self.special_format_options = ctk.CTkFrame(normal_iterator_frame, fg_color="transparent")
        self.special_format_options.grid(row=3, column=0, columnspan=2, sticky="ew")
        ctk.CTkLabel(self.special_format_options, text="特殊格式基础值 (例如: 245):").grid(row=0, column=0, padx=5, sticky="w")
        self.iterator_special_base = ctk.CTkEntry(self.special_format_options, width=120)
        self.iterator_special_base.insert(0, "245")
        self.iterator_special_base.grid(row=0, column=1, padx=5, sticky="w")

        # --- 分隔线和模式切换 ---
        ctk.CTkFrame(iterator_frame, height=1, fg_color="gray30").grid(row=4, column=0, columnspan=4, padx=10, pady=10, sticky="ew")
        
        mode_frame = ctk.CTkFrame(iterator_frame, fg_color="transparent")
        mode_frame.grid(row=5, column=0, columnspan=4, padx=10, pady=5, sticky="w")
        self.skin_mode_check = ctk.CTkCheckBox(mode_frame, text="启用武器皮肤模式", command=self.update_iterator_ui)
        self.skin_mode_check.pack(side="left", padx=(0, 20))
        self.combination_mode_check = ctk.CTkCheckBox(mode_frame, text="启用排列组合模式", command=self.update_iterator_ui)
        self.combination_mode_check.pack(side="left")

        # --- 组合模式选项 ---
        self.combination_options = ctk.CTkFrame(iterator_frame, fg_color="transparent")
        self.combination_options.grid(row=6, column=0, columnspan=4, padx=10, pady=5, sticky="ew")
        self.combination_options.grid_columnconfigure((0,1,2), weight=1)
        ctk.CTkLabel(self.combination_options, text="组合集起始值:").grid(row=0, column=0, sticky="w")
        self.combination_start = ctk.CTkEntry(self.combination_options)
        self.combination_start.insert(0, "1")
        self.combination_start.grid(row=1, column=0, padx=(0,5), sticky="ew")
        ctk.CTkLabel(self.combination_options, text="组合集结束值:").grid(row=0, column=1, sticky="w")
        self.combination_end = ctk.CTkEntry(self.combination_options)
        self.combination_end.insert(0, "10")
        self.combination_end.grid(row=1, column=1, padx=(5,5), sticky="ew")
        ctk.CTkLabel(self.combination_options, text="组合大小:").grid(row=0, column=2, sticky="w")
        self.combination_size = ctk.CTkEntry(self.combination_options)
        self.combination_size.insert(0, "2")
        self.combination_size.grid(row=1, column=2, padx=(5,0), sticky="ew")

        # --- YAML输出 ---
        ctk.CTkFrame(iterator_frame, height=1, fg_color="gray30").grid(row=7, column=0, columnspan=4, padx=10, pady=10, sticky="ew")
        yaml_frame = ctk.CTkFrame(iterator_frame, fg_color="transparent")
        yaml_frame.grid(row=8, column=0, columnspan=4, padx=10, pady=5, sticky="ew")
        self.yaml_format_check = ctk.CTkCheckBox(yaml_frame, text="启用YAML格式化输出 (通用)", command=self.update_iterator_ui)
        self.yaml_format_check.pack(side="left", padx=(0, 20))
        self.yaml_flag_label = ctk.CTkLabel(yaml_frame, text="选择Flag:")
        self.yaml_flag_label.pack(side="left", padx=(0, 5))
        self.yaml_flag_select = ctk.CTkComboBox(yaml_frame, values=["3 (收藏)", "5 (垃圾)", "17 (编组1)", "33 (编组2)", "65 (编组3)", "129 (编组4)"])
        self.yaml_flag_select.set("33 (编组2)")
        self.yaml_flag_select.pack(side="left")

        # --- 结果和按钮 ---
        result_frame = ctk.CTkFrame(iterator_frame, fg_color="transparent")
        result_frame.grid(row=9, column=0, columnspan=4, padx=10, pady=10, sticky="nsew")
        result_frame.grid_columnconfigure(0, weight=1)
        result_frame.grid_rowconfigure(1, weight=1)
        
        button_bar = ctk.CTkFrame(result_frame, fg_color="transparent")
        button_bar.grid(row=0, column=0, sticky="ew", pady=(0,5))
        self.iterator_start_btn = ctk.CTkButton(button_bar, text="开始遍历并生成", command=self.start_iterator_processing)
        self.iterator_start_btn.pack(side="left", padx=(0,10))
        self.iterator_export_btn = ctk.CTkButton(button_bar, text="导出结果", fg_color="#4CAF50", hover_color="#5cb85c", command=self.export_iterator_results)
        self.iterator_export_btn.pack(side="left")
        self.add_to_backpack_btn = ctk.CTkButton(button_bar, text="写入背包 (YAML模式)", command=self.add_yaml_to_backpack)
        self.add_to_backpack_btn.pack(side="left", padx=(10,0))
        
        ctk.CTkLabel(result_frame, text="生成结果:").grid(row=1, column=0, sticky="nw")
        self.iterator_output = ctk.CTkTextbox(result_frame, state="disabled")
        self.iterator_output.grid(row=2, column=0, sticky="nsew")

        self.iterator_status = ctk.CTkLabel(iterator_frame, text="状态: 就绪", text_color="gray")
        self.iterator_status.grid(row=10, column=0, columnspan=4, padx=10, pady=(5, 10), sticky="w")
        
        self.update_iterator_ui() # 初始化UI状态

    def update_iterator_ui(self):
        is_skin = self.skin_mode_check.get()
        is_combo = self.combination_mode_check.get()
        is_yaml = self.yaml_format_check.get()

        # 互斥逻辑
        if is_skin and self.combination_mode_check.get():
             self.combination_mode_check.deselect()
             is_combo = False
        if is_combo and self.skin_mode_check.get():
             self.skin_mode_check.deselect()
             is_skin = False

        # 启用/禁用常规遍历输入
        state = "disabled" if is_combo else "normal"
        self.iterator_start.configure(state=state)
        self.iterator_end.configure(state=state)

        # 特殊格式仅在非皮肤/组合模式下可用
        special_state = "normal" if not is_skin and not is_combo else "disabled"
        self.special_format_check.configure(state=special_state)
        if special_state == "disabled":
            self.special_format_check.deselect()
        
        # 显示/隐藏特殊格式选项
        if self.special_format_check.get() and special_state == "normal":
             self.special_format_options.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(5,0))
        else:
             self.special_format_options.grid_remove()

        # 显示/隐藏组合模式选项
        if is_combo:
            self.combination_options.grid(row=6, column=0, columnspan=4, padx=10, pady=5, sticky="ew")
        else:
            self.combination_options.grid_remove()
            
        # YAML相关控件状态
        self.iterator_start_btn.pack_forget()
        self.add_to_backpack_btn.pack_forget()

        if is_yaml:
            self.yaml_flag_label.pack(side="left", padx=(0, 5))
            self.yaml_flag_select.pack(side="left")
            self.add_to_backpack_btn.configure(text="生成并写入背包")
            self.add_to_backpack_btn.pack(side="left", padx=(10,0))
        else:
            self.yaml_flag_label.pack_forget()
            self.yaml_flag_select.pack_forget()
            self.iterator_start_btn.pack(side="left", padx=(0,10))
            self.add_to_backpack_btn.configure(text="写入背包 (YAML模式)") # Reset text

    def add_yaml_to_backpack(self):
        """生成物品并直接添加到背包，取代旧的YAML添加逻辑"""
        if not self.main_app.yaml_obj:
            messagebox.showerror("无存档", "请先解密一个存档文件。")
            return
            
        # 强制同步主应用的YAML，以防有未保存的更改
        if not self.main_app.sync_yaml_from_text():
            messagebox.showerror("YAML同步失败", "无法从主YAML编辑器同步数据，请检查其格式。")
            return

        self.add_to_backpack_btn.configure(state="disabled", text="正在生成并写入...")
        self.iterator_status.configure(text="状态: 开始处理...", text_color="gray")
        
        # 在新线程中运行以进行密集计算和添加操作
        threading.Thread(target=self._generate_and_add_items, daemon=True).start()

    def _generate_and_add_items(self):
        """
        核心后台逻辑：生成反序列化字符串，编码它们，然后逐一添加到背包。
        """
        success_count = 0
        fail_count = 0
        deserialized_strings = [] # 用于存储生成的反序列化字符串

        try:
            # --- 第1步: 生成所有反序列化字符串 (与 start_iterator_processing 逻辑相同) ---
            self.after(0, lambda: self.iterator_status.configure(text="状态: 正在生成物品列表...", text_color="gray"))
            
            base_data = self.iterator_base.get().strip()
            is_combination_mode = self.combination_mode_check.get()
            is_skin_mode = self.skin_mode_check.get()

            if not base_data:
                raise ValueError("基础数据不能为空。")

            if is_combination_mode:
                combo_start, combo_end, combo_size = int(self.combination_start.get()), int(self.combination_end.get()), int(self.combination_size.get())
                if combo_start > combo_end: raise ValueError("组合集起始值不能大于结束值。")
                combo_set = list(range(combo_start, combo_end + 1))
                if len(combo_set) < combo_size: raise ValueError("组合集数量需大于或等于组合大小。")
                combos = self.get_combinations(combo_set, combo_size)
                for combo in combos:
                    deserialized_strings.append(f"{base_data} {' '.join(f'{{{c}}}' for c in combo)}|")
            else:
                start, end = int(self.iterator_start.get()), int(self.iterator_end.get())
                if start > end: raise ValueError("遍历起始值不能大于结束值。")
                
                if is_skin_mode:
                    for i in range(start, end + 1):
                        deserialized_strings.append(f'{base_data} | "c", {i}|')
                else:
                    is_special = self.special_format_check.get()
                    special_base = self.iterator_special_base.get()
                    if is_special and not special_base: raise ValueError("请提供特殊格式的基础值。")
                    for i in range(start, end + 1):
                        data_to_serialize = f"{base_data}{{{special_base}:{i}}}|" if is_special else f"{base_data}{{{i}}}|"
                        deserialized_strings.append(data_to_serialize)

            if not deserialized_strings:
                raise ValueError("未生成任何数据。")

            # --- 第2步: 逐个编码并添加到背包 ---
            self.after(0, lambda: self.iterator_status.configure(text=f"状态: 已生成 {len(deserialized_strings)} 个物品，准备写入...", text_color="gray"))
            flag = self.yaml_flag_select.get().split(" ")[0]
            total = len(deserialized_strings)

            for i, line in enumerate(deserialized_strings):
                self.after(0, lambda i=i: self.iterator_status.configure(text=f"状态: 正在写入 {i + 1}/{total}..."))
                
                final_serial, err = b_encoder.encode_to_base85(line)
                if err:
                    self.main_app.log(f"遍历写入失败 (编码错误): {line} -> {err}")
                    fail_count += 1
                    continue
                
                if bl4_functions.add_item_to_backpack(self.main_app.yaml_obj, final_serial, flag):
                    success_count += 1
                else:
                    self.main_app.log(f"遍历写入失败 (无法加入背包): {final_serial}")
                    fail_count += 1
                
                time.sleep(0.01) # 轻微延迟以更新UI

            # --- 第3步: 完成后更新UI ---
            status_text = f"状态: 处理完成。成功: {success_count}, 失败: {fail_count}。"
            status_color = "green" if fail_count == 0 else ("orange" if success_count > 0 else "red")
            self.after(0, lambda: self.iterator_status.configure(text=status_text, text_color=status_color))

            if success_count > 0:
                self.main_app.log(f"遍历写入完成，成功{success_count}个。正在刷新UI...")
                self.after(0, self.main_app.refresh_yaml_text)
                self.after(0, self.main_app.refresh_items)

        except Exception as e:
            self.after(0, lambda e=e: self.iterator_status.configure(text=f"状态: 操作失败: {e}", text_color="red"))
            self.main_app.log(f"遍历生成并写入时发生错误: {e}")
        finally:
            self.after(0, lambda: self.add_to_backpack_btn.configure(state="normal", text="生成并写入背包"))
        
    def clear_single_converter(self):
        """Clears both input fields for the single converter."""
        self.active_input = None
        if self.debounce_timer:
            self.after_cancel(self.debounce_timer)
        self.base85_input.delete(0, 'end')
        self.deserialized_input.delete(0, 'end')
        self.single_status.configure(text="状态: 就绪", text_color="gray")

    def _is_base85(self, text):
        return text.strip().startswith('@U') and not any(c in text for c in ',|')

    def on_single_input_change(self, event=None):
        if self.debounce_timer:
            self.after_cancel(self.debounce_timer)
        
        focused_widget = self.focus_get()
        if focused_widget == self.base85_input:
            self.active_input = "base85"
        elif focused_widget == self.deserialized_input:
            self.active_input = "deserialized"
        else: # 如果焦点丢失，根据哪个框有内容来判断
            if self.base85_input.get(): self.active_input = "base85"
            elif self.deserialized_input.get(): self.active_input = "deserialized"
            else: return

        self.debounce_timer = self.after(300, self.perform_single_conversion)

    def perform_single_conversion(self):
        if self.active_input == "base85":
            source_widget, target_widget = self.base85_input, self.deserialized_input
            mode, value = "deserialize", source_widget.get().strip()
        elif self.active_input == "deserialized":
            source_widget, target_widget = self.deserialized_input, self.base85_input
            mode, value = "serialize", source_widget.get().strip()
        else:
            return

        if not value:
            target_widget.delete(0, 'end')
            self.single_status.configure(text="状态: 就绪")
            return

        self.single_status.configure(text="状态: 处理中...")
        
        try:
            if mode == 'deserialize':
                result, _, error = decoder_logic.decode_serial_to_string(value)
            else: # serialize
                result, error = b_encoder.encode_to_base85(value)
            
            if error:
                self.single_status.configure(text=f"状态: 错误: {error}", text_color="red")
            else:
                target_widget.delete(0, 'end')
                target_widget.insert(0, result)
                self.single_status.configure(text="状态: 转换成功!", text_color="green")
        except Exception as e:
            self.single_status.configure(text=f"状态: 严重错误: {e}", text_color="red")

    def start_batch_processing(self):
        lines = [line.strip() for line in self.batch_input.get("1.0", "end").split('\n') if line.strip()]
        if not lines:
            self.batch_status.configure(text="状态: 输入为空。")
            return
        
        self.batch_process_btn.configure(state="disabled", text="处理中...")
        self.batch_output.configure(state="normal")
        self.batch_output.delete("1.0", "end")
        
        # 在新线程中运行，防止UI阻塞
        threading.Thread(target=self._process_batch_lines, args=(lines,), daemon=True).start()

    def _process_batch_lines(self, lines):
        total = len(lines)
        for i, line in enumerate(lines):
            self.after(0, lambda i=i: self.batch_status.configure(text=f"状态: 正在处理 {i + 1} / {total}..."))
            
            mode = 'deserialize' if self._is_base85(line) else 'serialize'
            
            try:
                if mode == 'deserialize':
                    result, _, error = decoder_logic.decode_serial_to_string(line)
                else:
                    result, error = b_encoder.encode_to_base85(line)
                
                output = result if not error else f"错误: {error}"
            except Exception as e:
                output = f"严重错误: {e}"
            
            self.after(0, lambda output=output: self.batch_output.insert("end", output + '\n'))
            
            # 避免对本地处理造成过大压力，可以稍微延时
            time.sleep(0.01)

        self.after(0, self._finalize_batch_processing)

    def _finalize_batch_processing(self):
        self.batch_status.configure(text="状态: 处理完成!")
        self.batch_process_btn.configure(state="normal", text="开始批量处理")
        self.batch_output.configure(state="disabled")

    def export_batch_results(self):
        content = self.batch_output.get("1.0", "end-1c")
        if not content:
            messagebox.showwarning("无内容", "没有可导出的结果。")
            return
        
        filepath = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            title="导出批量结果"
        )
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                messagebox.showinfo("成功", f"结果已成功导出到:\n{filepath}")
            except Exception as e:
                messagebox.showerror("导出失败", f"无法写入文件: {e}")

    def get_combinations(self, source_list, combo_length):
        if combo_length > len(source_list):
            return []
        return list(itertools.combinations(source_list, combo_length))

    def start_iterator_processing(self):
        self.iterator_start_btn.configure(state="disabled", text="生成中...")
        self.iterator_output.configure(state="normal")
        self.iterator_output.delete("1.0", "end")
        self.iterator_status.configure(text="状态: 正在生成待处理列表...", text_color="gray")

        # 在新线程中运行以避免UI阻塞
        threading.Thread(target=self._process_iterator, daemon=True).start()

    def _process_iterator(self):
        try:
            base_data = self.iterator_base.get().strip()
            is_yaml_format = self.yaml_format_check.get()
            yaml_flag = self.yaml_flag_select.get().split(" ")[0] # "33 (编组2)" -> "33"
            
            is_special_format = self.special_format_check.get()
            is_skin_mode = self.skin_mode_check.get()
            is_combination_mode = self.combination_mode_check.get()

            if not base_data:
                raise ValueError("基础数据不能为空。")

            deserialized_strings = []

            if is_combination_mode:
                combo_start = int(self.combination_start.get())
                combo_end = int(self.combination_end.get())
                combo_size = int(self.combination_size.get())
                if combo_start > combo_end:
                    raise ValueError("组合集起始值不能大于结束值。")
                combo_set = list(range(combo_start, combo_end + 1))
                if len(combo_set) < combo_size:
                    raise ValueError("组合基础集数量必须大于或等于组合大小。")
                
                combos = self.get_combinations(combo_set, combo_size)
                for combo in combos:
                    # Formats as: {base_data} {c1} {c2} ... |
                    deserialized_strings.append(f"{base_data} {' '.join(f'{{{c}}}' for c in combo)}|")

            else: # Normal or Skin mode
                start, end = int(self.iterator_start.get()), int(self.iterator_end.get())
                if start > end:
                    raise ValueError("遍历起始值不能大于结束值。")
                
                if is_skin_mode:
                    for i in range(start, end + 1):
                        deserialized_strings.append(f'{base_data} | "c", {i}|')
                else: 
                    special_base = self.iterator_special_base.get()
                    if is_special_format and not special_base:
                        raise ValueError("请提供特殊格式的基础值。")
                    for i in range(start, end + 1):
                        data_to_serialize = f"{base_data}{{{special_base}:{i}}}|" if is_special_format else f"{base_data}{{{i}}}|"
                        deserialized_strings.append(data_to_serialize)
            
            if not deserialized_strings:
                self.after(0, lambda: self.iterator_status.configure(text="状态: 未生成任何数据。", text_color="orange"))
                self.after(0, self._finalize_iterator_processing)
                return

            self.after(0, lambda: self.iterator_status.configure(text=f"状态: 已生成 {len(deserialized_strings)} 条数据，开始编码..."))
            
            final_output = ""
            total = len(deserialized_strings)
            for i, line in enumerate(deserialized_strings):
                if (i + 1) % 10 == 0: # Update status every 10 items
                    self.after(0, lambda i=i: self.iterator_status.configure(text=f"状态: 正在编码 {i + 1}/{total}..."))
                
                result, error = b_encoder.encode_to_base85(line)
                
                if error:
                    output_line = f"错误: {error}\n"
                elif is_yaml_format:
                    # The yaml_slot_start logic is missing in the UI, so we can't implement it yet.
                    # Placeholder, doesn't increment slot numbers.
                    output_line = f"        - serial: '{result}'\n          state_flags: {yaml_flag}\n"
                else:
                    output_line = f"{line}  -->  {result}\n"

                final_output += output_line
                time.sleep(0.005) # Prevent UI from becoming completely unresponsive on large jobs

            self.after(0, lambda: self._update_iterator_output(final_output))
            self.after(0, lambda: self.iterator_status.configure(text="状态: 生成完成!", text_color="green"))

        except ValueError as e:
            self.after(0, lambda e=e: self.iterator_status.configure(text=f"状态: 输入错误: {e}", text_color="orange"))
        except Exception as e:
            self.after(0, lambda e=e: self.iterator_status.configure(text=f"状态: 严重错误: {e}", text_color="red"))
        finally:
            self.after(0, self._finalize_iterator_processing)

    def _update_iterator_output(self, content):
        self.iterator_output.delete("1.0", "end")
        self.iterator_output.insert("1.0", content)

    def _finalize_iterator_processing(self):
        self.iterator_start_btn.configure(state="normal", text="开始遍历并生成")
        self.iterator_output.configure(state="disabled")

    def export_iterator_results(self):
        content = self.iterator_output.get("1.0", "end-1c")
        if not content:
            messagebox.showwarning("无内容", "没有可导出的结果。")
            return

        is_yaml = self.yaml_format_check.get()
        file_extension = ".yaml" if is_yaml else ".txt"
        file_title = "导出为YAML" if is_yaml else "导出为TXT"

        filepath = filedialog.asksaveasfilename(
            defaultextension=file_extension,
            filetypes=[(f"{file_title}", f"*{file_extension}"), ("All Files", "*.*")],
            title="导出遍历结果"
        )
        if filepath:
            try:
                # Extra logic for non-YAML export
                if not is_yaml:
                    # In Python 3.8+ you can use walrus operator if desired:
                    # if choice := messagebox.askyesnocancel(...)
                    choice = messagebox.askquestion("导出选项", "是否只导出Base85编码?\n选择 '是' (Yes) 只导出编码, '否' (No) 导出完整行。", icon='question', type='yesno')
                    
                    if choice == 'yes':
                        content = '\n'.join([line.split('-->')[1].strip() for line in content.strip().split('\n') if '-->' in line])

                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                messagebox.showinfo("成功", f"结果已成功导出到:\n{filepath}")
            except Exception as e:
                messagebox.showerror("导出失败", f"无法写入文件: {e}")

    def batch_add_to_backpack(self):
        """将批量输入框中的内容添加到背包"""
        if not self.main_app.yaml_obj:
            messagebox.showerror("无存档", "请先解密一个存档文件。")
            return

        lines = [line.strip() for line in self.batch_add_input.get("1.0", "end").split('\n') if line.strip()]
        if not lines:
            messagebox.showwarning("无输入", "批量加入背包的输入框中没有内容。")
            return

        # 强制同步主应用的YAML，以防有未保存的更改
        if not self.main_app.sync_yaml_from_text():
            messagebox.showerror("YAML同步失败", "无法从主YAML编辑器同步数据，请检查其格式。")
            return

        self.batch_add_btn.configure(state="disabled", text="正在加入...")
        self.batch_add_status.configure(text="状态: 开始处理...", text_color="gray")
        
        flag_str = self.batch_add_flag_select.get()
        flag = flag_str.split(" ")[0]

        threading.Thread(target=self._process_batch_add, args=(lines, flag), daemon=True).start()

    def _process_batch_add(self, lines, flag):
        success_count = 0
        fail_count = 0
        
        for i, line in enumerate(lines):
            self.after(0, lambda i=i: self.batch_add_status.configure(text=f"状态: 正在处理 {i + 1}/{len(lines)}..."))
            final_serial = ""
            try:
                if self._is_base85(line):
                    final_serial = line
                else:
                    encoded_serial, err = b_encoder.encode_to_base85(line)
                    if err:
                        self.main_app.log(f"批量添加失败 (编码错误): {line} -> {err}")
                        fail_count += 1
                        continue
                    final_serial = encoded_serial

                # 使用bl4_functions中的核心逻辑
                if bl4_functions.add_item_to_backpack(self.main_app.yaml_obj, final_serial, flag):
                    success_count += 1
                else:
                    self.main_app.log(f"批量添加失败 (无法加入背包): {final_serial}")
                    fail_count += 1
            
            except Exception as e:
                self.main_app.log(f"批量添加时发生严重错误: {e} on line: {line}")
                fail_count += 1

            time.sleep(0.02) # 轻微延迟以更新UI

        # 全部处理完毕后更新UI
        def final_update():
            status_text = f"状态: 处理完成。成功: {success_count}, 失败: {fail_count}。"
            status_color = "green" if fail_count == 0 else ("orange" if success_count > 0 else "red")
            self.batch_add_status.configure(text=status_text, text_color=status_color)
            self.batch_add_btn.configure(state="normal", text="批量加入背包")

            # 如果有成功添加的，刷新主界面的物品列表和YAML文本
            if success_count > 0:
                self.main_app.log(f"批量加入背包完成，成功{success_count}个，失败{fail_count}个。正在刷新UI...")
                self.main_app.refresh_yaml_text()
                self.main_app.refresh_items()

        self.after(0, final_update)
