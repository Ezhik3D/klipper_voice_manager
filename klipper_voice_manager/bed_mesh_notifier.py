"""
Модуль BedMeshNotifier.

Отвечает за обработку событий построения сетки (bed mesh) в 3D‑принтере:
- анализирует ответ от принтера;
- сопоставляет шаблоны из конфига;
- формирует и отправляет голосовые уведомления.

Зависимости:
- shared_utils: функция enqueue_phrase для постановки фразы в очередь.
- ConfigManager: доступ к конфигурационным данным.
- SoundManager: управление воспроизведением звука.
- WSClient: получение статуса и управление response.
"""

from shared_utils import enqueue_phrase


class BedMeshNotifier:
    """
    Обработчик событий построения сетки (bed mesh) для голосовых уведомлений.

    Атрибуты:
        config_manager (ConfigManager): менеджер конфигурации.
        sound_manager (SoundManager): менеджер звука.
        ws_client (WSClient): клиент WebSocket для получения статуса.

    Методы:
        check(): анализирует текущий response и отправляет уведомление при совпадении.
    """

    def __init__(self, config_manager, sound_manager, ws_client):
        """
        Инициализирует BedMeshNotifier.

        Args:
            config_manager (ConfigManager): экземпляр менеджера конфигурации.
            sound_manager (SoundManager): экземпляр менеджера звука.
            ws_client (WSClient): экземпляр клиента WebSocket.
        """
        self.config_manager = config_manager
        self.sound_manager = sound_manager
        self.ws_client = ws_client

    def check(self):
        """
        Анализирует текущий response от принтера и отправляет голосовое уведомление
        при совпадении с шаблонами из конфигурации.

        Логика:
        1. Получает response под лок-ом.
        2. Проверяет валидность response.
        3. Загружает конфиг bed_mesh.
        4. Находит ID‑ключ по шаблонам.
        5. Определяет тип события (START/END) и адаптивность.
        6. Проверяет, включено ли уведомление в конфиге.
        7. Формирует фразу и отправляет её.
        8. Очищает response.

        Обрабатываемые исключения:
        - KeyError: если ключ отсутствует в конфиге.
        - AttributeError: если атрибут недоступен у объекта.
        - Exception: все остальные (логируется, но не препятствует работе).
        """
        try:
            # Получаем текущий response под лок-ом
            with self.ws_client.status_lock:
                raw_response = self.ws_client.shared_status.get("response")

            # Проверяем валидность response
            if not raw_response or not isinstance(raw_response, str):
                return

            # 1. ВСЕГДА берём свежий конфиг через ConfigManager (не кэшируем!)
            response_cfg = self.config_manager.get_config_section("response")
            bed_mesh_cfg = response_cfg.get("bed_mesh", {})

            # 2. Ищем ID-ключ, где raw_response есть в шаблонах
            matched_id = None
            for resp_id, templates in bed_mesh_cfg.items():
                if raw_response in templates:
                    matched_id = resp_id
                    break

            if not matched_id:
                print(
                    f"[BedMeshNotifier] Нет совпадений для: {raw_response}", flush=True
                )
                return

            # 3. Разбор ID-ключа (не шаблона!)
            # Определяем event_type по окончанию
            if matched_id.endswith("_START"):
                event_type = "START"
            elif matched_id.endswith("_END"):
                event_type = "END"
            else:
                print(
                    f"[BedMeshNotifier] Неизвестный формат ключа: {matched_id}",
                    flush=True,
                )
                return

            # Проверяем наличие "_ADAPTIVE" в ключе
            is_adaptive = "_ADAPTIVE" in matched_id

            # 4. Проверка активности уведомления по конфигу
            bed_mesh_notifications = (
                self.config_manager.get_config_section("bed_mesh_notifications") or {}
            )
            config_key = matched_id
            is_enabled = bed_mesh_notifications.get(
                config_key, True
            )  # по умолчанию True

            if is_enabled:
                # 5. Формирование фразы на основе ID-ключа
                phrase = []

                if event_type == "START":
                    phrase.extend(["начало", "построения"])

                if is_adaptive:
                    if event_type == "START":
                        phrase.extend(["адаптивной", "сетки"])
                    else:
                        phrase.extend(["адаптивная", "сетка"])
                else:
                    if event_type == "START":
                        phrase.append("сетки")
                    else:
                        phrase.append("сетка")

                if event_type == "END":
                    phrase.append("построена")

                # 6. Отправляем фразу
                enqueue_phrase(phrase, self.sound_manager, self.config_manager)

            # 7. ОБЯЗАТЕЛЬНО очищаем response после обработки
            self.ws_client.clear_response()

        except KeyError as e:
            print(
                f"[BedMeshNotifier] Ключ не найден в конфиге: {type(e).__name__}: {e}",
                flush=True,
            )
        except AttributeError as e:
            print(
                f"[BedMeshNotifier] Ошибка атрибута: {type(e).__name__}: {e}",
                flush=True,
            )
        except Exception as e:  # Остаточные исключения (редкие/непредвиденные)
            print(
                f"[BedMeshNotifier] Неожиданная ошибка в check(): {type(e).__name__}: {e}",
                flush=True,
            )
