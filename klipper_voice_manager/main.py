import threading
import time
import signal
import sys
import os
import traceback

from config_manager import ConfigManager
from sound_manager import SoundManager
from print_status_notifier import PrintStatusNotifier
from progress_notifier import ProgressNotifier
from print_time_notifier import PrintTimeNotifier
from fan_notifier import FanNotifier
from temperatures_notifier import TemperaturesNotifier
from parking_notifier import ParkingNotifier
from bed_mesh_notifier import BedMeshNotifier
from shared_utils import enqueue_phrase
from ws_client import WSClient
from custom_notifier import CustomNotifier

# Глобальное состояние
status_lock = threading.Lock()
shared_status = {}
shutdownflag = threading.Event()

# Инициализация компонентов
config_manager = ConfigManager("config.yaml")
sound_manager = SoundManager(config_manager)
ws = WSClient(config_manager, status_lock, shared_status)

# Инициализация нотификаторов
print_status_notifier = PrintStatusNotifier(config_manager, sound_manager, ws)
progress_notifier = ProgressNotifier(config_manager, sound_manager, ws)
print_time_notifier = PrintTimeNotifier(config_manager, sound_manager, ws)
fan_notifier = FanNotifier(config_manager, sound_manager, ws)
temperatures_notifier = TemperaturesNotifier(config_manager, sound_manager, ws)
parking_notifier = ParkingNotifier(config_manager, sound_manager, ws)
bed_mesh_notifier = BedMeshNotifier(config_manager, sound_manager, ws)
custom_notifier = CustomNotifier(config_manager, sound_manager, ws)

# События для синхронизации потоков вместо polling
status_update_event = threading.Event()
klipper_status_event = threading.Event()


def signal_handler(signum, frame):
    """Обработчик сигналов завершения (SIGINT, SIGTERM)."""
    print(f"[ЗВУК] Получен сигнал {signum}. Завершение работы...")
    shutdownflag.set()
    # Пробуждаем потоки из ожидания
    status_update_event.set()
    klipper_status_event.set()


def cleanup():
    """Корректное завершение всех сервисов."""
    print("[ЗВУК] Остановка сервисов...")
    try:
        config_manager.stop_watching()
    except Exception as e:
        print(f"[ОШИБКА] ConfigManager cleanup: {e}")
    
    try:
        sound_manager.stop_all()
    except Exception as e:
        print(f"[ОШИБКА] SoundManager cleanup: {e}")
    
    try:
        ws.stop()
    except Exception as e:
        print(f"[ОШИБКА] WebSocket cleanup: {e}")
    
    print("[ЗВУК] Сервисы остановлены. Выход.")


def _setup_subscriptions():
    """Регистрирует обработчики изменений конфигурации."""
    sound_sections = ["sound_manager", "sounds", "sounds_dir"]
    for section in sound_sections:
        config_manager.subscribe_to_section(section, _on_sound_config_changed)

    ws_sections = ["websocket", "klipper"]
    for section in ws_sections:
        config_manager.subscribe_to_section(section, _on_ws_config_changed)


def _on_sound_config_changed(section_name, section_data, old_data=None):
    """Обработчик изменений конфигурации звуков."""
    print(f"[КОНФИГ] Раздел '{section_name}' изменён (ключи: {list(section_data.keys())})")

    # Игнорируем изменение только громкости
    if section_name == "sound_manager":
        changed_keys = set(section_data.keys())
        if changed_keys == {"volume"}:
            print("[КОНФИГ] Изменился только volume — игнорируем")
            return

        # Обновляем только часы уведомлений
        if changed_keys == {"notification_hours"}:
            print("[КОНФИГ] Обновляем notification_hours")
            try:
                sound_manager.reload_notification_settings()
            except Exception as e:
                print(f"[ЗВУК ОШИБКА] Ошибка при обновлении notification_hours: {e}")
            return

    # Паузируем воспроизведение перед перестройкой кеша
    try:
        sound_manager.pause()
        time.sleep(0.2)
    except Exception as e:
        print(f"[ЗВУК ОШИБКА] Ошибка при паузе: {e}")

    try:
        # Используем встроенный метод SoundManager для инициализации кеша
        sound_manager.initialize_cache()
        sound_manager.reload_notification_settings()
    except Exception as e:
        print(f"[ЗВУК ОШИБКА] Ошибка при обновлении кеша: {e}")
        traceback.print_exc()
    finally:
        # Возобновляем воспроизведение
        try:
            time.sleep(0.1)
            sound_manager.resume()
        except Exception as e:
            print(f"[ЗВУК ОШИБКА] Ошибка при возобновлении: {e}")


def _on_ws_config_changed(section_name, section_data, old_data=None):
    """Обработчик изменений WebSocket конфигурации."""
    print(f"[КОНФИГ] Раздел '{section_name}' изменён, переконфигурируем WebSocket...")
    if section_name in ["klipper", "websocket"]:
        time.sleep(0.1)
        try:
            ws.reconfigure()
        except Exception as e:
            print(f"[ВС ОШИБКА] Ошибка переконфигурирования: {e}")


def status_processor():
    """Обработчик статуса принтера - использует Event вместо polling."""
    while not shutdownflag.is_set():
        try:
            with status_lock:
                status = ws.get_state()

            if status.print_state == "—":
                # Вместо sleep используем Event с timeout
                status_update_event.wait(timeout=0.5)
                status_update_event.clear()
                continue

            # Проверяем все компоненты
            print_status_notifier.check(status)
            print_time_notifier.check(status)
            progress_notifier.check(status)
            fan_notifier.check(status)
            temperatures_notifier.check(status)
            parking_notifier.check()
            bed_mesh_notifier.check()
            custom_notifier.check()

            # Ждём siguiente обновление или сигнала завершения
            status_update_event.wait(timeout=0.1)
            status_update_event.clear()

        except Exception as e:
            print(f"[ОШИБКА ПРОЦЕССОРА] {e}")
            traceback.print_exc()
            time.sleep(0.5)


def klipper_monitor():
    """Монитор состояния Klipper - отслеживает дисконнект и ребут MCU."""
    disconnected_notified = False
    reboot_notified = False
    mcu_notified = False

    while not shutdownflag.is_set():
        try:
            with status_lock:
                klipper_disconnected = shared_status.get("klipper_disconnected", False)
                klipper_reboot = shared_status.get("klipper_reboot", False)
                mcu_disconnected = shared_status.get("mcu_disconnected", False)

            # Обрабатываем события только при переходе из False в True
            if klipper_disconnected and not disconnected_notified:
                print("[ЗВУК] Обнаружена потеря соединения с klipper")
                handle_klipper_event(["потеряна", "связь", "с", "klipper"])
                with status_lock:
                    shared_status["klipper_disconnected"] = False
                disconnected_notified = True

            if klipper_reboot and not reboot_notified:
                print("[ЗВУК] Обнаружен запуск принтера")
                handle_klipper_event(["принтер", "перезапущен"])
                with status_lock:
                    shared_status["klipper_reboot"] = False
                reboot_notified = True

            if mcu_disconnected and not mcu_notified:
                print("[ЗВУК] Обнаружено отключение MCU")
                handle_klipper_event(["MCU", "отключен"])
                with status_lock:
                    shared_status["mcu_disconnected"] = False
                mcu_notified = True

            # Сбрасываем флаги если события уходят
            if not klipper_disconnected:
                disconnected_notified = False
            if not klipper_reboot:
                reboot_notified = False
            if not mcu_disconnected:
                mcu_notified = False

            # Ждём событие с timeout вместо sleep
            klipper_status_event.wait(timeout=1.0)
            klipper_status_event.clear()

        except Exception as e:
            print(f"[ОШИБКА МОНИТОРА klipper] {e}")
            traceback.print_exc()
            time.sleep(1.0)


def handle_klipper_event(phrase_list):
    """Унифицированная обработка событий Klipper с таймаутом."""
    max_wait = 30  # секунд максимального ожидания
    timeout = threading.Event()

    def timeout_handler():
        """Отмена ожидания через таймаут."""
        time.sleep(max_wait)
        timeout.set()
        sound_manager.clear_queue()

    # Запускаем таймаут в отдельном потоке
    timeout_thread = threading.Thread(target=timeout_handler, daemon=True)
    timeout_thread.start()

    try:
        # Очищаем очередь
        try:
            sound_manager.clear_queue()
            print("[ЗВУК] Очередь очищена")
        except Exception as e:
            print(f"[ЗВУК ОШИБКА] Ошибка при очистке: {e}")
            return

        # Отправляем фразу на озвучку
        try:
            enqueue_phrase(phrase_list, sound_manager, config_manager)
            print(f"[ЗВУК] Отправлена фраза: {phrase_list}")
        except Exception as e:
            print(f"[ЗВУК ОШИБКА] Ошибка отправки: {e}")
            return

        # Ждём завершения с таймаутом
        start_time = time.time()
        while sound_manager._playback_active and not timeout.is_set():
            time.sleep(0.05)

        if timeout.is_set():
            print("[ЗВУК] Превышено время ожидания (30 сек), продолжаем...")

    finally:
        timeout.set()  # Гарантируем завершение таймаут потока


def main():
    """Главная функция."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("[ЗВУК] Инициализация...")
    
    _setup_subscriptions()
    config_manager.start_watching()

    # Инициализируем кеш (используем встроенный метод SoundManager)
    try:
        sound_manager.initialize_cache()
    except Exception as e:
        print(f"[ЗВУК ОШИБКА] Ошибка инициализации кеша: {e}")
        traceback.print_exc()

    # Запускаем приветствие
    enqueue_phrase(["система", "запущена"], sound_manager, config_manager)

    # Запускаем WebSocket
    try:
        ws.start()
    except Exception as e:
        print(f"[ЗВУК ОШИБКА] Ошибка запуска WebSocket: {e}")
        cleanup()
        sys.exit(1)

    # Запускаем рабочие потоки
    processor_thread = threading.Thread(
        target=status_processor,
        daemon=True,
        name="StatusProcessor"
    )
    processor_thread.start()

    monitor_thread = threading.Thread(
        target=klipper_monitor,
        daemon=True,
        name="KlipperMonitor"
    )
    monitor_thread.start()

    print("[ЗВУК] Система готова. Ожидание команд...")

    try:
        while not shutdownflag.is_set():
            # Основной поток обрабатывает события звуков
            sound_manager.process_events()
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("[ЗВУК] Программа завершена пользователем (Ctrl+C)")
    finally:
        cleanup()
        sys.exit(0)


if __name__ == "__main__":
    main()
