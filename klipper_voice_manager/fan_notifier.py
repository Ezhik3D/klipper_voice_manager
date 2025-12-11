import time
import threading
from number_words import number_to_words
from plural_utils import plural_form
from shared_utils import enqueue_phrase


class FanNotifier:
    """
    Отвечает за уведомления о состоянии вентилятора:
    включение/выключение, изменение скорости.
    """

    def __init__(self, config_manager, sound_manager, ws):
        self.config_manager = config_manager
        self.sound_manager = sound_manager
        self.ws = ws
        self.fan_enabled = False
        self.fan_speed_percent = 0
        self.last_announce_time = 0
        self.lock = threading.Lock()

    def check(self, status):
        """
        Анализирует состояние вентилятора и озвучивает изменения.

        Args:
            status: объект статуса принтера
        """
        fan_cfg = self.config_manager.get_config_section("fan").get("notifications", {})

        # Читаем настройки из конфига
        announce_interval = fan_cfg.get("announce_interval_sec", 5)
        percent_threshold = max(0, fan_cfg.get("percent_change_threshold", 5))

        on_off_phrases_enabled = fan_cfg.get("on_off_phrases", False)
        percent_phrases_enabled = fan_cfg.get("percent_phrases", False)

        current_percent = int(round(status.fan_percent))
        is_fan_on = current_percent > 0

        with self.lock:
            # Определяем, изменилось ли состояние включения вентилятора
            if is_fan_on != self.fan_enabled:
                if is_fan_on:
                    if on_off_phrases_enabled and percent_phrases_enabled:
                        enqueue_phrase(
                            ["обдув", "включен"],
                            self.sound_manager,
                            self.config_manager,
                        )
                        percent_alias = plural_form(
                            current_percent, ("процент", "процента", "процентов")
                        )
                        enqueue_phrase(
                            number_to_words(current_percent) + [percent_alias],
                            self.sound_manager,
                            self.config_manager,
                        )
                    elif not on_off_phrases_enabled and percent_phrases_enabled:
                        percent_alias = plural_form(
                            current_percent, ("процент", "процента", "процентов")
                        )
                        enqueue_phrase(
                            ["обдув"]
                            + number_to_words(current_percent)
                            + [percent_alias],
                            self.sound_manager,
                            self.config_manager,
                        )
                    elif on_off_phrases_enabled and not percent_phrases_enabled:
                        enqueue_phrase(
                            ["обдув", "включен"],
                            self.sound_manager,
                            self.config_manager,
                        )
                    self.fan_speed_percent = current_percent
                else:
                    if on_off_phrases_enabled:
                        enqueue_phrase(
                            ["обдув", "выключен"],
                            self.sound_manager,
                            self.config_manager,
                        )
                    self.fan_speed_percent = 0
                self.fan_enabled = is_fan_on

            # Повторное оповещение при изменении скорости больше порога спустя время announce_interval
            now = time.time()
            if (
                is_fan_on
                and percent_phrases_enabled
                and abs(current_percent - self.fan_speed_percent) > percent_threshold
            ):
                if now - self.last_announce_time > announce_interval:
                    percent_alias = plural_form(
                        current_percent, ("процент", "процента", "процентов")
                    )
                    enqueue_phrase(
                        ["обдув"] + number_to_words(current_percent) + [percent_alias],
                        self.sound_manager,
                        self.config_manager,
                    )
                    self.fan_speed_percent = current_percent
                    self.last_announce_time = now

    def reset(self):
        """Сброс состояния уведомлений"""
        with self.lock:
            self.fan_enabled = False
            self.fan_speed_percent = 0
            self.last_announce_time = 0
