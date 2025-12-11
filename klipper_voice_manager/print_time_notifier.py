import re
from shared_utils import enqueue_phrase
from number_words import number_to_words
from plural_utils import plural_form



class PrintTimeNotifier:
    """
    Отвечает за уведомление о расчётном времени печати на основе имени файла.
    Флаг озвучивания (_print_time_announced) управляется WSClient на основе состояния печати,
    а не на основе имени файла. Это позволяет корректно озвучивать одинаковые файлы при повторных печатях.
    """

    def __init__(self, config_manager, sound_manager, ws):
        self.config_manager = config_manager
        self.sound_manager = sound_manager
        self.ws = ws


    def check(self, status):
        """Проверяет и озвучивает расчётное время печати из имени файла."""
        # Проверяем, что печать активна
        if status.print_state != "printing":
            return

        config = self.config_manager.get_config_section("progress")
        if not config:
            print("[PrintTimeNotifier] Конфиг секции 'progress' не найден", flush=True)
            return
        notifications_cfg = config.get("notifications", {})

        # Проверяем, включено ли оповещение о начальном расчёте времени
        if not notifications_cfg.get("initial_estimate", False):
            return

        # Проверяем источник данных — ТОЛЬКО filename
        source = config.get("initial_estimate_source", "filename")
        if source != "filename":
            return  # Не наша зона ответственности

        # Проверяем наличие имени файла
        if not status.filename or not isinstance(status.filename, str):
            print("[PrintTimeNotifier] filename не задан или не строка", flush=True)
            # ПЕРЕДАЁМ УПРАВЛЕНИЕ В ProgressNotifier: время не найдено в filename
            self.ws.set_print_time_announced(False)
            return

        # Проверяем флаг уже озвученного времени через потокобезопасный метод
        if self.ws.is_print_time_announced():
            return

        # Ищем временную метку с помощью regex из конфига (real-time!)
        time_pattern_cfg = self.config_manager.get_config_section("time_pattern")
        if not time_pattern_cfg or "regex" not in time_pattern_cfg:
            print("[PrintTimeNotifier] Конфиг time_pattern не найден или нет regex", flush=True)
            # ПЕРЕДАЁМ УПРАВЛЕНИЕ В ProgressNotifier
            self.ws.set_print_time_announced(False)
            return

        try:
            time_regex = re.compile(time_pattern_cfg["regex"])
            match = time_regex.search(status.filename)
            if not match:
                # ПЕРЕДАЁМ УПРАВЛЕНИЕ В ProgressNotifier
                self.ws.set_print_time_announced(False)
                return

            time_str = match.group()
            days = hours = minutes = seconds = 0

            # Извлекаем компоненты времени
            if d_match := re.search(r"(\d+)d", time_str, re.IGNORECASE):
                days = int(d_match.group(1))
            if h_match := re.search(r"(\d+)h", time_str, re.IGNORECASE):
                hours = int(h_match.group(1))
            if m_match := re.search(r"(\d+)m", time_str, re.IGNORECASE):
                minutes = int(m_match.group(1))
            if s_match := re.search(r"(\d+)s", time_str, re.IGNORECASE):
                seconds = int(s_match.group(1))

            # Проверяем, что хотя бы один компонент времени найден
            if days == 0 and hours == 0 and minutes == 0 and seconds == 0:
                print("[PrintTimeNotifier] Не найдено временных компонентов в строке", flush=True)
                # ПЕРЕДАЁМ УПРАВЛЕНИЕ В ProgressNotifier
                self.ws.set_print_time_announced(False)
                return

            total_seconds = days * 86400 + hours * 3600 + minutes * 60 + seconds
            if total_seconds <= 0:
                print("[PrintTimeNotifier] Рассчитанное время ≤ 0", flush=True)
                # ПЕРЕДАЁМ УПРАВЛЕНИЕ В ProgressNotifier
                self.ws.set_print_time_announced(False)
                return

            # Формируем фразу для озвучивания
            phrase = ["расчетное", "время", "печати"]

            if days > 0:
                phrase.extend(number_to_words(days, gender="m"))
                phrase.append(plural_form(days, ("день", "дня", "дней")))
            if hours > 0:
                phrase.extend(number_to_words(hours, gender="m"))
                phrase.append(plural_form(hours, ("час", "часа", "часов")))
            if minutes > 0:
                phrase.extend(number_to_words(minutes, gender="f"))
                phrase.append(plural_form(minutes, ("минута", "минуты", "минут")))
            if seconds > 0:
                phrase.extend(number_to_words(seconds, gender="f"))
                phrase.append(plural_form(seconds, ("секунда", "секунды", "секунд")))

            # Устанавливаем флаг ПЕРЕД озвучкой через потокобезопасный метод
            # ТОЛЬКО ЕСЛИ ВРЕМЯ НАЙДЕНО И КОРРЕКТНО
            self.ws.set_print_time_announced(True)
            enqueue_phrase(phrase, self.sound_manager, self.config_manager)
            print(f"[PrintTimeNotifier] Озвучено расчётное время печати из filename", flush=True)

        except Exception as e:
            print(f"[PrintTimeNotifier ERROR] Ошибка при обработке filename: {e}", flush=True)
            # В случае ошибки тоже передаём управление в ProgressNotifier
            self.ws.set_print_time_announced(False)
