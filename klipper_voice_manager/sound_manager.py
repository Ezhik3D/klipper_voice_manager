import os
import platform
import traceback
import pygame
import threading
import time
import hashlib
import pickle
from collections import deque
from datetime import datetime
from pydub import AudioSegment
from system_profiler import SystemProfiler


class SoundManager:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        sm_cfg = self.config_manager.get_config_section("sound_manager")

        self.sounds_dir = sm_cfg.get("sounds_dir", "./sounds")
        self.container_path = os.path.join(os.getcwd(), "audio_cache_v1.bin")

        # Кеш для быстрой проверки изменений файлов (mtime + size)
        self._file_metadata_cache = {}

        # Часы уведомлений
        notification_hours = sm_cfg.get("notification_hours", {})
        try:
            self.notification_start = datetime.strptime(
                notification_hours.get("start", "00:00"), "%H:%M"
            ).time()
            self.notification_end = datetime.strptime(
                notification_hours.get("end", "23:59"), "%H:%M"
            ).time()
            print(f"[АУДИО] Часы уведомлений: {self.notification_start.strftime('%H:%M')} - "
                  f"{self.notification_end.strftime('%H:%M')}")
        except Exception as e:
            print(f"[АУДИО ОШИБКА] Неверный формат notification_hours: {e}")
            self.notification_start = datetime.strptime("00:00", "%H:%M").time()
            self.notification_end = datetime.strptime("23:59", "%H:%M").time()

        self.queue = deque()
        self._lock = threading.Lock()
        self._playback_condition = threading.Condition(self._lock)
        self._paused = False
        self._playback_active = False
        self._shutdown = False

        # Кеш звуков в памяти
        self._sound_cache = {}

        # Инициализация профилировщика
        self.profiler = SystemProfiler()
        ap = self.profiler.audio_params

        try:
            pygame.mixer.pre_init(ap['frequency'], -16, ap['channels'], 1024)
            pygame.init()
            print(f"[АУДИО] pygame mixer: {ap['frequency']}Гц, {ap['channels']} каналов, "
                  f"профиль={self.profiler.profile_name}")
        except Exception as e:
            print(f"[АУДИО ОШИБКА] Ошибка инициализации pygame: {e}")
            raise

        # Запускаем поток воспроизведения
        self._playback_thread = threading.Thread(
            target=self._playback_worker, 
            daemon=True, 
            name="AudioPlaybackWorker"
        )
        self._playback_thread.start()

    def initialize_cache(self):
        all_audio_paths = []
        sounds_cfg = self.config_manager.get_config_section("sounds")
        
        if not sounds_cfg:
            print("[АУДИО] Секция 'sounds' не найдена в конфигурации")
            return

        for alias in sounds_cfg.keys():
            filepath = self.config_manager.find_sound_file(alias)
            if filepath:
                all_audio_paths.append(filepath)
            else:
                print(f"[АУДИО ПРЕДУПР] Алиас '{alias}' ссылается на отсутствующий файл")

        self.update_cache(all_audio_paths)
        self.report_extra_files()

    def _get_file_metadata(self, filepath):
        """
        Получает метаданные файла (mtime, size) для быстрой проверки изменений.
        """
        try:
            stat = os.stat(filepath)
            return (stat.st_mtime, stat.st_size)
        except (OSError, IOError):
            return None

    def _compute_file_hash(self, filepath):
        """
        Вычисляет SHA-256 хеш только если файл не в кеше или изменился.
        """
        metadata = self._get_file_metadata(filepath)
        if metadata is None:
            return None

        # Если метаданные совпадают с кешированными, пропускаем хеширование
        if filepath in self._file_metadata_cache:
            if self._file_metadata_cache[filepath]['metadata'] == metadata:
                return self._file_metadata_cache[filepath]['hash']

        # Вычисляем хеш для файла
        try:
            with open(filepath, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            
            # Кешируем результат
            self._file_metadata_cache[filepath] = {
                'metadata': metadata,
                'hash': file_hash
            }
            return file_hash
        except Exception as e:
            print(f"[АУДИО ОШИБКА] Не удалось вычислить хеш {filepath}: {e}")
            return None

    def _load_container(self):
        """
        Загружает контейнер с диска (кеш аудиофайлов).
        """
        if not os.path.exists(self.container_path):
            return None

        try:
            print(f"[АУДИО] Загрузка контейнера из {self.container_path}...")
            start_t = time.time()
            with open(self.container_path, 'rb') as f:
                data = pickle.load(f)

            # Проверяем совместимость профиля и параметров
            if data.get('profile_name') != self.profiler.profile_name:
                print("[АУДИО] Профиль системы изменился, контейнер пересоздастся")
                return None

            if data.get('audio_params') != self.profiler.audio_params:
                print("[АУДИО] Параметры аудио изменились, контейнер пересоздастся")
                return None

            elapsed = time.time() - start_t
            print(f"[АУДИО] Контейнер загружен за {elapsed:.3f}с ({len(data.get('files', {}))} файлов)")
            return data
        except Exception as e:
            print(f"[АУДИО ОШИБКА] Ошибка загрузки контейнера: {e}")
            return None

    def _save_container(self, files_map):
        """
        Сохраняет контейнер с аудиоданными на диск.
        """
        data = {
            'profile_name': self.profiler.profile_name,
            'audio_params': self.profiler.audio_params,
            'files': files_map
        }
        try:
            start_t = time.time()
            with open(self.container_path, 'wb') as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
            elapsed = time.time() - start_t
            print(f"[АУДИО] Контейнер сохранён за {elapsed:.3f}с")
        except Exception as e:
            print(f"[АУДИО ОШИБКА] Не удалось сохранить контейнер: {e}")

    def _normalize_audio(self, filepath):
        """
        Нормализует аудиофайл к целевому формату.
        """
        ap = self.profiler.audio_params
        target_freq = ap['frequency']
        target_ch = ap['channels']
        silence_ms = ap['silence_ms']

        try:
            audio = AudioSegment.from_file(filepath)
            audio = audio.set_frame_rate(target_freq).set_channels(target_ch).normalize()
            silence = AudioSegment.silent(duration=silence_ms, frame_rate=target_freq)
            return silence + audio + silence
        except Exception as e:
            print(f"[АУДИО ОШИБКА] Ошибка нормализации {filepath}: {e}")
            return None

    def update_cache(self, filepaths):
        """
        Обновляет кеш звуков: загружает из контейнера или пересоздаёт.
        Оптимизирована работа с метаданными файлов для быстрой проверки изменений.
        """
        with self._lock:
            # Загружаем существующий контейнер
            container_data = self._load_container()
            disk_files_map = container_data.get('files', {}) if container_data else {}

            new_memory_cache = {}
            new_disk_files_map = {}
            
            files_loaded = 0
            files_rebuilt = 0

            # Нормализуем пути и собираем валидные файлы
            valid_paths = set()
            for filepath in filepaths:
                abs_path = os.path.abspath(filepath)
                norm_path = os.path.normpath(abs_path)
                if platform.system() in ['Windows', 'Darwin']:
                    norm_path = norm_path.lower()
                
                if os.path.isfile(norm_path):
                    valid_paths.add(norm_path)

            # Обрабатываем каждый файл
            for abs_path in valid_paths:
                current_hash = self._compute_file_hash(abs_path)
                if current_hash is None:
                    continue

                sound_obj = None
                raw_data = None
                duration = 0.0

                # Проверяем наличие в контейнере
                cached_entry = disk_files_map.get(abs_path)
                if cached_entry and cached_entry['hash'] == current_hash:
                    # Файл не изменился, восстанавливаем из контейнера
                    try:
                        raw_data = cached_entry['raw_data']
                        duration = cached_entry.get('duration', 0)
                        sound_obj = pygame.mixer.Sound(buffer=raw_data)
                        files_loaded += 1
                    except Exception as e:
                        print(f"[АУДИО ОШИБКА] Ошибка восстановления из контейнера: {e}")

                # Если файл изменился или его нет в контейнере
                if sound_obj is None:
                    print(f"[АУДИО] Обработка: {os.path.basename(abs_path)}")
                    norm_audio = self._normalize_audio(abs_path)
                    if norm_audio:
                        raw_data = norm_audio.raw_data
                        duration = norm_audio.duration_seconds
                        try:
                            sound_obj = pygame.mixer.Sound(buffer=raw_data)
                            files_rebuilt += 1
                        except Exception as e:
                            print(f"[АУДИО ОШИБКА] Ошибка создания Sound: {e}")

                # Сохраняем успешно загруженный звук
                if sound_obj and raw_data:
                    new_disk_files_map[abs_path] = {
                        'hash': current_hash,
                        'raw_data': raw_data,
                        'duration': duration
                    }
                    new_memory_cache[abs_path] = {
                        'sound': sound_obj,
                        'hash': current_hash
                    }

            # Обновляем рабочий кеш
            self._sound_cache = new_memory_cache

            # Определяем, нужно ли сохранять контейнер
            need_save = (
                len(disk_files_map) != len(new_disk_files_map) or
                any(new_disk_files_map.get(p, {}).get('hash') != disk_files_map.get(p, {}).get('hash')
                    for p in new_disk_files_map.keys()) or
                not container_data  # Контейнер впервые создаётся
            )

            if need_save:
                print(f"[АУДИО] Сохраняем контейнер ({files_rebuilt} пересоздано)")
                self._save_container(new_disk_files_map)

        print(f"[АУДИО] Кеш готов: {len(self._sound_cache)} файлов "
              f"(загружено: {files_loaded}, пересоздано: {files_rebuilt})")

    def _is_notification_time(self):
        """Проверяет, находимся ли мы в часах уведомлений."""
        current_time = datetime.now().time()
        start = self.notification_start
        end = self.notification_end
        
        if start <= end:
            return start <= current_time <= end
        else:
            return current_time >= start or current_time <= end

    def enqueue_sentence(self, filepaths):
        """Добавляет фразу в очередь воспроизведения."""
        with self._playback_condition:
            self.queue.extend(filepaths)
            self._playback_condition.notify()

    def pause(self):
        """Приостанавливает воспроизведение."""
        with self._lock:
            self._paused = True
            pygame.mixer.pause()
            print("[АУДИО] Воспроизведение приостановлено")

    def resume(self):
        """Возобновляет воспроизведение."""
        with self._lock:
            self._paused = False
            pygame.mixer.unpause()
            print("[АУДИО] Воспроизведение возобновлено")

    def stop_all(self):
        """Полностью останавливает воспроизведение."""
        with self._playback_condition:
            self._shutdown = True
            pygame.mixer.stop()
            self.queue.clear()
            self._playback_active = False
            self._playback_condition.notify_all()
        print("[АУДИО] Воспроизведение остановлено")

    def clear_queue(self):
        """Очищает очередь (текущий звук продолжает играть)."""
        with self._lock:
            self.queue.clear()
            print("[АУДИО] Очередь очищена")

    def _get_current_volume(self):
        """Получает текущий уровень громкости из конфигурации."""
        sm_cfg = self.config_manager.get_config_section("sound_manager")
        return sm_cfg.get("volume", 1.0)

    def _playback_worker(self):
        """
        Основной поток воспроизведения с улучшенной обработкой ошибок.
        Использует Condition для эффективной синхронизации вместо polling.
        """
        while not self._shutdown:
            try:
                with self._playback_condition:
                    # Ждём появления элемента в очереди
                    while not self.queue and not self._shutdown:
                        self._playback_condition.wait(timeout=1.0)

                    if self._shutdown or not self.queue:
                        continue

                    filepath = self.queue.popleft()
                    self._playback_active = True

                # Проверяем время уведомлений
                if not self._is_notification_time():
                    print(f"[АУДИО] Вне часов уведомлений: {os.path.basename(filepath)}")
                    with self._lock:
                        self._playback_active = False
                    continue

                # Получаем звук из кеша
                abs_path = os.path.abspath(filepath)
                sound_entry = None
                with self._lock:
                    sound_entry = self._sound_cache.get(abs_path)

                if sound_entry is None:
                    print(f"[АУДИО ОШИБКА] Файл не в кеше: {os.path.basename(filepath)}")
                    with self._lock:
                        self._playback_active = False
                    continue

                # Воспроизводим звук
                try:
                    sound = sound_entry['sound']
                    current_volume = self._get_current_volume()
                    sound.set_volume(max(0.0, min(1.0, current_volume)))
                    sound.play()

                    # Ждём окончания воспроизведения
                    while pygame.mixer.get_busy() and not self._paused and not self._shutdown:
                        time.sleep(0.01)

                    # Ждём если пауза активна
                    while self._paused and not self._shutdown:
                        time.sleep(0.05)

                except Exception as e:
                    print(f"[АУДИО ОШИБКА] Ошибка воспроизведения: {e}")
                    traceback.print_exc()

                finally:
                    with self._lock:
                        self._playback_active = False

            except Exception as e:
                print(f"[АУДИО ОШИБКА] Неожиданная ошибка в потоке воспроизведения: {e}")
                traceback.print_exc()
                time.sleep(0.5)

    def process_events(self):
        """Метод для совместимости с основной программой."""
        pass

    def get_cached_sound(self, filepath):
        """Получает звук из кеша."""
        abs_path = os.path.abspath(filepath)
        with self._lock:
            entry = self._sound_cache.get(abs_path)
            return entry['sound'] if entry else None

    def reload_notification_settings(self):
        """Перезагружает настройки часов уведомлений."""
        sm_cfg = self.config_manager.get_config_section("sound_manager")
        notification_hours = sm_cfg.get("notification_hours", {})
        try:
            self.notification_start = datetime.strptime(
                notification_hours.get("start", "00:00"), "%H:%M"
            ).time()
            self.notification_end = datetime.strptime(
                notification_hours.get("end", "23:59"), "%H:%M"
            ).time()
            print(f"[АУДИО] Часы уведомлений обновлены: "
                  f"{self.notification_start.strftime('%H:%M')} - "
                  f"{self.notification_end.strftime('%H:%M')}")
        except Exception as e:
            print(f"[АУДИО ОШИБКА] Ошибка обновления notification_hours: {e}")
            
    def report_extra_files(self):
        """
        Выводит список файлов в sounds_dir, которые не указаны в конфигурации (лишние).
        """
        sm_cfg = self.config_manager.get_config_section("sound_manager")
        sounds_dir = sm_cfg.get("sounds_dir", "./sounds")

        if not os.path.exists(sounds_dir):
            print(f"[АУДИО] Папка звуков не найдена: {sounds_dir}")
            return

        # Получаем все файлы из конфигурации (через алиасы)
        config_sounds = self.config_manager.get_config_section("sounds")
        if not config_sounds:
            print("[АУДИО] Секция 'sounds' не найдена в конфигурации")
            return

        # Собираем полные пути к файлам из конфигурации
        used_files = set()
        for alias, filename in config_sounds.items():
            filepath = self.config_manager.find_sound_file(alias)
            if filepath:
                used_files.add(os.path.basename(filepath))

        # Если ни один файл не найден — предупреждаем
        if not used_files:
            print("[АУДИО] Ни один файл из конфигурации не найден в папке")
            return

        # Собираем все файлы в sounds_dir с поддерживаемыми расширениями
        SUPPORTED_EXTENSIONS = {'.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac'}
        all_files_in_dir = set()

        for entry in os.listdir(sounds_dir):
            full_path = os.path.join(sounds_dir, entry)
            if os.path.isfile(full_path):
                ext = os.path.splitext(entry)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    all_files_in_dir.add(entry)


        # Находим лишние файлы (есть в папке, но не указаны в конфиге)
        extra_files = all_files_in_dir - used_files


        # Выводим результат
        if extra_files:
            print(f"[АУДИО] Найден(о) {len(extra_files)} лишний(их) файл(ов) в папке '{sounds_dir}':")
            for fname in sorted(extra_files):
                print(f'  - {fname}')
        else:
            print(f"[АУДИО] В папке '{sounds_dir}' нет лишних звуковых файлов (все используются).")

