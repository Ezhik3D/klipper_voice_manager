import threading
import json
import time
import websocket
import socket
import struct
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock

class PrintState(Enum):
    STANDBY = "standby"
    PRINTING = "printing"
    PAUSED = "paused"
    COMPLETE = "complete"
    ERROR = "error"
    UNKNOWN = "—"

class CompletionState(Enum):
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    PENDING = "—"

UNKNOWN_STR = "—"

@dataclass
class PrinterStatus:
    print_state: str = UNKNOWN_STR
    completion_state: str = UNKNOWN_STR
    progress_percent: int = 0
    elapsed_time: float = 0.0
    remaining_time: float = 0.0
    filament_used: float = 0.0
    filename: Optional[str] = None

    bed_temp: float = 0.0
    bed_target: float = 0.0
    ext_temp: float = 0.0
    ext_target: float = 0.0

    fan_percent: float = 0.0

    gcode_response: Optional[str] = None

    _last_progress: int = field(default=-1, init=False)
    _cached_remaining: Optional[float] = field(default=None, init=False)

class WSClient:
    QUERY_OBJECTS = {
        "print_stats": [
            "state",
            "filename",
            "progress",
            "print_duration",
            "filament_used",
        ],
        "display_status": ["progress"],
        "heater_bed": ["temperature", "target"],
        "extruder": ["temperature", "target"],
        "fan": ["speed"],
    }

    ID_SUBSCRIBE = 1
    ID_QUERY = 2

    def __init__(self, config_manager, status_lock, shared_status):
        self.uri = None
        self.config_manager = config_manager
        self.status_lock = status_lock
        self.shared_status = shared_status

        self._load_connection_params()
        self._load_ws_config()

        self._thread: Optional[threading.Thread] = None
        self._ws: Optional[websocket.WebSocketApp] = None
        self._stop_event = threading.Event()


        self._connected = False
        self._subscribed = False
        self.print_started = False
        self.manual_reset_active = False


        self.status = PrinterStatus()
        self.last_raw_status = {}


        self._status_changed = True
        self._reconfig_lock = threading.Lock()


        self.status.completion_state = CompletionState.PENDING.value
        
        # НОВОЕ: Флаг для управления озвучиванием расчётного времени
        self._print_time_announced = False
        self._print_time_announced_lock = threading.Lock()


        self.response_queue = []
        self.queue_lock = threading.Lock()
        self.print_status_notifier = None
        self._restart_in_progress = False
        self._is_restarting = False
        self._reconfig_lock = Lock()  # Новый мьютекс для защиты
        self._is_reconfiguring = False  # Флаг состояния



    def _load_connection_params(self):
        try:
            klipper_config = self.config_manager.get_config_section("klipper")
            if not klipper_config:
                raise ValueError("Секция 'klipper' не найдена в конфиге")
            if "host" not in klipper_config or not klipper_config["host"]:
                raise ValueError("Параметр 'host' отсутствует или пуст в секции 'klipper'")


            new_ip = klipper_config["host"]
            new_port = klipper_config.get("port", 7125)
            new_path = klipper_config.get("websocket_path", "/websocket")
            new_uri = f"ws://{new_ip}:{new_port}{new_path}"

            if new_uri != self.uri:
                self.ip = new_ip
                self.port = new_port
                self.path = new_path
                self.uri = new_uri
                print(f"[WSClient] URI сформирован: {self.uri}")
        except Exception as e:
            print(f"[WSClient] Ошибка загрузки параметров подключения: {e}")
            if not hasattr(self, 'uri') or not self.uri:
                self.uri = "ws://localhost:7125/websocket"


    def _load_ws_config(self):
        ws_config = self.config_manager.get_config_section("websocket")
        self.WS_SETTINGS = {
            "ping_interval": ws_config.get("ping_interval", 30),
            "ping_timeout": ws_config.get("ping_timeout", 10),
            "send_timeout": ws_config.get("send_timeout", 5),
        }
        self.RECONNECT_DELAY = ws_config.get("reconnect_delay", 2)
        self.THREAD_JOIN_TIMEOUT = ws_config.get("thread_join_timeout", 3)

    def _get_nested_value(self, data: Dict, *keys, default=None) -> Any:
        result = data
        for key in keys:
            if isinstance(result, dict):
                result = result.get(key)
            else:
                return default
        return result if result is not None else default


    def set_print_time_announced(self, value: bool):
        with self._print_time_announced_lock:
            self._print_time_announced = value


    def is_print_time_announced(self) -> bool:
        with self._print_time_announced_lock:
            return self._print_time_announced


    def _update_state_machine(self, new_state: Optional[str]):
        if new_state is None:
            return
        with self.status_lock:
            old_state = self.status.print_state
            self.status.print_state = new_state

            if new_state == PrintState.PRINTING.value:
                if old_state != PrintState.PAUSED.value:
                    self.set_print_time_announced(False)
                self.print_started = True
                self.manual_reset_active = False
                if self.status.completion_state != CompletionState.PENDING.value:
                    self.status.completion_state = CompletionState.PENDING.value
            elif new_state == PrintState.COMPLETE.value:
                self.set_print_time_announced(False)
                if self.status.completion_state not in (
                    CompletionState.COMPLETE.value,
                    CompletionState.CANCELLED.value,
                ):
                    self.print_started = False
                    self.status.completion_state = CompletionState.COMPLETE.value
            elif new_state == PrintState.STANDBY.value:
                self.set_print_time_announced(False)
                if self.print_started:
                    self.print_started = False
                    self.status.completion_state = CompletionState.CANCELLED.value

    def _calculate_remaining_time(self, progress_percent: int, elapsed_time: float) -> float:
        if (progress_percent == self.status._last_progress
                and self.status._cached_remaining is not None):
            return self.status._cached_remaining
        self.status._last_progress = progress_percent
        if progress_percent > 0 and elapsed_time > 0:
            try:
                total_time = elapsed_time / (progress_percent / 100.0)
                remaining = max(0.0, total_time - elapsed_time)
                self.status._cached_remaining = remaining
                return remaining
            except (ZeroDivisionError, TypeError):
                self.status._cached_remaining = 0.0
                return 0.0
        self.status._cached_remaining = 0.0
        return 0.0

    def _update_status_field(self, field_name: str, new_value: Any) -> bool:
        with self.status_lock:
            old_value = getattr(self.status, field_name)
            if new_value is None:
                return False
            if old_value != new_value:
                setattr(self.status, field_name, new_value)
                return True
        return False

    def _extract_status_from_message(self, status_data: Dict) -> bool:
        changed = False

        new_state = self._get_nested_value(status_data, "print_stats", "state")
        if new_state is not None and new_state != self.status.print_state:
            self._update_state_machine(new_state)
            changed = True

        progress = self._get_nested_value(status_data, "print_stats", "progress")
        if progress is None:
            progress = self._get_nested_value(status_data, "display_status", "progress")

        if progress is not None:
            new_percent = int(progress * 100)
            changed |= self._update_status_field("progress_percent", new_percent)

        elapsed = self._get_nested_value(status_data, "print_stats", "print_duration")
        changed |= self._update_status_field("elapsed_time", elapsed)

        if changed or self.status.progress_percent != self.status._last_progress:
            new_remaining = self._calculate_remaining_time(
                self.status.progress_percent, self.status.elapsed_time
            )
            if new_remaining != self.status.remaining_time:
                self.status.remaining_time = new_remaining

        changed |= self._update_status_field(
            "filament_used",
            self._get_nested_value(status_data, "print_stats", "filament_used"),
        )
        changed |= self._update_status_field(
            "filename", self._get_nested_value(status_data, "print_stats", "filename")
        )
        changed |= self._update_status_field(
            "bed_temp", self._get_nested_value(status_data, "heater_bed", "temperature")
        )
        changed |= self._update_status_field(
            "bed_target", self._get_nested_value(status_data, "heater_bed", "target")
        )
        changed |= self._update_status_field(
            "ext_temp", self._get_nested_value(status_data, "extruder", "temperature")
        )
        changed |= self._update_status_field(
            "ext_target", self._get_nested_value(status_data, "extruder", "target")
        )

        fan_speed = self._get_nested_value(status_data, "fan", "speed")
        if fan_speed is not None:
            new_fan_percent = round(fan_speed * 100, 1)
            changed |= self._update_status_field("fan_percent", new_fan_percent)

        return changed

    def _on_open(self, ws):
        print(f"[WSClient] Подключение установлено к {self.uri}")
        self._connected = True
        self._subscribed = False

        try:
            ws.send(json.dumps({
                "jsonrpc": "2.0",
                "id": self.ID_QUERY,
                "method": "printer.objects.query",
                "params": {"objects": self.QUERY_OBJECTS}
            }))
        except Exception as e:
            print(f"[WSClient] Ошибка при запросе статуса: {e}")


        # Запускаем подписку только если не в процессе перезапуска
        if not self._restart_in_progress:
            self._resubscribe()

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            method = data.get("method")

            if ws is None or not hasattr(ws, 'sock'):
                return

            if method == "notify_klippy_shutdown":
                with self.status_lock:
                    self.shared_status["mcu_disconnected"] = True
                return

            if method == "notify_klippy_ready":
                print("[WSClient] Получено notify_klippy_ready — перезапускаем подписку")
                with self.status_lock:
                    self.shared_status["klipper_reboot"] = True
                time.sleep(1)
                self.full_restart()
                return

            if method == "notify_klippy_disconnected":
                print("[WSClient] Получено notify_klippy_disconnected")
                with self.status_lock:
                    self.shared_status["klipper_disconnected"] = True
                return

            if data.get("id") == self.ID_SUBSCRIBE and "result" in data:
                self._subscribed = True
                print("[WSClient] Подписка подтверждена")
                return

            status = None
            if data.get("id") == self.ID_QUERY and "result" in data:
                status = data["result"].get("status", {})
            elif method == "notify_status_update":
                params = data.get("params", [])
                if params and isinstance(params, list):
                    status = params[0]

            if status is not None:
                with self.status_lock:
                    self.last_raw_status = status.copy()
                self._extract_status_from_message(status)
                return

            if method == "notify_gcode_response":
                params = data.get("params", [])
                if params and isinstance(params[0], str):
                    response_text = params[0].strip()
                    self._handle_new_response(response_text)

        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON decode: {e}", flush=True)
        except Exception as e:
            print(f"[ERROR] Message processing: {e}", flush=True)

    def _resubscribe(self):
        if not self._ws or not self._connected:
            print("[WSClient] Невозможно подписаться: нет соединения")
            return

        if self._subscribed:
            print("[WSClient] Подписка уже активна, пропускаем")
            return

        print("[WSClient] Повторная подписка на объекты...")
        try:
            self._ws.send(json.dumps({
                "jsonrpc": "2.0",
                "id": self.ID_SUBSCRIBE,
                "method": "printer.objects.subscribe",
                "params": {
                    "objects": self.QUERY_OBJECTS,
                    "request_response": True
                }
            }))
            self._subscribed = False  # Ждём подтверждения
        except Exception as e:
            print(f"[WSClient] Ошибка при повторной подписке: {e}")

    def _on_close(self, ws, close_status_code=None, close_msg=None):
        print(f"[WSClient] WebSocket закрыт: {close_status_code} {close_msg}")
        with self.status_lock:
            self.shared_status.clear()
            self.shared_status["connected"] = False
        self._connected = False
        self._subscribed = False

    def _on_error(self, ws, error):
        print(f"[WSClient] Ошибка WebSocket: {error}", flush=True)
        with self.status_lock:
            self.shared_status.clear()
            self.shared_status["connected"] = False
        self._connected = False
        self._subscribed = False

    def _ws_thread(self):
        while not self._stop_event.is_set():
            # Защита от параллельных запусков
            if threading.current_thread() != self._thread:
                print("[WSClient] Неправильный поток — выход")
                break

            try:
                self._load_connection_params()
                if not self.uri or "localhost" in self.uri:
                    time.sleep(self.RECONNECT_DELAY)
                    continue

                print(f"[WSClient] Подключение к: {self.uri}")
                
                # Создаём новый экземпляр WebSocketApp
                self._ws = websocket.WebSocketApp(
                    self.uri,
                    on_message=self._on_message,
                    on_open=self._on_open,
                    on_close=self._on_close,
                    on_error=self._on_error
                )
                
                if self._ws and not self._stop_event.is_set():
                    self._ws.run_forever(
                        ping_interval=0,
                        ping_timeout=1,
                        reconnect=False
                    )
                
                # Даём время на корректное закрытие
                time.sleep(0.1)
                
            except Exception as e:
                print(f"[WSClient] Ошибка в потоке: {e}")
                time.sleep(self.RECONNECT_DELAY)

    def start(self):
        # Полная очистка перед запуском
        if self._thread and self._thread.is_alive():
            print("[WSClient] Активный поток обнаружен — останавливаем...")
            self.stop()
            time.sleep(0.3)

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._ws_thread, daemon=True)
        self._thread.start()
        print("[WSClient] Поток запущен")

    def stop(self):
        print("[WSClient] Остановка...")
        self._stop_event.set()

        if self._ws:
            try:
                # 1. Немедленно останавливаем обработку
                self._ws.keep_running = False
                
                # 2. Закрываем соединение с таймаутом
                try:
                    self._ws.close(timeout=2)  # Уменьшенный таймаут
                except:
                    pass
                
                # 3. Принудительно закрываем сокет
                if hasattr(self._ws, 'sock') and self._ws.sock:
                    try:
                        self._ws.sock.shutdown(socket.SHUT_RDWR)
                    except:
                        pass
                    try:
                        self._ws.sock.close()
                    except:
                        pass
                
            except Exception as e:
                print(f"[WSClient] Ошибка при закрытии: {e}")
            finally:
                self._ws = None  # Обязательно обнуляем

        # 4. Ждём завершения потока с чётким таймаутом
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)  # Фиксированный таймаут
            if self._thread.is_alive():
                print("[WSClient] Поток не завершился за 3 сек — принудительно продолжаем")

        # 5. Полное сброс состояния
        self._connected = False
        self._subscribed = False
        self._thread = None

        with self.status_lock:
            self.shared_status.clear()
            self.shared_status["connected"] = False
            self.status = PrinterStatus()
            self.print_started = False

        print("[WSClient] Остановлен")

    def reconfigure(self):
        if not self._reconfig_lock.acquire(blocking=False):
            print("[WSClient] Переконфигурация уже выполняется, пропускаем...")
            return

        try:
            self._is_reconfiguring = True
            print("[WSClient] Переконфигурация...")

            # 1. Полная остановка текущего соединения
            self.stop()
            
            # 2. Гарантированная очистка
            time.sleep(0.5)  # Даём время на завершение
            
            # 3. Перезагрузка конфига
            self._load_connection_params()
            self._load_ws_config()
            
            # 4. Запуск нового соединения
            self.start()
            
        except Exception as e:
            print(f"[WSClient] Ошибка при переконфигурации: {e}")
        finally:
            self._is_reconfiguring = False
            self._reconfig_lock.release()

    def on_config_reload(self):
        print("[WSClient] Получен сигнал перезагрузки конфигурации")
        self.reconfigure()

    def _handle_new_response(self, response_text: str):
        response_cfg = self.config_manager.get_config_section("response") or {}
        matched = False

        for section, patterns in response_cfg.items():
            for resp_id, templates in patterns.items():
                if response_text in templates:
                    matched = True
                    with self.queue_lock:
                        if self.shared_status.get("response") is None:
                            with self.status_lock:
                                self.shared_status["response"] = response_text
                                self.status.gcode_response = response_text
                        else:
                            self.response_queue.append(response_text)
                    break
            if matched:
                break

        if not matched:
            print(f"[WSClient] Нет совпадений для response: {response_text}", flush=True)

    def clear_response(self):
        with self.status_lock, self.queue_lock:
            self.shared_status["response"] = None
            self.status.gcode_response = None
            if self.response_queue:
                next_response = self.response_queue.pop(0)
                self.shared_status["response"] = next_response
                self.status.gcode_response = next_response

    def get_state(self) -> PrinterStatus:
        return self.status

    def query_status(self):
        if (not self._ws or not self._connected or not self._subscribed or
                not hasattr(self._ws, "sock") or not self._ws.sock):
            print("[WSClient] Невозможно запросить статус: нет активного соединения", flush=True)
            return

        request = {
            "jsonrpc": "2.0",
            "id": self.ID_QUERY,
            "method": "printer.objects.query",
            "params": {"objects": self.QUERY_OBJECTS},
        }

        try:
            self._ws.sock.settimeout(self.WS_SETTINGS["send_timeout"])
            self._ws.send(json.dumps(request))
            self._ws.sock.settimeout(None)
        except Exception as e:
            print(f"[WSClient] Ошибка при запросе статуса: {e}", flush=True)

    def has_pending_response(self) -> bool:
        with self.status_lock:
            return bool(self.shared_status.get("response"))

    def full_restart(self):
        if self._is_restarting:
            print("[WSClient] Перезапуск уже в процессе, пропускаем...")
            return

        self._is_restarting = True  # Устанавливаем флаг активного перезапуска
        print("[WSClient] Полный перезапуск клиента (с убийством потока)...")

        self._restart_in_progress = True
        self._stop_event.set()

        if self._ws:
            try:
                self._ws.keep_running = False
                self._ws.close(timeout=1)
            except Exception as e:
                print(f"[WSClient] Ошибка при закрытии WebSocket: {e}")
            self._ws = None

        if self._thread and self._thread.is_alive():
            current_thread = threading.current_thread()
            if self._thread != current_thread:
                try:
                    self._thread.join(timeout=5)
                    if self._thread.is_alive():
                        print("[WSClient] Поток не завершился за 5 сек — продолжаем без него")
                except RuntimeError as e:
                    print(f"[WSClient] Ошибка join потока: {e}")
            else:
                print("[WSClient] Не могу join текущий поток — пропускаем join()")


        self._thread = None
        self._connected = False
        self._subscribed = False

        self._load_connection_params()
        self._load_ws_config()

        with self.status_lock:
            self.shared_status["connected"] = False
            self.status = PrinterStatus()
            self.print_started = False
            self.manual_reset_active = False
            self.set_print_time_announced(False)

        with self.queue_lock:
            self.response_queue.clear()
            self.shared_status["response"] = None
            self.status.gcode_response = None

        self.start()

        self._restart_in_progress = False
        self._is_restarting = False  # Снимаем флаг после завершения

        print("[WSClient] Полный перезапуск завершён")
