import json
import os
import random
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    VLC_RUNTIME = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    VLC_DLL_HANDLE = os.add_dll_directory(str(VLC_RUNTIME))
    os.environ["VLC_PLUGIN_PATH"] = str(VLC_RUNTIME / "plugins")

import vlc
from mutagen import File as MutagenFile
from mutagen.id3 import ID3, TIT2, TPE1, TCON, TDRC, APIC
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QLabel, QSlider, QFileDialog, QLineEdit, QTabWidget,
    QFormLayout, QComboBox, QCheckBox, QMessageBox, QInputDialog, QSpinBox, QListWidgetItem,
    QFrame, QStackedWidget
)

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DATA = ROOT / "data"
PLAYLISTS = DATA / "playlists"
CONFIG = ROOT / "config"
for folder in (DATA, PLAYLISTS, CONFIG):
    folder.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS = {
    "search_enabled": True,
    "scan_roots": [],
    "excluded_paths": [],
    "scan_video": True,
    "theme": "Яндекс Музыка",
    "accent": "#F5C400",
    "font": "Segoe UI",
    "font_size": 10,
    "volume": 70,
    "eq_enabled": False,
    "eq_values": [0] * 10
}
SETTINGS_FILE = CONFIG / "settings.json"
UI_FILE = CONFIG / "ui.json"

def load_json(path, default):
    if not path.exists():
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
        return default.copy()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default.copy()

class MediaPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
        self.ui_config = load_json(UI_FILE, {"active_preset": "Яндекс Музыка", "presets": {"Яндекс Музыка": {"background": "#121214", "panel": "#1B1B1F", "sidebar": "#151518", "accent": "#F5C400", "text": "#F7F7F8", "muted": "#A5A5AC"}, "Spotify": {"background": "#121212", "panel": "#181818", "sidebar": "#101010", "accent": "#1ED760", "text": "#FFFFFF", "muted": "#A7A7A7"}, "SoundCloud": {"background": "#101010", "panel": "#1A1A1A", "sidebar": "#141414", "accent": "#FF5500", "text": "#FFFFFF", "muted": "#A8A8A8"}}})
        active_preset = self.ui_config.get("active_preset")
        if active_preset in self.ui_config.get("presets", {}):
            self.settings["theme"] = active_preset
        self.instance = vlc.Instance("--no-video-title-show")
        self.player = self.instance.media_player_new()
        self.library = []
        self.current_index = -1
        self.repeat_mode = "off"
        self.shuffle = False
        self.user_seeking = False
        self.current_playlist = []
        self.setWindowTitle("MediaPlayer")
        self.resize(1120, 720)
        self.build_ui()
        self.apply_theme()
        self.player.audio_set_volume(int(self.settings.get("volume", 70)))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_position)
        self.timer.start(400)

    def build_ui(self):
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(root)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(218)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(18, 24, 18, 18)
        side.setSpacing(9)
        brand = QLabel("MEDIA PLAYER")
        brand.setObjectName("brand")
        side.addWidget(brand)
        side.addSpacing(22)
        self.nav_buttons = []
        for symbol, label, page in [("⌂", "Обзор", 0), ("♫", "Медиатека", 1), ("▤", "Плейлисты", 1), ("◒", "Эквалайзер", 2), ("✎", "Редактор тегов", 3), ("⚙", "Настройки", 4)]:
            btn = QPushButton(f"{symbol}   {label}")
            btn.setObjectName("navButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=page, item=btn: self.show_page(i, item))
            side.addWidget(btn)
            self.nav_buttons.append(btn)
        side.addStretch()
        hint = QLabel("Локальная музыка без копирования исходных файлов")
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        side.addWidget(hint)
        outer.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        self.pages.setObjectName("contentStack")

        home = QWidget()
        home_layout = QVBoxLayout(home)
        home_layout.setContentsMargins(30, 28, 30, 28)
        home_layout.setSpacing(18)
        title = QLabel("Ваша музыка")
        title.setObjectName("pageTitle")
        home_layout.addWidget(title)
        subtitle = QLabel("Вся локальная коллекция — в одном месте.")
        subtitle.setObjectName("mutedText")
        home_layout.addWidget(subtitle)
        hero = QFrame()
        hero.setObjectName("heroCard")
        hero_layout = QVBoxLayout(hero)
        hero_title = QLabel("Продолжайте слушать")
        hero_title.setObjectName("heroTitle")
        hero_layout.addWidget(hero_title)
        self.overview_now = QLabel("Добавьте музыку или синхронизируйте выбранные папки.")
        self.overview_now.setObjectName("mutedText")
        self.overview_now.setWordWrap(True)
        hero_layout.addWidget(self.overview_now)
        hero_actions = QHBoxLayout()
        add_home = QPushButton("Добавить файлы")
        add_home.clicked.connect(self.add_files)
        sync_home = QPushButton("Синхронизировать")
        sync_home.clicked.connect(self.scan_library)
        hero_actions.addWidget(add_home)
        hero_actions.addWidget(sync_home)
        hero_actions.addStretch()
        hero_layout.addLayout(hero_actions)
        home_layout.addWidget(hero)
        self.library_summary = QLabel("В медиатеке пока нет файлов")
        self.library_summary.setObjectName("sectionTitle")
        home_layout.addWidget(self.library_summary)
        home_layout.addStretch()
        self.pages.addWidget(home)

        library_page = QWidget()
        lib = QVBoxLayout(library_page)
        lib.setContentsMargins(30, 28, 30, 24)
        lib.setSpacing(14)
        lib_title = QLabel("Медиатека")
        lib_title.setObjectName("pageTitle")
        lib.addWidget(lib_title)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по медиатеке")
        self.search.textChanged.connect(self.filter_library)
        top.addWidget(self.search, 1)
        add = QPushButton("Добавить файлы")
        add.clicked.connect(self.add_files)
        top.addWidget(add)
        sync = QPushButton("Синхронизировать")
        sync.clicked.connect(self.scan_library)
        top.addWidget(sync)
        lib.addLayout(top)
        self.track_list = QListWidget()
        self.track_list.setObjectName("trackList")
        self.track_list.itemDoubleClicked.connect(self.play_selected)
        self.track_list.currentItemChanged.connect(self.on_track_selected)
        lib.addWidget(self.track_list, 1)
        actions = QHBoxLayout()
        for label, callback in [("Новый плейлист", self.create_playlist), ("Сохранить плейлист", self.save_playlist), ("Открыть плейлист", self.open_playlist), ("Удалить из списка", self.remove_track)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        lib.addLayout(actions)
        self.pages.addWidget(library_page)

        eq_page = QWidget()
        eq = QVBoxLayout(eq_page)
        eq.setContentsMargins(30, 28, 30, 24)
        eq_title = QLabel("Эквалайзер")
        eq_title.setObjectName("pageTitle")
        eq.addWidget(eq_title)
        self.eq_enabled = QCheckBox("Включить эквалайзер")
        self.eq_enabled.setChecked(self.settings.get("eq_enabled", False))
        eq.addWidget(self.eq_enabled)
        self.eq_sliders = []
        frequencies = ["60 Hz", "170 Hz", "310 Hz", "600 Hz", "1 kHz", "3 kHz", "6 kHz", "12 kHz", "14 kHz", "16 kHz"]
        values = self.settings.get("eq_values", [0] * 10)
        for i, freq in enumerate(frequencies):
            line = QHBoxLayout()
            line.addWidget(QLabel(freq))
            slider = QSlider(Qt.Horizontal)
            slider.setRange(-20, 20)
            slider.setValue(int(values[i]) if i < len(values) else 0)
            line.addWidget(slider)
            eq.addLayout(line)
            self.eq_sliders.append(slider)
        presets = QHBoxLayout()
        for name, vals in [("Речь", [-4,-3,-2,2,4,5,3,1,0,0]), ("Бас", [8,7,5,2,0,-2,-3,-3,-2,-2]), ("Спокойный", [2,1,0,1,2,1,0,-1,-2,-2]), ("Сброс", [0]*10)]:
            button = QPushButton(name)
            button.clicked.connect(lambda checked=False, v=vals: self.set_eq_values(v))
            presets.addWidget(button)
        eq.addLayout(presets)
        save_eq = QPushButton("Сохранить эквалайзер")
        save_eq.clicked.connect(self.save_settings)
        eq.addWidget(save_eq)
        eq.addStretch()
        self.pages.addWidget(eq_page)

        tags_page = QWidget()
        tag_form = QFormLayout(tags_page)
        tag_form.setContentsMargins(30, 28, 30, 24)
        tag_title = QLabel("Редактор тегов")
        tag_title.setObjectName("pageTitle")
        tag_form.addRow(tag_title)
        self.tag_title = QLineEdit()
        self.tag_artist = QLineEdit()
        self.tag_genre = QLineEdit()
        self.tag_date = QLineEdit()
        self.cover_path = QLineEdit()
        self.tag_file = QLabel("Выберите трек в медиатеке")
        cover_btn = QPushButton("Выбрать обложку")
        cover_btn.clicked.connect(self.choose_cover)
        tag_form.addRow(self.tag_file)
        tag_form.addRow("Название", self.tag_title)
        tag_form.addRow("Исполнитель", self.tag_artist)
        tag_form.addRow("Жанр", self.tag_genre)
        tag_form.addRow("Год / дата", self.tag_date)
        tag_form.addRow("Файл обложки", self.cover_path)
        tag_form.addRow(cover_btn)
        save_tags = QPushButton("Записать теги в файл")
        save_tags.clicked.connect(self.save_tags)
        tag_form.addRow(save_tags)
        self.pages.addWidget(tags_page)

        settings_page = QWidget()
        form = QFormLayout(settings_page)
        form.setContentsMargins(30, 28, 30, 24)
        form.setVerticalSpacing(14)
        settings_title = QLabel("Настройки")
        settings_title.setObjectName("pageTitle")
        form.addRow(settings_title)
        self.search_enabled = QCheckBox("Искать аудио при синхронизации")
        self.search_enabled.setChecked(self.settings.get("search_enabled", True))
        form.addRow(self.search_enabled)
        self.scan_video = QCheckBox("Искать видеофайлы и воспроизводить их аудиодорожку")
        self.scan_video.setChecked(self.settings.get("scan_video", True))
        form.addRow(self.scan_video)
        self.roots_label = QLabel("\n".join(self.settings.get("scan_roots", [])) or "Папки не выбраны")
        roots_btn = QPushButton("Выбрать диски и папки")
        roots_btn.clicked.connect(self.add_scan_root)
        form.addRow(roots_btn, self.roots_label)
        self.excluded_label = QLabel("\n".join(self.settings.get("excluded_paths", [])) or "Исключений нет")
        exclude_btn = QPushButton("Исключить папку или диск")
        exclude_btn.clicked.connect(self.add_exclusion)
        form.addRow(exclude_btn, self.excluded_label)
        self.theme = QComboBox()
        self.theme.addItems(["Яндекс Музыка", "Spotify", "SoundCloud", "Свой стиль"])
        self.theme.setCurrentText(self.settings.get("theme", "Яндекс Музыка"))
        self.theme.currentTextChanged.connect(self.change_theme)
        form.addRow("Оформление", self.theme)
        self.accent = QLineEdit(self.settings.get("accent", "#F5C400"))
        form.addRow("Цвет акцента", self.accent)
        self.font = QLineEdit(self.settings.get("font", "Segoe UI"))
        form.addRow("Шрифт", self.font)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 24)
        self.font_size.setValue(int(self.settings.get("font_size", 10)))
        form.addRow("Размер шрифта", self.font_size)
        save = QPushButton("Сохранить настройки")
        save.clicked.connect(self.save_settings)
        form.addRow(save)
        self.preset_name = QLineEdit()
        self.preset_name.setPlaceholderText("Название пользовательского пресета")
        save_preset = QPushButton("Сохранить пресет")
        save_preset.clicked.connect(self.save_ui_preset)
        form.addRow(self.preset_name, save_preset)
        self.preset_selector = QComboBox()
        self.preset_selector.addItems(sorted(self.ui_config.get("presets", {}).keys()))
        load_preset = QPushButton("Применить пресет")
        load_preset.clicked.connect(self.load_ui_preset)
        form.addRow(self.preset_selector, load_preset)
        self.pages.addWidget(settings_page)

        outer.addWidget(self.pages, 1)

        self.player_panel = QFrame()
        self.player_panel.setObjectName("playerPanel")
        self.player_panel.setFixedWidth(276)
        player_layout = QVBoxLayout(self.player_panel)
        player_layout.setContentsMargins(18, 24, 18, 20)
        player_layout.setSpacing(14)
        panel_heading = QLabel("СЕЙЧАС ИГРАЕТ")
        panel_heading.setObjectName("eyebrow")
        player_layout.addWidget(panel_heading)
        self.cover_art = QLabel("♫")
        self.cover_art.setObjectName("coverPlaceholder")
        self.cover_art.setAlignment(Qt.AlignCenter)
        self.cover_art.setMinimumHeight(210)
        player_layout.addWidget(self.cover_art)
        self.now_playing = QLabel("Ничего не воспроизводится")
        self.now_playing.setObjectName("trackTitle")
        self.now_playing.setWordWrap(True)
        self.now_playing.setAlignment(Qt.AlignCenter)
        player_layout.addWidget(self.now_playing)
        self.track_position = QSlider(Qt.Horizontal)
        self.track_position.sliderPressed.connect(lambda: setattr(self, "user_seeking", True))
        self.track_position.sliderReleased.connect(self.seek)
        player_layout.addWidget(self.track_position)
        times = QHBoxLayout()
        self.elapsed = QLabel("00:00")
        self.duration = QLabel("00:00")
        times.addWidget(self.elapsed)
        times.addStretch()
        times.addWidget(self.duration)
        player_layout.addLayout(times)
        controls = QHBoxLayout()
        for label, callback in [("⏮", self.previous_track), ("▶ / ⏸", self.toggle_play), ("⏭", self.next_track), ("Перемешать", self.toggle_shuffle), ("Повтор: выкл.", self.toggle_repeat)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
            if label.startswith("Повтор"):
                self.repeat_button = button
        player_layout.addLayout(controls)
        volume_row = QHBoxLayout()
        volume_row.addWidget(QLabel("Громкость"))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(self.settings.get("volume", 70)))
        self.volume.valueChanged.connect(self.set_volume)
        volume_row.addWidget(self.volume)
        player_layout.addLayout(volume_row)
        player_layout.addStretch()
        outer.addWidget(self.player_panel)

        self.show_page(0, self.nav_buttons[0])
        menu = self.menuBar().addMenu("Файл")
        open_action = QAction("Открыть файлы", self)
        open_action.triggered.connect(self.add_files)
        menu.addAction(open_action)
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.close)
        menu.addAction(exit_action)

    def show_page(self, index, active_button=None):
        self.pages.setCurrentIndex(index)
        for button in self.nav_buttons:
            button.setProperty("active", button is active_button)
            button.style().unpolish(button)
            button.style().polish(button)
        if index == 0:
            self.update_overview()

    def update_overview(self):
        count = len(self.library)
        self.library_summary.setText(f"В медиатеке: {count} файлов")
        if 0 <= self.current_index < count:
            self.overview_now.setText(self.display_name(self.library[self.current_index]))
        elif count:
            self.overview_now.setText(f"В вашей медиатеке {count} файлов. Выберите трек, чтобы начать воспроизведение.")
        else:
            self.overview_now.setText("Добавьте музыку или синхронизируйте выбранные папки.")

    def supported_extensions(self):
        audio = {".mp3", ".ogg", ".oga", ".wav", ".flac", ".m4a", ".aac", ".opus", ".wma", ".aiff"}
        video = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".mpeg", ".mpg", ".wmv", ".m4v"}
        return audio | (video if self.settings.get("scan_video", True) else set())

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Добавить медиафайлы")
        for file in files:
            self.add_to_library(file)

    def add_to_library(self, file):
        path = str(Path(file).resolve())
        if path not in self.library and Path(path).suffix.lower() in self.supported_extensions():
            self.library.append(path)
            item = QListWidgetItem(self.display_name(path))
            item.setData(Qt.UserRole, path)
            self.track_list.addItem(item)
            self.update_overview()

    def display_name(self, path):
        try:
            media = MutagenFile(path, easy=True)
            if media:
                title = media.get("title", [None])[0]
                artist = media.get("artist", [None])[0]
                if title:
                    return f"{title} — {artist}" if artist else title
        except Exception:
            pass
        return Path(path).name

    def filter_library(self, query):
        self.track_list.clear()
        for path in self.library:
            if query.casefold() in self.display_name(path).casefold():
                item = QListWidgetItem(self.display_name(path))
                item.setData(Qt.UserRole, path)
                self.track_list.addItem(item)

    def scan_library(self):
        if not self.search_enabled.isChecked():
            QMessageBox.information(self, "Синхронизация", "Поиск медиатеки отключён в настройках.")
            return
        roots = self.settings.get("scan_roots", [])
        excluded = [str(Path(x).resolve()) for x in self.settings.get("excluded_paths", [])]
        if not roots:
            QMessageBox.information(self, "Синхронизация", "Сначала выберите диски или папки в настройках.")
            return
        found = 0
        for root in roots:
            for current, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if not any(str(Path(current, d).resolve()).startswith(e) for e in excluded)]
                for name in files:
                    path = str(Path(current, name).resolve())
                    if Path(name).suffix.lower() in self.supported_extensions() and path not in self.library:
                        self.add_to_library(path)
                        found += 1
        QMessageBox.information(self, "Синхронизация", f"Добавлено файлов: {found}")

    def add_scan_root(self):
        path = QFileDialog.getExistingDirectory(self, "Выберите папку или корень диска")
        if path and path not in self.settings["scan_roots"]:
            self.settings["scan_roots"].append(path)
            self.roots_label.setText("\n".join(self.settings["scan_roots"]))

    def add_exclusion(self):
        path = QFileDialog.getExistingDirectory(self, "Исключить папку")
        if path and path not in self.settings["excluded_paths"]:
            self.settings["excluded_paths"].append(path)
            self.excluded_label.setText("\n".join(self.settings["excluded_paths"]))

    def create_playlist(self):
        name, ok = QInputDialog.getText(self, "Новый плейлист", "Название:")
        if ok and name.strip():
            self.current_playlist = []
            self.setWindowTitle(f"MediaPlayer — {name.strip()}")

    def save_playlist(self):
        name, ok = QInputDialog.getText(self, "Сохранить плейлист", "Имя файла:")
        if not ok or not name.strip():
            return
        paths = [item.data(Qt.UserRole) for item in self.track_list.selectedItems()]
        if not paths:
            paths = self.library[:]
        safe = "".join(c for c in name.strip() if c.isalnum() or c in " _-")
        (PLAYLISTS / f"{safe}.json").write_text(json.dumps({"name": name, "tracks": paths}, ensure_ascii=False, indent=2), encoding="utf-8")

    def open_playlist(self):
        file, _ = QFileDialog.getOpenFileName(self, "Открыть плейлист", str(PLAYLISTS), "Плейлисты (*.json)")
        if not file:
            return
        data = json.loads(Path(file).read_text(encoding="utf-8"))
        self.library = [p for p in data.get("tracks", []) if Path(p).exists()]
        self.track_list.clear()
        for path in self.library:
            item = QListWidgetItem(self.display_name(path))
            item.setData(Qt.UserRole, path)
            self.track_list.addItem(item)

    def remove_track(self):
        item = self.track_list.currentItem()
        if item:
            path = item.data(Qt.UserRole)
            self.track_list.takeItem(self.track_list.row(item))
            if path in self.library:
                self.library.remove(path)
            self.current_index = -1

    def on_track_selected(self, current, previous=None):
        if current:
            path = current.data(Qt.UserRole)
            if path:
                self.load_tags(path)

    def play_selected(self):
        item = self.track_list.currentItem()
        if item:
            path = item.data(Qt.UserRole)
            if path in self.library:
                self.current_index = self.library.index(path)
                self.play_index(self.current_index)

    def play_index(self, index):
        if not self.library:
            return
        index %= len(self.library)
        self.current_index = index
        media = self.instance.media_new(self.library[index])
        self.player.set_media(media)
        self.player.play()
        self.now_playing.setText(self.display_name(self.library[index]))
        self.overview_now.setText(self.display_name(self.library[index]))
        self.cover_art.setText("♫")
        self.load_tags(self.library[index])
        self.apply_equalizer()

    def toggle_play(self):
        if self.player.is_playing():
            self.player.pause()
        elif self.current_index >= 0:
            self.player.play()
        elif self.library:
            self.play_index(0)

    def next_track(self):
        if self.library:
            self.play_index(random.randrange(len(self.library)) if self.shuffle else self.current_index + 1)

    def previous_track(self):
        if self.library:
            self.play_index(self.current_index - 1)

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle

    def toggle_repeat(self):
        self.repeat_mode = {"off": "all", "all": "one", "one": "off"}[self.repeat_mode]
        self.repeat_button.setText({"off": "Повтор: выкл.", "all": "Повтор: список", "one": "Повтор: трек"}[self.repeat_mode])

    def refresh_position(self):
        if self.current_index < 0:
            return
        length = self.player.get_length()
        position = self.player.get_time()
        if length > 0 and not self.user_seeking:
            self.track_position.setRange(0, length)
            self.track_position.setValue(max(0, position))
            self.elapsed.setText(self.format_time(position))
            self.duration.setText(self.format_time(length))
        if self.player.get_state() == vlc.State.Ended:
            if self.repeat_mode == "one":
                self.play_index(self.current_index)
            elif self.repeat_mode == "all" or self.current_index < len(self.library) - 1:
                self.next_track()

    def format_time(self, ms):
        sec = max(0, ms // 1000)
        return f"{sec // 60:02d}:{sec % 60:02d}"

    def seek(self):
        self.player.set_time(self.track_position.value())
        self.user_seeking = False

    def set_volume(self, value):
        self.player.audio_set_volume(value)
        self.settings["volume"] = value

    def set_eq_values(self, values):
        for slider, value in zip(self.eq_sliders, values):
            slider.setValue(value)

    def apply_equalizer(self):
        if not self.eq_enabled.isChecked():
            self.player.audio_set_equalizer(None)
            return
        eq = vlc.AudioEqualizer()
        for index, slider in enumerate(self.eq_sliders):
            try:
                eq.set_amp_at_index(float(slider.value()), index)
            except Exception:
                pass
        self.player.audio_set_equalizer(eq)

    def load_tags(self, path):
        self.tag_file.setText(Path(path).name)
        try:
            tags = MutagenFile(path, easy=True)
            self.tag_title.setText(tags.get("title", [""])[0] if tags else "")
            self.tag_artist.setText(tags.get("artist", [""])[0] if tags else "")
            self.tag_genre.setText(tags.get("genre", [""])[0] if tags else "")
            self.tag_date.setText(tags.get("date", [""])[0] if tags else "")
        except Exception:
            self.tag_title.clear()
            self.tag_artist.clear()
            self.tag_genre.clear()
            self.tag_date.clear()

    def save_tags(self):
        selected = self.track_list.currentItem() if hasattr(self, "track_list") else None
        path = selected.data(Qt.UserRole) if selected else None
        if not path and 0 <= self.current_index < len(self.library):
            path = self.library[self.current_index]
        if not path or not Path(path).is_file():
            QMessageBox.warning(self, "Теги", "Сначала выберите файл в медиатеке.")
            return
        try:
            audio = MutagenFile(path, easy=True)
            if audio is None:
                raise ValueError("Формат не поддерживает редактирование тегов.")
            audio["title"] = self.tag_title.text()
            audio["artist"] = self.tag_artist.text()
            audio["genre"] = self.tag_genre.text()
            if self.tag_date.text():
                audio["date"] = self.tag_date.text()
            audio.save()
            cover = self.cover_path.text().strip()
            if cover and Path(cover).is_file() and Path(path).suffix.lower() == ".mp3":
                tags = ID3(path)
                tags.delall("APIC")
                tags.add(APIC(encoding=3, mime="image/jpeg" if cover.lower().endswith((".jpg", ".jpeg")) else "image/png", type=3, desc="Cover", data=Path(cover).read_bytes()))
                tags.save(path)
            QMessageBox.information(self, "Теги", "Теги сохранены.")
            self.filter_library(self.search.text())
        except Exception as exc:
            QMessageBox.warning(self, "Теги", str(exc))

    def choose_cover(self):
        file, _ = QFileDialog.getOpenFileName(self, "Обложка", "", "Изображения (*.jpg *.jpeg *.png)")
        if file:
            self.cover_path.setText(file)

    def change_theme(self, name):
        self.settings["theme"] = name
        if name in self.ui_config.get("presets", {}):
            self.ui_config["active_preset"] = name
            UI_FILE.write_text(json.dumps(self.ui_config, ensure_ascii=False, indent=2), encoding="utf-8")
        self.apply_theme()

    def apply_theme(self):
        presets = self.ui_config.get("presets", {})
        theme_name = self.settings.get("theme", "Яндекс Музыка")
        preset = presets.get(theme_name, presets.get("Яндекс Музыка", {}))
        if theme_name == "Свой стиль":
            preset = {"background": "#171717", "panel": "#202020", "sidebar": "#151515", "accent": self.accent.text() if hasattr(self, "accent") else "#7C5CFC", "text": "#FFFFFF", "muted": "#AAAAAA"}
        bg = preset.get("background", "#121214")
        panel = preset.get("panel", "#1B1B1F")
        sidebar = preset.get("sidebar", "#151518")
        accent = preset.get("accent", "#F5C400")
        fg = preset.get("text", "#F7F7F8")
        muted = preset.get("muted", "#A5A5AC")
        layout_mode = preset.get("layout", "hero-library-player")
        sidebar_width, player_width, card_radius, nav_padding, row_padding = {
            "hero-library-player": (218, 276, 16, 12, 11),
            "library-main-now-playing": (224, 292, 10, 10, 9),
            "stream-library-player": (196, 260, 7, 9, 8)
        }.get(layout_mode, (218, 276, 12, 10, 9))
        if hasattr(self, "sidebar"):
            self.sidebar.setFixedWidth(sidebar_width)
        if hasattr(self, "player_panel"):
            self.player_panel.setFixedWidth(player_width)
        if hasattr(self, "accent") and theme_name == "Свой стиль":
            accent = self.accent.text() or accent
        font = self.font.text() if hasattr(self, "font") else self.settings.get("font", "Segoe UI")
        size = self.font_size.value() if hasattr(self, "font_size") else self.settings.get("font_size", 10)
        self.setFont(QFont(font, size))
        self.setStyleSheet(f"""
            QMainWindow,QWidget#contentStack {{ background:{bg}; color:{fg}; }}
            QWidget {{ color:{fg}; }}
            QFrame#sidebar {{ background:{sidebar}; border:0; }}
            QFrame#playerPanel {{ background:{panel}; border-left:1px solid #303035; }}
            QLabel#brand {{ color:{accent}; font-size:17px; font-weight:800; letter-spacing:2px; }}
            QLabel#pageTitle {{ font-size:28px; font-weight:750; }}
            QLabel#heroTitle {{ font-size:22px; font-weight:700; }}
            QLabel#sectionTitle {{ font-size:16px; font-weight:650; }}
            QLabel#trackTitle {{ font-size:15px; font-weight:650; }}
            QLabel#eyebrow {{ color:{muted}; font-size:10px; font-weight:700; letter-spacing:1.5px; }}
            QLabel#mutedText {{ color:{muted}; }}
            QLabel#coverPlaceholder {{ background:{bg}; border:1px solid #34343A; border-radius:14px; color:{accent}; font-size:68px; }}
            QFrame#heroCard {{ background:{panel}; border:1px solid #303035; border-radius:{card_radius}px; padding:18px; }}
            QPushButton {{ background:#29292E; border:0; border-radius:9px; padding:10px 13px; color:{fg}; }}
            QPushButton:hover {{ background:{accent}; color:#111111; }}
            QPushButton#navButton {{ background:transparent; color:{muted}; text-align:left; padding:{nav_padding}px 13px; border-radius:{card_radius}px; }}
            QPushButton#navButton:hover {{ background:#29292E; color:{fg}; }}
            QPushButton#navButton[active="true"] {{ background:{panel}; color:{accent}; font-weight:700; }}
            QLineEdit,QListWidget,QComboBox,QSpinBox {{ background:{panel}; border:1px solid #38383F; border-radius:8px; padding:8px; color:{fg}; selection-background-color:{accent}; }}
            QListWidget#trackList {{ border:0; background:{bg}; alternate-background-color:{panel}; padding:6px; }}
            QListWidget::item {{ padding:{row_padding}px 10px; border-radius:{card_radius}px; }}
            QListWidget::item:selected {{ background:{panel}; color:{accent}; }}
            QCheckBox {{ spacing:9px; }}
            QSlider::groove:horizontal {{ height:5px; background:#45454B; border-radius:2px; }}
            QSlider::handle:horizontal {{ background:{accent}; width:13px; height:13px; margin:-5px 0; border-radius:6px; }}
            QMenuBar {{ background:{sidebar}; color:{fg}; }}
            QMenuBar::item:selected {{ background:{panel}; }}
            QMenu {{ background:{panel}; color:{fg}; border:1px solid #38383F; }}
        """)

    def save_ui_preset(self):
        name = self.preset_name.text().strip()
        if not name:
            return
        self.ui_config.setdefault("presets", {})[name] = {
            "theme": self.theme.currentText(), "accent": self.accent.text(),
            "font": self.font.text(), "font_size": self.font_size.value()
        }
        UI_FILE.write_text(json.dumps(self.ui_config, ensure_ascii=False, indent=2), encoding="utf-8")
        if self.preset_selector.findText(name) < 0:
            self.preset_selector.addItem(name)
        self.preset_selector.setCurrentText(name)

    def load_ui_preset(self):
        preset_name = self.preset_selector.currentText()
        preset = self.ui_config.get("presets", {}).get(preset_name)
        if not preset:
            return
        theme_name = preset.get("theme", preset_name)
        if theme_name not in self.ui_config.get("presets", {}):
            theme_name = "Свой стиль"
        self.theme.setCurrentText(theme_name)
        self.accent.setText(preset.get("accent", preset.get("accent_color", "#F5C400")))
        self.font.setText(preset.get("font", "Segoe UI"))
        self.font_size.setValue(int(preset.get("font_size", 10)))
        self.settings["theme"] = theme_name
        self.settings["accent"] = self.accent.text()
        self.settings["font"] = self.font.text()
        self.settings["font_size"] = self.font_size.value()
        if theme_name in self.ui_config.get("presets", {}):
            self.ui_config["active_preset"] = theme_name
        self.apply_theme()

    def save_settings(self):
        self.settings.update({
            "search_enabled": self.search_enabled.isChecked(),
            "scan_video": self.scan_video.isChecked(),
            "theme": self.theme.currentText(), "accent": self.accent.text(),
            "font": self.font.text(), "font_size": self.font_size.value(),
            "volume": self.volume.value(), "eq_enabled": self.eq_enabled.isChecked(),
            "eq_values": [s.value() for s in self.eq_sliders]
        })
        SETTINGS_FILE.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
        self.apply_theme()
        self.apply_equalizer()
        QMessageBox.information(self, "Настройки", "Настройки сохранены.")

    def closeEvent(self, event):
        self.player.stop()
        self.save_settings_silent()
        UI_FILE.write_text(json.dumps(self.ui_config, ensure_ascii=False, indent=2), encoding="utf-8")
        event.accept()

    def save_settings_silent(self):
        self.settings["volume"] = self.volume.value()
        self.settings["eq_enabled"] = self.eq_enabled.isChecked()
        self.settings["eq_values"] = [s.value() for s in self.eq_sliders]
        SETTINGS_FILE.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MediaPlayer()
    window.show()
    sys.exit(app.exec())
