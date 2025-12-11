from shared_utils import enqueue_phrase

class CustomNotifier:
    """
    Универсальный модуль для кастомных оповещений на основе шаблонов из конфига.
    """

    def __init__(self, config_manager, sound_manager, ws_client):
        self.config_manager = config_manager
        self.sound_manager = sound_manager
        self.ws_client = ws_client

    def check(self):
        try:
            with self.ws_client.status_lock:
                raw_response = self.ws_client.shared_status.get("response")

            if not raw_response or not isinstance(raw_response, str):
                return

            response_cfg = self.config_manager.get_config_section("response")
            custom_response_cfg = response_cfg.get("custom_response", {})
            if not custom_response_cfg:
                return

            # Поиск совпадающего шаблона
            matched_id = None
            for resp_id, templates in custom_response_cfg.items():
                if raw_response in templates:
                    matched_id = resp_id
                    break

            if not matched_id:
                print(f"[CustomNotifier] Нет совпадений для: {raw_response}", flush=True)
                return

            # Загрузка конфигурации уведомлений
            notifier_cfg = self.config_manager.get_config_section("custom_notifier")
            if not notifier_cfg:
                self.ws_client.clear_response()
                print("[CustomNotifier] Секция custom_notifier не найдена", flush=True)
                return

            notification_config = notifier_cfg.get(matched_id)
            if notification_config is None:
                print(f"[CustomNotifier] Конфигурация для ID {matched_id} не найдена", flush=True)
                self.ws_client.clear_response()
                return

            # Корректное чтение флага включения
            true_key = next(
                (k for k in notification_config.keys() if str(k).lower() == "true"),
                None
            )
            
            if true_key is None:
                is_enabled = False
                print(f"[CustomNotifier] Ключ 'true' не найден для {matched_id}", flush=True)
            else:
                raw_value = notification_config[true_key]
                if isinstance(raw_value, bool):
                    is_enabled = raw_value
                elif isinstance(raw_value, str):
                    is_enabled = raw_value.strip().lower() in ("true", "1", "yes")
                else:
                    is_enabled = bool(raw_value)


            # Логика обработки согласно ТЗ:
            # - Если is_enabled=True: отправляем оповещение, затем очищаем response
            # - Если is_enabled=False: сразу очищаем response (без оповещения)
            if is_enabled:
                aliace = notification_config.get("aliace", [])
                if aliace:
                    enqueue_phrase(aliace, self.sound_manager, self.config_manager)
                else:
                    print(f"[CustomNotifier] Пустой aliace для {matched_id}", flush=True)
                
                # Очищаем response после успешного оповещения
                self.ws_client.clear_response()
            else:
                # Сразу очищаем response без оповещения
                self.ws_client.clear_response()


        except KeyError as e:
            print(f"[CustomNotifier] Ключ не найден в конфиге: {type(e).__name__}: {e}", flush=True)
        except AttributeError as e:
            print(f"[CustomNotifier] Ошибка атрибута: {type(e).__name__}: {e}", flush=True)
        except Exception as e:
            print(f"[CustomNotifier] Неожиданная ошибка в check(): {type(e).__name__}: {e}", flush=True)
