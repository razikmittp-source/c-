#!/usr/bin/env python3
import ctypes
import json
import random
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, ttk

import pyautogui
from pynput import keyboard, mouse

pyautogui.PAUSE = 0  # управляем скоростью сами; встроенная пауза pyautogui после каждого вызова не нужна

STOP_HOTKEY = "<cmd>+<alt>+<esc>"
HOTKEY_LABEL = "⌘⌥⎋"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


@dataclass
class DragBatch:
    area_top_left: tuple = (500, 500)
    area_bottom_right: tuple = (600, 560)
    repeat_min: int = 9
    repeat_max: int = 9
    drag_distance: int = 76
    direction: str = "right"

    def random_start_point(self):
        x1, y1 = self.area_top_left
        x2, y2 = self.area_bottom_right
        x = random.uniform(min(x1, x2), max(x1, x2))
        y = random.uniform(min(y1, y2), max(y1, y2))
        return (x, y)

    def random_repeat_count(self):
        return random.randint(min(self.repeat_min, self.repeat_max), max(self.repeat_min, self.repeat_max))


@dataclass
class ClickBatch:
    point: tuple = (750, 800)
    repeat_min: int = 3
    repeat_max: int = 3
    smart_indicator_enabled: bool = False
    indicator_top_left: tuple = (0, 0)
    indicator_bottom_right: tuple = (0, 0)

    def random_repeat_count(self):
        return random.randint(min(self.repeat_min, self.repeat_max), max(self.repeat_min, self.repeat_max))


@dataclass
class AppConfig:
    batch1: DragBatch = field(default_factory=lambda: DragBatch((500, 500), (600, 560), 9, 9, 76, "right"))
    batch2: DragBatch = field(default_factory=lambda: DragBatch((900, 500), (1000, 560), 2, 2, 76, "left"))
    batch3: ClickBatch = field(default_factory=lambda: ClickBatch((750, 800), 3, 3))
    delay_min_seconds: float = 1.0
    delay_max_seconds: float = 4.0


def _point_to_dict(p):
    return {"x": p[0], "y": p[1]}


def _point_from_dict(d):
    return (d["x"], d["y"])


def _drag_batch_to_dict(b: DragBatch) -> dict:
    return {
        "areaTopLeft": _point_to_dict(b.area_top_left),
        "areaBottomRight": _point_to_dict(b.area_bottom_right),
        "repeatMin": b.repeat_min,
        "repeatMax": b.repeat_max,
        "dragDistance": b.drag_distance,
        "direction": b.direction,
    }


def _drag_batch_from_dict(d: dict) -> DragBatch:
    repeat_min = d.get("repeatMin", d.get("repeatCount", 1))
    repeat_max = d.get("repeatMax", d.get("repeatCount", repeat_min))
    return DragBatch(_point_from_dict(d["areaTopLeft"]), _point_from_dict(d["areaBottomRight"]),
                      repeat_min, repeat_max, d["dragDistance"], d["direction"])


def _click_batch_to_dict(b: ClickBatch) -> dict:
    return {
        "point": _point_to_dict(b.point),
        "repeatMin": b.repeat_min,
        "repeatMax": b.repeat_max,
        "smartIndicatorEnabled": b.smart_indicator_enabled,
        "indicatorTopLeft": _point_to_dict(b.indicator_top_left),
        "indicatorBottomRight": _point_to_dict(b.indicator_bottom_right),
    }


def _click_batch_from_dict(d: dict) -> ClickBatch:
    repeat_min = d.get("repeatMin", d.get("repeatCount", 1))
    repeat_max = d.get("repeatMax", d.get("repeatCount", repeat_min))
    indicator_top_left = _point_from_dict(d["indicatorTopLeft"]) if "indicatorTopLeft" in d else (0, 0)
    indicator_bottom_right = _point_from_dict(d["indicatorBottomRight"]) if "indicatorBottomRight" in d else (0, 0)
    return ClickBatch(_point_from_dict(d["point"]), repeat_min, repeat_max,
                       d.get("smartIndicatorEnabled", False), indicator_top_left, indicator_bottom_right)


def config_to_dict(cfg: AppConfig) -> dict:
    return {
        "batch1": _drag_batch_to_dict(cfg.batch1),
        "batch2": _drag_batch_to_dict(cfg.batch2),
        "batch3": _click_batch_to_dict(cfg.batch3),
        "delayMinSeconds": cfg.delay_min_seconds,
        "delayMaxSeconds": cfg.delay_max_seconds,
    }


def config_from_dict(d: dict) -> AppConfig:
    return AppConfig(_drag_batch_from_dict(d["batch1"]), _drag_batch_from_dict(d["batch2"]),
                      _click_batch_from_dict(d["batch3"]), d["delayMinSeconds"], d["delayMaxSeconds"])


def save_config(cfg: AppConfig, path: Path):
    path.write_text(json.dumps(config_to_dict(cfg), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_config(path: Path) -> AppConfig:
    return config_from_dict(json.loads(path.read_text(encoding="utf-8")))


class MouseController:
    @staticmethod
    def click(point):
        pyautogui.moveTo(point[0], point[1])
        pyautogui.mouseDown()
        time.sleep(0.05)
        pyautogui.mouseUp()

    @staticmethod
    def drag_click(start, end, steps=12, step_delay=0.012):
        pyautogui.moveTo(start[0], start[1])
        pyautogui.mouseDown()
        time.sleep(0.03)

        for i in range(1, steps + 1):
            t = i / steps
            x = start[0] + (end[0] - start[0]) * t
            y = start[1] + (end[1] - start[1]) * t
            pyautogui.dragTo(x, y, button="left", mouseDownUp=False)
            time.sleep(step_delay)

        pyautogui.mouseUp()


def _smoothed(values, window):
    if window <= 1:
        return list(values)
    half = window // 2
    n = len(values)
    return [sum(values[max(0, i - half):min(n, i + half + 1)]) / len(values[max(0, i - half):min(n, i + half + 1)])
            for i in range(n)]


def count_photo_segments(top_left, bottom_right):
    """Считает число светлых полосок-сегментов (индикатор количества фото) в заданной области экрана."""
    x1, y1 = top_left
    x2, y2 = bottom_right
    left, top = int(min(x1, x2)), int(min(y1, y2))
    width, height = int(abs(x2 - x1)), int(abs(y2 - y1))
    if width < 4 or height < 1:
        return 0

    shot = pyautogui.screenshot(region=(left, top, width, height)).convert("L")
    pixels = shot.load()
    col_brightness = [sum(pixels[x, y] for y in range(height)) / height for x in range(width)]

    if max(col_brightness) - min(col_brightness) < 8:
        return 0  # область почти однотонная — полосок не видно (неверная область или нет разрешения на запись экрана)

    # сглаживаем узким окном — гасит одиночные шумовые пиксели (анти-алиасинг/сжатие видео),
    # не трогая настоящие разрывы между полосками
    col_brightness = _smoothed(col_brightness, 3)
    threshold = (max(col_brightness) + min(col_brightness)) / 2
    is_bright = [b >= threshold for b in col_brightness]

    min_segment = 2
    segments = 0
    run = 0
    for bright in is_bright:
        if bright:
            run += 1
            if run == min_segment:
                segments += 1
        else:
            run = 0

    return segments


def is_accessibility_trusted() -> bool:
    if sys.platform != "darwin":
        return True
    try:
        app_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        return bool(app_services.AXIsProcessTrusted())
    except OSError:
        return True


class CoordinatePicker:
    def start_capture(self, on_captured):
        def on_click(x, y, button, pressed):
            if pressed and button == mouse.Button.left:
                on_captured((x, y))
                return False

        listener = mouse.Listener(on_click=on_click)
        listener.start()


class HotkeyMonitor:
    def __init__(self, on_triggered):
        self._listener = keyboard.GlobalHotKeys({STOP_HOTKEY: on_triggered})

    def start(self):
        self._listener.start()

    def stop(self):
        self._listener.stop()


class AutomationEngine:
    def __init__(self, on_state_change):
        self._thread = None
        self._stop_event = threading.Event()
        self.is_running = False
        self._on_state_change = on_state_change

    def start(self, config: AppConfig):
        if self.is_running:
            return
        self._stop_event.clear()
        self.is_running = True
        self._on_state_change(True)
        self._thread = threading.Thread(target=self._run, args=(config,), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def _run(self, config: AppConfig):
        try:
            while not self._stop_event.is_set():
                self._run_drag_batch(config.batch1, config.batch3, config)
                if self._stop_event.is_set():
                    break
                self._run_drag_batch(config.batch2, config.batch3, config)
        except pyautogui.FailSafeException:
            pass
        finally:
            self.is_running = False
            self._on_state_change(False)

    def _run_drag_batch(self, batch: DragBatch, filler: ClickBatch, config: AppConfig):
        for _ in range(max(batch.random_repeat_count(), 0)):
            if self._stop_event.is_set():
                return

            start = batch.random_start_point()
            offset = batch.drag_distance if batch.direction == "right" else -batch.drag_distance
            end = (start[0] + offset, start[1])
            MouseController.drag_click(start, end)
            self._wait_random_delay(config)

            if self._stop_event.is_set():
                return
            for _ in range(max(self._filler_repeat_count(filler), 0)):
                if self._stop_event.is_set():
                    return
                MouseController.click(filler.point)
                self._wait_random_delay(config)

    def _filler_repeat_count(self, filler: ClickBatch) -> int:
        if filler.smart_indicator_enabled:
            try:
                segments = count_photo_segments(filler.indicator_top_left, filler.indicator_bottom_right)
            except Exception:
                segments = 0
            return max(segments - 1, 0)
        return filler.random_repeat_count()

    def _wait_random_delay(self, config: AppConfig):
        lo = min(config.delay_min_seconds, config.delay_max_seconds)
        hi = max(config.delay_min_seconds, config.delay_max_seconds)
        delay = random.uniform(lo, hi) if hi > lo else lo
        self._stop_event.wait(timeout=max(delay, 0))


BG = "#f3f3f5"
CARD_BG = "#ffffff"
BORDER = "#dcdce0"
TEXT = "#1c1c1e"
MUTED = "#6e6e73"
ACCENT = "#0a7cff"
ACCENT_ACTIVE = "#0666d6"
DANGER = "#e5493f"
DANGER_ACTIVE = "#c93d34"


class ClickerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Утилита автокликов")
        root.configure(bg=BG)
        self._center_window(600, 680)
        root.minsize(560, 520)

        self._setup_style()

        self.engine = AutomationEngine(self._on_engine_state_change)
        self.hotkey_monitor = HotkeyMonitor(lambda: self.engine.stop())
        self.hotkey_monitor.start()

        self.status_var = tk.StringVar(value="")
        self.config_path_var = tk.StringVar(value=str(DEFAULT_CONFIG_PATH))

        cfg = self._try_load_default_config()
        self._build_vars(cfg)
        self._build_ui()

    def _center_window(self, width, height):
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        height = min(height, screen_h - 80)
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _setup_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        base_font = ("SF Pro Text", 10) if sys.platform == "darwin" else ("Helvetica", 10)
        bold_font = (base_font[0], base_font[1], "bold")
        mono_font = ("SF Mono", 10) if sys.platform == "darwin" else ("monospace", 10)

        style.configure(".", background=BG, foreground=TEXT, font=base_font)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Card.TLabel", background=CARD_BG, foreground=TEXT)
        style.configure("Card.TCheckbutton", background=CARD_BG, foreground=TEXT)
        style.map("Card.TCheckbutton", background=[("active", CARD_BG)])
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Muted.Card.TLabel", background=CARD_BG, foreground=MUTED)
        style.configure("Header.TLabel", background=BG, foreground=TEXT, font=(base_font[0], 17, "bold"))
        style.configure("SectionTitle.TLabel", background=CARD_BG, foreground=TEXT, font=bold_font)
        style.configure("Warning.TLabel", background=BG, foreground=DANGER, font=base_font)

        style.configure("Card.TLabelframe", background=CARD_BG, bordercolor=BORDER, relief="solid", borderwidth=1)
        style.configure("Card.TLabelframe.Label", background=CARD_BG, foreground=TEXT, font=bold_font)

        style.configure("TEntry", fieldbackground="#ffffff", bordercolor=BORDER, padding=4)
        style.configure("Mono.TEntry", fieldbackground="#ffffff", bordercolor=BORDER, padding=4, font=mono_font)
        style.configure("TSpinbox", fieldbackground="#ffffff", bordercolor=BORDER, padding=4)
        style.configure("TCombobox", fieldbackground="#ffffff", bordercolor=BORDER, padding=4)

        style.configure("TButton", background="#e8e8ed", foreground=TEXT, padding=(10, 6), borderwidth=0)
        style.map("TButton", background=[("active", "#dcdce2")])

        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", padding=(16, 8),
                         font=bold_font, borderwidth=0)
        style.map("Accent.TButton", background=[("active", ACCENT_ACTIVE), ("disabled", "#a9cdf7")])

        style.configure("Danger.TButton", background=DANGER, foreground="#ffffff", padding=(16, 8),
                         font=bold_font, borderwidth=0)
        style.map("Danger.TButton", background=[("active", DANGER_ACTIVE), ("disabled", "#f0b5b0")])

    def _try_load_default_config(self) -> AppConfig:
        if DEFAULT_CONFIG_PATH.exists():
            try:
                self.status_var.set(f"Загружено из {DEFAULT_CONFIG_PATH.name}")
                return load_config(DEFAULT_CONFIG_PATH)
            except Exception as e:
                self.status_var.set(f"Ошибка загрузки: {e}")
        self.status_var.set("Значения по умолчанию")
        return AppConfig()

    def _build_vars(self, cfg: AppConfig):
        def drag_vars(b: DragBatch):
            return dict(
                tlx=tk.IntVar(value=int(b.area_top_left[0])), tly=tk.IntVar(value=int(b.area_top_left[1])),
                brx=tk.IntVar(value=int(b.area_bottom_right[0])), bry=tk.IntVar(value=int(b.area_bottom_right[1])),
                count_min=tk.IntVar(value=b.repeat_min), count_max=tk.IntVar(value=b.repeat_max),
                distance=tk.IntVar(value=b.drag_distance),
                direction=tk.StringVar(value=b.direction),
            )

        self.v1 = drag_vars(cfg.batch1)
        self.v2 = drag_vars(cfg.batch2)
        self.v3 = dict(
            px=tk.IntVar(value=int(cfg.batch3.point[0])), py=tk.IntVar(value=int(cfg.batch3.point[1])),
            count_min=tk.IntVar(value=cfg.batch3.repeat_min), count_max=tk.IntVar(value=cfg.batch3.repeat_max),
            smart_enabled=tk.BooleanVar(value=cfg.batch3.smart_indicator_enabled),
            itlx=tk.IntVar(value=int(cfg.batch3.indicator_top_left[0])),
            itly=tk.IntVar(value=int(cfg.batch3.indicator_top_left[1])),
            ibrx=tk.IntVar(value=int(cfg.batch3.indicator_bottom_right[0])),
            ibry=tk.IntVar(value=int(cfg.batch3.indicator_bottom_right[1])),
        )
        self.delay_min_var = tk.DoubleVar(value=cfg.delay_min_seconds)
        self.delay_max_var = tk.DoubleVar(value=cfg.delay_max_seconds)

    def _gui_to_config(self) -> AppConfig:
        def drag_batch(v):
            return DragBatch((v["tlx"].get(), v["tly"].get()), (v["brx"].get(), v["bry"].get()),
                              v["count_min"].get(), v["count_max"].get(), v["distance"].get(), v["direction"].get())

        return AppConfig(
            batch1=drag_batch(self.v1),
            batch2=drag_batch(self.v2),
            batch3=ClickBatch((self.v3["px"].get(), self.v3["py"].get()),
                               self.v3["count_min"].get(), self.v3["count_max"].get(),
                               self.v3["smart_enabled"].get(),
                               (self.v3["itlx"].get(), self.v3["itly"].get()),
                               (self.v3["ibrx"].get(), self.v3["ibry"].get())),
            delay_min_seconds=self.delay_min_var.get(),
            delay_max_seconds=self.delay_max_var.get(),
        )

    def _build_ui(self):
        footer = tk.Frame(self.root, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        footer.pack(side="bottom", fill="x")

        controls = ttk.Frame(footer, style="Card.TFrame", padding=(20, 14))
        controls.pack(fill="x")
        self.start_btn = ttk.Button(controls, text="▶  Старт", style="Accent.TButton", command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(controls, text=f"■  Стоп   {HOTKEY_LABEL}", style="Danger.TButton",
                                    command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=10)
        self.running_label = ttk.Label(controls, text="", style="Muted.Card.TLabel")
        self.running_label.pack(side="left", padx=6)

        self.warning_label = ttk.Label(
            footer,
            text="⚠️ Нет доступа Accessibility — клики не будут работать.\n"
                 "Настройки → Конфиденциальность и безопасность → Универсальный доступ.",
            style="Warning.TLabel", justify="left", padding=(20, 0, 20, 14),
        )
        if not is_accessibility_trusted():
            self.warning_label.pack(anchor="w", fill="x")

        canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        container = ttk.Frame(canvas, padding=20)
        window_id = canvas.create_window((0, 0), window=container, anchor="nw")
        container.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window_id, width=e.width))

        self._canvas = canvas
        if not getattr(self, "_wheel_bound", False):
            self.root.bind_all("<MouseWheel>", lambda e: self._canvas.yview_scroll(int(-e.delta / 60), "units"))
            self.root.bind_all("<Button-4>", lambda e: self._canvas.yview_scroll(-2, "units"))
            self.root.bind_all("<Button-5>", lambda e: self._canvas.yview_scroll(2, "units"))
            self._wheel_bound = True

        ttk.Label(container, text="Утилита автокликов", style="Header.TLabel").pack(anchor="w", pady=(0, 14))

        self._build_drag_section(container, "Партия 1 — перетягивание вправо", self.v1)
        self._build_drag_section(container, "Партия 2 — перетягивание влево", self.v2)
        self._build_click_section(container, "Партия 3 — простые клики (между перетягиваниями)", self.v3)

        delay_box = self._card(container, "Задержка между действиями, сек")
        row = ttk.Frame(delay_box, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="От:", style="Card.TLabel").pack(side="left")
        ttk.Entry(row, textvariable=self.delay_min_var, width=6, style="Mono.TEntry").pack(side="left", padx=(6, 18))
        ttk.Label(row, text="До:", style="Card.TLabel").pack(side="left")
        ttk.Entry(row, textvariable=self.delay_max_var, width=6, style="Mono.TEntry").pack(side="left", padx=(6, 0))

        path_box = self._card(container, "Файл конфигурации")
        row1 = ttk.Frame(path_box, style="Card.TFrame")
        row1.pack(fill="x")
        ttk.Entry(row1, textvariable=self.config_path_var, style="Mono.TEntry").pack(side="left", fill="x", expand=True)
        ttk.Button(row1, text="Обзор…", command=self._browse_path).pack(side="left", padx=(8, 0))
        row2 = ttk.Frame(path_box, style="Card.TFrame")
        row2.pack(fill="x", pady=(10, 0))
        ttk.Button(row2, text="Сохранить настройки", command=self._save).pack(side="left")
        ttk.Button(row2, text="Загрузить настройки", command=self._load).pack(side="left", padx=8)
        ttk.Label(row2, textvariable=self.status_var, style="Muted.Card.TLabel").pack(side="left", padx=6)

    def _card(self, parent, title):
        box = ttk.Labelframe(parent, text=title, style="Card.TLabelframe", padding=14)
        box.pack(fill="x", pady=(0, 14))
        return box

    def _build_drag_section(self, parent, title, v):
        box = self._card(parent, title)
        self._coord_row(box, "Угол области A", v["tlx"], v["tly"])
        self._coord_row(box, "Угол области Б", v["brx"], v["bry"])

        row0 = ttk.Frame(box, style="Card.TFrame")
        row0.pack(fill="x", pady=(10, 0))
        ttk.Label(row0, text="Повторов: от", style="Card.TLabel").pack(side="left")
        ttk.Spinbox(row0, from_=0, to=999, textvariable=v["count_min"], width=4).pack(side="left", padx=(6, 4))
        ttk.Label(row0, text="до", style="Card.TLabel").pack(side="left")
        ttk.Spinbox(row0, from_=0, to=999, textvariable=v["count_max"], width=4).pack(side="left", padx=(4, 0))

        row = ttk.Frame(box, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Дистанция перетягивания, px:", style="Card.TLabel").pack(side="left")
        ttk.Entry(row, textvariable=v["distance"], width=6, style="Mono.TEntry").pack(side="left", padx=(6, 18))
        ttk.Label(row, text="Направление:", style="Card.TLabel").pack(side="left")
        ttk.Combobox(row, textvariable=v["direction"], values=["right", "left"], width=6,
                     state="readonly").pack(side="left", padx=(6, 0))

        ttk.Label(
            box,
            text="Дистанция — на сколько пикселей палец сдвинется за одно перетягивание "
                 "(влево или вправо от случайной точки в области).",
            style="Muted.Card.TLabel", wraplength=480, justify="left",
        ).pack(anchor="w", pady=(6, 0))

    def _build_click_section(self, parent, title, v):
        box = self._card(parent, title)
        self._coord_row(box, "Точка клика", v["px"], v["py"])
        row = ttk.Frame(box, style="Card.TFrame")
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text="Кликов между перетягиваниями: от", style="Card.TLabel").pack(side="left")
        ttk.Spinbox(row, from_=0, to=999, textvariable=v["count_min"], width=4).pack(side="left", padx=(6, 4))
        ttk.Label(row, text="до", style="Card.TLabel").pack(side="left")
        ttk.Spinbox(row, from_=0, to=999, textvariable=v["count_max"], width=4).pack(side="left", padx=(4, 0))

        ttk.Checkbutton(
            box, text="Определять число кликов по индикатору фото (вместо диапазона выше)",
            variable=v["smart_enabled"], style="Card.TCheckbutton",
        ).pack(anchor="w", pady=(10, 4))
        self._coord_row(box, "Угол индикатора A", v["itlx"], v["itly"])
        self._coord_row(box, "Угол индикатора Б", v["ibrx"], v["ibry"])
        ttk.Label(
            box,
            text="Если включено — перед кликами программа сфотографирует эту область (узкая полоска "
                 "над фото профиля), посчитает светлые сегменты и кликнет на один раз меньше, чем их число. "
                 "Требует разрешение macOS «Запись экрана» в дополнение к «Универсальному доступу».",
            style="Muted.Card.TLabel", wraplength=480, justify="left",
        ).pack(anchor="w", pady=(6, 0))

    def _coord_row(self, parent, label, x_var, y_var):
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=15, style="Card.TLabel").pack(side="left")
        ttk.Entry(row, textvariable=x_var, width=6, style="Mono.TEntry").pack(side="left", padx=3)
        ttk.Entry(row, textvariable=y_var, width=6, style="Mono.TEntry").pack(side="left", padx=3)
        btn = ttk.Button(row, text="Пипетка")
        btn.configure(command=lambda: self._pick_coordinate(btn, x_var, y_var))
        btn.pack(side="left", padx=(8, 0))

    def _pick_coordinate(self, button, x_var, y_var):
        button.configure(text="Кликните на экране…", state="disabled")

        def on_captured(point):
            def apply():
                x_var.set(int(point[0]))
                y_var.set(int(point[1]))
                button.configure(text="Пипетка", state="normal")
            self.root.after(0, apply)

        CoordinatePicker().start_capture(on_captured)

    def _browse_path(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="config.json",
                                             filetypes=[("JSON", "*.json")])
        if path:
            self.config_path_var.set(path)

    def _save(self):
        try:
            save_config(self._gui_to_config(), Path(self.config_path_var.get()))
            self.status_var.set(f"Сохранено: {self.config_path_var.get()}")
        except Exception as e:
            self.status_var.set(f"Ошибка сохранения: {e}")

    def _load(self):
        try:
            cfg = load_config(Path(self.config_path_var.get()))
            self._build_vars(cfg)
            for child in self.root.winfo_children():
                child.destroy()
            self._build_ui()
            self.status_var.set(f"Загружено: {self.config_path_var.get()}")
        except Exception as e:
            self.status_var.set(f"Ошибка загрузки: {e}")

    def _start(self):
        self._save()
        self.engine.start(self._gui_to_config())

    def _stop(self):
        self.engine.stop()

    def _on_engine_state_change(self, is_running: bool):
        def apply():
            self.start_btn.configure(state="disabled" if is_running else "normal")
            self.stop_btn.configure(state="normal" if is_running else "disabled")
            self.running_label.configure(text="Выполняется…" if is_running else "")
        self.root.after(0, apply)


def main():
    root = tk.Tk()
    ClickerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
