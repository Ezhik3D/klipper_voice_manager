import re
from shared_utils import enqueue_phrase


class ParkingNotifier:
    """
    Уведомляет о начале и конце парковки осей принтера.
    Работает с любыми строковыми шаблонами в конфиге — важен только ID-ключ.
    Поддерживает включение/выключение отдельных типов уведомлений через конфиг.
    Даже при отключённом уведомлении response обрабатывается и удаляется из очереди.
    """

    # Регулярка для извлечения оси и статуса из ID-ключа (не из шаблона!)
    G28_ID_RE = re.compile(r"G28(?:_([XYZ]))?_(START|END)")

    def __init__(self, config_manager, sound_manager, ws_client):
        self.config_manager = config_manager
        self.sound_manager = sound_manager
        self.ws_client = ws_client

    def check(self):
        try:
            # Получаем текущий response под лок-ом
            with self.ws_client.status_lock:
                raw_response = self.ws_client.shared_status.get("response")

            # Проверяем валидность response
            if not raw_response or not isinstance(raw_response, str):
                return

            # 1. ВСЕГДА берём свежий конфиг через ConfigManager (не кэшируем!)
            response_cfg = self.config_manager.get_config_section("response") or {}
            parking_cfg = response_cfg.get("parking", {})

            # 2. Ищем ID-ключ, где raw_response есть в шаблонах
            matched_id = None
            for resp_id, templates in parking_cfg.items():
                if raw_response in templates:
                    matched_id = resp_id
                    break

            if not matched_id:
                print(
                    f"[ParkingNotifier] Нет совпадений для: {raw_response}", flush=True
                )
                return

            # 3. Разбор ID-ключа (не шаблона!)
            match = self.G28_ID_RE.match(matched_id)
            axis = None
            event_type = None

            if match:
                axis = match.group(1)  # X/Y/Z или None
                event_type = match.group(2)  # START/END

            # Если не удалось разобрать ID-ключ — выходим
            if not event_type:
                print(
                    f"[ParkingNotifier] Не удалось разобрать ID-ключ: {matched_id}",
                    flush=True,
                )
                return

            # 4. Проверка активности уведомления по конфигу
            g28_notifications = (
                self.config_manager.get_config_section("g28_notifications") or {}
            )

            # Формируем ключ для проверки в конфиге
            config_key = f"G28{f'_{axis}' if axis else ''}_{event_type}"

            is_enabled = True
            if config_key in g28_notifications:
                is_enabled = g28_notifications[config_key]

            if is_enabled:
                # 5. Формирование фразы на основе ID-ключа
                phrase = ["парковка"]

                if axis:
                    axis_lower = axis.lower()
                    # Берём слово для оси из конфига (например, "икс", "игрек")
                    axis_word = self.config_manager.get_config_section(
                        "axis_words"
                    ).get(axis_lower, axis_lower)
                    phrase.extend(["оси", axis_word])

                if event_type == "END":
                    phrase.append("завершена")

                # 6. Отправляем фразу
                enqueue_phrase(phrase, self.sound_manager, self.config_manager)

            # 7. ОБЯЗАТЕЛЬНО очищаем response после обработки (даже если уведомление было отключено)
            self.ws_client.clear_response()

        except Exception as e:
            print(
                f"[ParkingNotifier] Ошибка в check: {type(e).__name__}: {e}", flush=True
            )
