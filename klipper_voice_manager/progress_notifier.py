import time
import math
from typing import List
from number_words import number_to_words
from plural_utils import plural_form
from shared_utils import enqueue_phrase
from unit_optimizer_mm import get_compact_filament_phrase_mm
from unit_optimizer_mass import get_compact_filament_phrase_grams


class ProgressNotifier:
    """
    Уведомляет о прогрессе печати.
    Для initial_estimate использует потокобезопасные методы WSClient.
    """

    def __init__(self, config_manager, sound_manager, ws):
        self.config_manager = config_manager
        self.sound_manager = sound_manager
        self.ws = ws

        # Состояние (аналог глобальных переменных из старого кода)
        self.last_notified_percent = -1
        self.progress_interval_mode = 1
        self.print_start_time = None

    def check(self, status):
        """Основной метод — проверяет прогресс и отправляет уведомления."""
        try:
            config = self.config_manager.get_config_section("progress")
            if config is None:
                print("[PROGRESS] ОШИБКА: секция 'progress' не найдена в конфиге", flush=True)
                return

            notifications_cfg = config.get("notifications", {})
            print_state = status.print_state
            progress_percent = status.progress_percent
            elapsed_time = status.elapsed_time
            filament_used = status.filament_used

            if print_state != "printing":
                return

            # Инициализация времени старта при первом вызове
            if self.print_start_time is None:
                self.print_start_time = time.time()

            # Определение интервала уведомлений
            self._update_interval(config, progress_percent, elapsed_time)

            # Озвучивание при ровно 1% прогресса (один раз за печать)
            if (notifications_cfg.get("initial_estimate", False) and
                    elapsed_time > 0 and
                    1.0 <= progress_percent < 2.0):  # строго 1%
                self._notify_initial_estimate(progress_percent, elapsed_time, config)



            # Проверка, нужно ли отправлять уведомление сейчас
            send_notification = self._should_send_notification(
                config, progress_percent
            )

            if send_notification:
                if notifications_cfg.get("progress", False):
                    self._notify_progress(progress_percent, config)
                if notifications_cfg.get("elapsed_time", False):
                    self._notify_elapsed_time(elapsed_time)
                if (notifications_cfg.get("remaining_time", False) and
                        elapsed_time > 0):
                    self._notify_remaining_time(progress_percent, elapsed_time)
                if (notifications_cfg.get("filament_usage", False) and
                    filament_used > 0):
                    self._notify_filament_usage(filament_used, config)


                self.last_notified_percent = progress_percent


        except AttributeError as e:
            print(f"[PROGRESS] ОШИБКА: отсутствует поле в status: {e}", flush=True)
        except (KeyError, TypeError, ValueError) as e:
            print(
                f"[PROGRESS] ОШИБКА в ProgressNotifier.check: {type(e).__name__}: {e}",
                flush=True,
            )
        except Exception as e:
            print(
                f"[PROGRESS] НЕПРЕДВИДЕННАЯ ОШИБКА в ProgressNotifier.check: {type(e).__name__}: {e}",
                flush=True,
            )

    def _update_interval(self, config, progress_percent, elapsed_time):
        """Определяет интервал уведомлений."""
        notif_intervals = config.get("notification_intervals", "auto")


        if notif_intervals == "auto":
            if progress_percent > 0 and elapsed_time > 0:
                estimated_total = elapsed_time / (progress_percent / 100.0)
                self.progress_interval_mode = self._select_interval_auto(estimated_total)
            else:
                elapsed_since_start = time.time() - self.print_start_time
                if elapsed_since_start < 600:
                    self.progress_interval_mode = 10
                elif elapsed_since_start < 1800:
                    self.progress_interval_mode = 5
                else:
                    self.progress_interval_mode = 1
        else:
            if isinstance(notif_intervals, int):
                self.progress_interval_mode = notif_intervals
            elif isinstance(notif_intervals, list) and notif_intervals:
                self.progress_interval_mode = notif_intervals[0]

    def _select_interval_auto(self, total_time_sec: float) -> int:
        """Автовыбор интервала."""
        hours = total_time_sec / 3600.0
        if hours > 3.0:
            return 1
        if 1.0 <= hours <= 3.0:
            return 5
        return 10

    def _should_send_notification(self, config, progress_percent) -> bool:
        """Проверяет, нужно ли отправить уведомление сейчас."""
        if progress_percent <= 0:
            return False

        notif_intervals = config.get("notification_intervals", "auto")

        if isinstance(notif_intervals, int):
            return (self._should_notify(progress_percent) and
                    self._is_significant_change(progress_percent))
        elif isinstance(notif_intervals, list):
            return (progress_percent in notif_intervals and
                    progress_percent != self.last_notified_percent and
                    self._is_significant_change(progress_percent))

        return False

    def _should_notify(self, percent: int) -> bool:
        """Проверка по интервалу."""
        return (percent % self.progress_interval_mode == 0 and
                percent != self.last_notified_percent)

    def _is_significant_change(self, current: float) -> bool:
        """Проверка значимого изменения."""
        return abs(current - self.last_notified_percent) >= 0.5

    def _notify_initial_estimate(self, progress_percent, elapsed, config):
        """Озвучивает начальную оценку времени (calculation mode)."""
        try:
            if progress_percent <= 0:
                return

            # ПРОВЕРЯЕМ ФЛАГ В НАЧАЛЕ: если время уже озвучено, выходим
            if self.ws.is_print_time_announced():
                return

            source = config.get("initial_estimate_source", "filename")

            # Теперь НЕ ВЫХОДИМ при source == "filename"
            # Потому что PrintTimeNotifier мог не найти время и сбросить флаг

            # Расчётное время (calculation mode)
            estimated_total = elapsed / (progress_percent / 100.0)
            remaining_time = max(0, estimated_total - elapsed)
            phrase = ["расчетное", "время", "печати"] + self._format_time(remaining_time)
            enqueue_phrase(phrase, self.sound_manager, self.config_manager)

            # Устанавливаем флаг через потокобезопасный метод WSClient
            self.ws.set_print_time_announced(True)
            print(f"[PROGRESS] Озвучено расчётное время печати (calculation mode)", flush=True)

        except (ZeroDivisionError, TypeError, ValueError, AttributeError) as e:
            print(f"[PROGRESS] ОШИБКА в _notify_initial_estimate: {type(e).__name__}: {e}", flush=True)


    def _notify_progress(self, progress_percent, config):
        """Озвучивает процент завершения."""
        try:
            percent_alias = plural_form(
                progress_percent, ("процент", "процента", "процентов")
            )
            phrase = (
                ["прогресс", "печати"]
                + number_to_words(progress_percent)
                + [percent_alias]
            )
            enqueue_phrase(phrase, self.sound_manager, self.config_manager)
        except (TypeError, ValueError) as e:
            print(
                f"[PROGRESS] ОШИБКА в _notify_progress: {type(e).__name__}: {e}",
                flush=True,
            )

    def _notify_elapsed_time(self, elapsed):
        """Озвучивает прошедшее время."""
        try:
            enqueue_phrase(
                ["прошло"] + self._format_time(elapsed),
                self.sound_manager,
                self.config_manager,
            )
        except (TypeError, ValueError) as e:
            print(
                f"[PROGRESS] ОШИБКА в _notify_elapsed_time: {type(e).__name__}: {e}",
                flush=True,
            )

    def _notify_remaining_time(self, progress_percent, elapsed):
        """Озвучивает оставшееся время."""
        try:
            estimated_total = elapsed / (progress_percent / 100.0)
            remaining_time = max(0, estimated_total - elapsed)
            enqueue_phrase(
                ["осталось"] + self._format_time(remaining_time),
                self.sound_manager,
                self.config_manager,
            )
        except (ZeroDivisionError, TypeError, ValueError) as e:
            print(
                f"[PROGRESS] ОШИБКА в _notify_remaining_time: {type(e).__name__}: {e}",
                flush=True,
            )

    def _format_time(self, seconds: float) -> list:
        """Преобразует секунды в речевое представление времени."""
        try:
            seconds = int(seconds)
            hours, rem = divmod(seconds, 3600)
            minutes = rem // 60
            parts = []

            if hours > 0:
                parts += number_to_words(hours) + [
                    plural_form(hours, ("час", "часа", "часов"))
                ]
            if minutes > 0:
                parts += number_to_words(minutes, gender="f") + [
                    plural_form(minutes, ("минута", "минуты", "минут"))
                ]
            elif hours == 0 and minutes == 0:
                parts += ["меньше", "минуты"]

            return parts
        except (TypeError, ValueError) as e:
            print(
                f"[PROGRESS] ОШИБКА в _format_time: {type(e).__name__}: {e}",
                flush=True,
            )
            return ["время", "неизвестно"]

    def _notify_filament_usage(self, filament_used, config):
        """Озвучивает расход филамента."""
        try:
            units = config.get("filament_units", "грамм")
            density = config.get("filament_density", 1.24)
            diameter = config.get("filament_diameter", 1.75)
            unit_style = config.get("unit_style", "auto")
            phrase = ["расход", "филамента"]

            if units == "грамм":
                grams = int(
                    round(
                        self._filament_length_to_grams(filament_used, diameter, density)
                    )
                )
                if unit_style == "compact":
                    compact_phrase = get_compact_filament_phrase_grams(grams)
                    phrase += compact_phrase
                else:
                    if grams >= 1000:
                        kilograms = grams // 1000
                        remaining_grams = grams % 1000
                        kg_alias = plural_form(
                            kilograms, ("килограмм", "килограмма", "килограммов")
                        )
                        phrase += number_to_words(kilograms) + [kg_alias]
                        if remaining_grams > 0:
                            g_alias = plural_form(
                                remaining_grams, ("грамм", "грамма", "граммов")
                            )
                            phrase += number_to_words(remaining_grams) + [g_alias]
                    else:
                        g_alias = plural_form(grams, ("грамм", "грамма", "граммов"))
                        phrase += number_to_words(grams) + [g_alias]
            else:
                mm = int(filament_used)
                if unit_style == "compact":
                    compact_phrase = get_compact_filament_phrase_mm(mm)
                    phrase += compact_phrase
                else:
                    converted_units = self._convert_mm_to_units(mm)
                    if converted_units:
                        phrase += converted_units

            enqueue_phrase(phrase, self.sound_manager, self.config_manager)
        except (TypeError, ValueError, KeyError) as e:
            print(
                f"[PROGRESS] ОШИБКА в _notify_filament_usage: {type(e).__name__}: {e}",
                flush=True,
            )
        except Exception as e:
            print(
                f"[PROGRESS] НЕПРЕДВИДЕННАЯ ОШИБКА в _notify_filament_usage: {type(e).__name__}: {e}",
                flush=True,
            )

    def _filament_length_to_grams(self, length_mm, diameter_mm, density_g_per_cm3):
        """Конвертирует длину филамента в граммы."""
        try:
            radius_mm = diameter_mm / 2.0
            cross_section_area_mm2 = math.pi * (radius_mm ** 2)
            volume_mm3 = cross_section_area_mm2 * length_mm
            volume_cm3 = volume_mm3 / 1000.0
            mass_g = volume_cm3 * density_g_per_cm3
            return mass_g
        except (TypeError, ValueError, ZeroDivisionError) as e:
            print(
                f"[PROGRESS] ОШИБКА в _filament_length_to_grams: {type(e).__name__}: {e}",
                flush=True,
            )
            return 0.0

    def _convert_mm_to_units(self, mm: int) -> List[str]:
        """Конвертирует миллиметры в текстовое представление."""
        try:
            if mm <= 0:
                return []

            kilometers = mm // 1_000_000
            rem = mm % 1_000_000
            meters = rem // 1_000
            rem %= 1_000
            centimeters = rem // 10
            millimeters = rem % 10

            phrase = []
            if kilometers > 0:
                phrase += number_to_words(kilometers) + [
                    plural_form(kilometers, ("километр", "километра", "километров"))
                ]
            if meters > 0:
                phrase += number_to_words(meters) + [
                    plural_form(meters, ("метр", "метра", "метров"))
                ]
            if centimeters > 0:
                phrase += number_to_words(centimeters) + [
                    plural_form(centimeters, ("сантиметр", "сантиметра", "сантиметров"))
                ]
            if millimeters > 0:
                phrase += number_to_words(millimeters) + [
                    plural_form(millimeters, ("миллиметр", "миллиметра", "миллиметров"))
                ]

            if not phrase:
                phrase = number_to_words(mm) + [
                    plural_form(mm, ("миллиметр", "миллиметра", "миллиметров"))
                ]

            return phrase
        except (TypeError, ValueError) as e:
            print(
                f"[PROGRESS] ОШИБКА в _convert_mm_to_units: {type(e).__name__}: {e}",
                flush=True,
            )
            return []
