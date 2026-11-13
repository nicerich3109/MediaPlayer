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
    QFormLayout, QComboBox, QCheckBox, QMessageBox, QInputDialog, QSpinBox, QListWidgetItem
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
    "theme": "Spotify",
    "accent": "#1DB954",
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
        self.ui_config = load_json(UI_FILE, {"presets": {}})
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
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        library_page = QWidget()
        lib = QVBoxLayout(library_page)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по медиатеке")
        self.search.textChanged.connect(self.filter_library)
        top.addWidget(self.search)
        add = QPushButton("Добавить файлы")
        add.clicked.connect(self.add_files)
        top.addWidget(add)
        sync = QPushButton("Синхронизировать")
        sync.clicked.connect(self.scan_library)
        top.addWidget(sync)
        lib.addLayout(top)
        self.track_list = QListWidget()
        self.track_list.itemDoubleClicked.connect(self.play_selected)
        lib.addWidget(self.track_list)
        actions = QHBoxLayout()
        for label, callback in (("Новый плейлист", self.create_playlist), ("Сохранить плейлист", self.save_playlist), ("Открыть плейлист", self.open_playlist), ("Удалить из списка", self.remove_track)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        lib.addLayout(actions)
        self.tabs.addTab(library_page, "Медиатека")

        player_page = QWidget()
        p = QVBoxLayout(player_page)
        self.now_playing = QLabel("Ничего не воспроизводится")
        self.now_playing.setAlignment(Qt.AlignCenter)
        self.now_playing.setMinimumHeight(100)
        p.addWidget(self.now_playing)
        self.track_position = QSlider(Qt.Horizontal)
        self.track_position.sliderPressed.connect(lambda: setattr(self, "user_seeking", True))
        self.track_position.sliderReleased.connect(self.seek)
        p.addWidget(self.track_position)
        times = QHBoxLayout()
        self.elapsed = QLabel("00:00")
        self.duration = QLabel("00:00")
        times.addWidget(self.elapsed)
        times.addStretch()
        times.addWidget(self.duration)
        p.addLayout(times)
        controls = QHBoxLayout()
        for label, callback in (("⏮", self.previous_track), ("▶ / ⏸", self.toggle_play), ("⏭", self.next_track), ("Перемешать", self.toggle_shuffle), ("Повтор: выкл.", self.toggle_repeat)):
            b = QPushButton(label)
            b.clicked.connect(callback)
            controls.addWidget(b)
            if label.startswith("Повтор"):
                self.repeat_button = b
        p.addLayout(controls)
        volume_row = QHBoxLayout()
        volume_row.addWidget(QLabel("Громкость"))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(self.settings.get("volume", 70)))
        self.volume.valueChanged.connect(self.set_volume)
        volume_row.addWidget(self.volume)
        p.addLayout(volume_row)
        self.tabs.addTab(player_page, "Плеер")

        settings_page = QWidget()
        form = QFormLayout(settings_page)
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
        self.theme.addItems(["Spotify", "Яндекс Музыка", "SoundCloud", "Свой стиль"])
        self.theme.setCurrentText(self.settings.get("theme", "Spotify"))
        self.theme.currentTextChanged.connect(self.change_theme)
        form.addRow("Стиль", self.theme)
        self.accent = QLineEdit(self.settings.get("accent", "#1DB954"))
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
        preset_name = QLineEdit()
        preset_name.setPlaceholderText("Название UI-пресета")
        self.preset_name = preset_name
        save_preset = QPushButton("Сохранить UI-пресет")
        save_preset.clicked.connect(self.save_ui_preset)
        form.addRow(preset_name, save_preset)
        self.preset_selector = QComboBox()
        self.preset_selector.addItems(sorted(self.ui_config.get("presets", {}).keys()))
        load_preset = QPushButton("Применить UI-пресет")
        load_preset.clicked.connect(self.load_ui_preset)
        form.addRow(self.preset_selector, load_preset)
        self.tabs.addTab(settings_page, "Настройки")

        eq_page = QWidget()
        eq = QVBoxLayout(eq_page)
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
        for name, vals in (("Речь", [-4,-3,-2,2,4,5,3,1,0,0]), ("Бас", [8,7,5,2,0,-2,-3,-3,-2,-2]), ("Спокойный", [2,1,0,1,2,1,0,-1,-2,-2]), ("Сброс", [0]*10)):
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked=False, v=vals: self.set_eq_values(v))
            presets.addWidget(btn)
        eq.addLayout(presets)
        save_eq = QPushButton("Сохранить эквалайзер")
        save_eq.clicked.connect(self.save_settings)
        eq.addWidget(save_eq)
        self.tabs.addTab(eq_page, "Эквалайзер")

        tags_page = QWidget()
        tag_form = QFormLayout(tags_page)
        self.tag_title = QLineEdit()
        self.tag_artist = QLineEdit()
        self.tag_genre = QLineEdit()
        self.tag_date = QLineEdit()
        self.cover_path = QLineEdit()
        cover_btn = QPushButton("Выбрать обложку")
        cover_btn.clicked.connect(self.choose_cover)
        self.tag_file = QLabel("Выберите трек в медиатеке")
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
        self.tabs.addTab(tags_page, "Теги")

        menu = self.menuBar().addMenu("Файл")
        open_action = QAction("Открыть файлы", self)
        open_action.triggered.connect(self.add_files)
        menu.addAction(open_action)
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.close)
        menu.addAction(exit_action)

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
        if self.current_index < 0:
            QMessageBox.warning(self, "Теги", "Сначала выберите и воспроизведите файл.")
            return
        path = self.library[self.current_index]
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
        self.apply_theme()

    def apply_theme(self):
        presets = {
            "Spotify": ("#121212", "#1DB954", "#FFFFFF"),
            "Яндекс Музыка": ("#171717", "#FFCC00", "#FFFFFF"),
            "SoundCloud": ("#171717", "#FF5500", "#FFFFFF"),
            "Свой стиль": ("#171717", self.accent.text() if hasattr(self, "accent") else "#7C5CFC", "#FFFFFF")
        }
        bg, accent, fg = presets.get(self.settings.get("theme", "Spotify"), presets["Spotify"])
        if hasattr(self, "accent") and self.settings.get("theme") == "Свой стиль":
            accent = self.accent.text() or accent
        font = self.font.text() if hasattr(self, "font") else self.settings.get("font", "Segoe UI")
        size = self.font_size.value() if hasattr(self, "font_size") else self.settings.get("font_size", 10)
        self.setFont(QFont(font, size))
        self.setStyleSheet(f"QMainWindow,QWidget{{background:{bg};color:{fg};}} QPushButton{{background:#292929;border:0;border-radius:8px;padding:9px 13px;}} QPushButton:hover{{background:{accent};color:#111;}} QLineEdit,QListWidget,QComboBox{{background:#242424;border:1px solid #383838;border-radius:6px;padding:7px;color:{fg};}} QSlider::groove:horizontal{{height:5px;background:#444;}} QSlider::handle:horizontal{{background:{accent};width:13px;margin:-5px 0;border-radius:6px;}} QTabBar::tab{{padding:10px 18px;background:#222;}} QTabBar::tab:selected{{background:{accent};color:#111;}}")

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
        preset = self.ui_config.get("presets", {}).get(self.preset_selector.currentText())
        if not preset:
            return
        self.theme.setCurrentText(preset.get("theme", "Свой стиль"))
        self.accent.setText(preset.get("accent", "#1DB954"))
        self.font.setText(preset.get("font", "Segoe UI"))
        self.font_size.setValue(int(preset.get("font_size", 10)))
        self.settings.update(preset)
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
