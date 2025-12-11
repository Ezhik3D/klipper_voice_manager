import json
import os
import threading
import yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class ConfigReloadHandler(FileSystemEventHandler):
    """Обработчик событий изменения config.yaml с дебаунсингом."""
    
    def __init__(self, reload_callback):
        super().__init__()
        self.reload_callback = reload_callback
        self.timer = None
        self.lock = threading.Lock()

    def on_modified(self, event):
        """Обработчик события модификации файла."""
        if event.src_path.endswith("config.yaml"):
            with self.lock:
                if self.timer:
                    self.timer.cancel()
                # Дебаунсируем с задержкой 0.5 сек для пакета изменений
                self.timer = threading.Timer(0.5, self._trigger_reload)
                self.timer.start()

    def _trigger_reload(self):
        """Вызывает обновление конфигурации."""
        try:
            self.reload_callback()
        except Exception as e:
            print(f"[CONFIG ОШИБКА] Ошибка при перезагрузке: {e}")
        finally:
            with self.lock:
                self.timer = None


class ConfigManager:
    """
    Менеджер конфигурации с поддержкой подписок на изменения секций.
    """
    
    def __init__(self, config_path="config.yaml"):
        self.config_path = config_path
        self.lock = threading.RLock()
        self.priority_lock = threading.Lock()
        self.is_priority_mode = False
        
        # Белый список секций для WSClient (доступны даже в приоритетном режиме)
        self.ws_allowed_sections = {"klipper", "websocket", "response"}
        
        self.config = {}
        self._previous_config = {}
        self.section_callbacks = {}
        self.reload_callback = None
        self.updated_event = threading.Event()
        self.observer = None
        
        # Кеш для find_sound_file() - {alias: filepath}
        self._sound_file_cache = {}
        self._cache_lock = threading.Lock()
        
        self.load_config()

    def load_config(self):
        """Загружает конфигурацию из YAML файла."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                new_config = yaml.safe_load(f) or {}
            with self.lock:
                self.config = new_config
                changed_sections = self._get_changed_sections()
                self._notify_callbacks(changed_sections)
                self._previous_config = json.loads(json.dumps(self.config))
                # Инвалидируем кеш файлов при изменении конфигурации
                with self._cache_lock:
                    self._sound_file_cache.clear()
                self.updated_event.set()
        except Exception as e:
            print(f"[CONFIG ОШИБКА] Ошибка загрузки конфига: {e}")

    def _get_changed_sections(self):
        """Определяет, какие секции изменились."""
        changed = set()
        for section in self.config:
            if (section not in self._previous_config or
                self.config[section] != self._previous_config.get(section)):
                changed.add(section)
        for section in self._previous_config:
            if section not in self.config:
                changed.add(section)
        return changed

    def _notify_callbacks(self, changed_sections):
        """Уведомляет подписчиков об изменении секций."""
        for section in changed_sections:
            if section in self.section_callbacks:
                old_section = self._previous_config.get(section, {})
                new_section = self.config.get(section, {})

                # Определяем реально изменённые ключи
                changed_data = {}
                for key in new_section:
                    if key not in old_section or old_section[key] != new_section[key]:
                        changed_data[key] = new_section[key]
                
                for key in old_section:
                    if key not in new_section:
                        changed_data[key] = None

                # Вызываем все подписанные callback'и
                for callback in self.section_callbacks[section]:
                    try:
                        callback(section, changed_data, old_section)
                    except Exception as e:
                        print(f"[CONFIG ОШИБКА] Ошибка в callback для {section}: {e}")

    def get_config_section(self, section_name, timeout=5.0, is_priority=False):
        """
        Получает секцию конфигурации с учётом приоритетного режима.
        """
        # Белый список секций - всегда доступны
        if section_name in self.ws_allowed_sections:
            acquired = self.lock.acquire(timeout=timeout)
            if not acquired:
                print(f"[CONFIG ОШИБКА] Timeout при получении {section_name}")
                return {}
            try:
                return self.config.get(section_name, {})
            finally:
                self.lock.release()

        # Проверяем приоритетный режим для остальных секций
        if not is_priority and self.is_priority_mode:
            print(f"[CONFIG ОШИБКА] Доступ к '{section_name}' заблокирован (приоритетный режим)")
            return {}

        acquired = self.lock.acquire(timeout=timeout)
        if not acquired:
            print(f"[CONFIG ОШИБКА] Timeout при получении {section_name}")
            return {}
        try:
            return self.config.get(section_name, {})
        finally:
            self.lock.release()

    def subscribe_to_section(self, section_name, callback):
        """Подписывает callback на изменения секции."""
        if section_name not in self.section_callbacks:
            self.section_callbacks[section_name] = set()  # Используем set вместо list
        
        if callback not in self.section_callbacks[section_name]:
            self.section_callbacks[section_name].add(callback)
            print(f"[CONFIG] Подписка на '{section_name}' добавлена")
        else:
            print(f"[CONFIG] Подписка на '{section_name}' уже существует")

    def find_sound_file(self, alias: str) -> str:
        """
        Находит файл звука по алиасу с явным указанием расширения.
        Проверяет поддерживаемые форматы и кеширует результат.
        """
        SUPPORTED_EXTENSIONS = {'.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac'}
        
        # Проверка кеша (быстрый выход)
        with self._cache_lock:
            if alias in self._sound_file_cache:
                return self._sound_file_cache[alias]

        # Получаем конфигурацию звуков
        sounds = self.get_config_section("sounds")
        if alias not in sounds:
            print(f"[CONFIG ОШИБКА] Алиас '{alias}' не найден в секции 'sounds'")
            return None

        # Получаем базовый путь из конфигурации
        sm_config = self.get_config_section("sound_manager")
        base_path = sm_config.get("sounds_dir", "sounds/")

        # Формируем полный путь
        filename = sounds[alias]
        filepath = os.path.join(base_path, filename)
        abs_path = os.path.abspath(filepath)

        # Проверяем расширение файла
        file_ext = os.path.splitext(filename)[1].lower()
        if not file_ext:
            print(f"[CONFIG ОШИБКА] У файла '{filename}' отсутствует расширение")
            return None
        
        if file_ext not in SUPPORTED_EXTENSIONS:
            print(f"[CONFIG ОШИБКА] Неподдерживаемый формат файла: '{filename}' "
                  f"(поддерживаются: {', '.join(sorted(SUPPORTED_EXTENSIONS))})")
            return None

        # Проверяем существование файла
        if os.path.isfile(abs_path):
            with self._cache_lock:
                self._sound_file_cache[alias] = abs_path
            return abs_path
        else:
            print(f"[CONFIG ПРЕДУПР] Файл не найден: {abs_path}")
            return None

    def start_watching(self):
        """Запускает отслеживание изменений config.yaml."""
        event_handler = ConfigReloadHandler(self.reload_config)
        self.observer = Observer()
        config_dir = os.path.dirname(os.path.abspath(self.config_path)) or "."
        self.observer.schedule(event_handler, config_dir, recursive=False)
        self.observer.start()
        print("[CONFIG] Слежение за config.yaml запущено")

    def stop_watching(self):
        """Останавливает отслеживание конфигурации."""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            print("[CONFIG] Слежение за config.yaml остановлено")

    def reload_config(self):
        """Перезагружает конфигурацию."""
        print("[CONFIG] Перезагрузка конфигурации...")
        self.load_config()
        if self.reload_callback:
            try:
                self.reload_callback()
            except Exception as e:
                print(f"[CONFIG ОШИБКА] Ошибка в reload_callback: {e}")
