import time
import threading
from number_words import number_to_words
from plural_utils import plural_form
from shared_utils import enqueue_phrase


class HeaterState:
    """Внутреннее представление состояния нагревателя"""

    def __init__(self, component_name, component_key):
        self.component_name = component_name
        self.component_key = component_key
        self.last_target = 0.0
        self.reached = False
        self.low_alerted = False
        self.high_alerted = False
        self.target_achieved_and_stable = False
        self.heater_off_alerted = False

    def reset(self, new_target):
        """Сброс состояния при изменении целевой температуры"""
        self.last_target = new_target
        self.reached = False
        self.low_alerted = False
        self.high_alerted = False
        self.target_achieved_and_stable = False
        self.heater_off_alerted = False


class TemperaturesNotifier:
    """
    Отвечает за мониторинг температур печати:
    предупреждения о низкой/высокой температуре,
    оповещение о достижении целевой температуры,
    оповещение об отключении нагрева.
    """

    def __init__(self, config_manager, sound_manager, ws):
        self.config_manager = config_manager
        self.sound_manager = sound_manager
        self.ws = ws
        self.lock = threading.Lock()

        # Состояние нагревателей
        self.bed_state = HeaterState("стола", "bed")
        self.ext_state = HeaterState("экструдера", "extruder")

        # Флаг инициализации
        self.init_complete = False

    def check(self, status):
        """
        Анализирует температуры и выполняет озвучку в зависимости от событий.

        Args:
            status: объект статуса принтера
        """
        try:
            # Одноразовая задержка при первом запуске
            if not self.init_complete:
                time.sleep(2)
                self.init_complete = True

            # Температура и цель для стола
            heater_bed = status.bed_temp
            bed_target = status.bed_target
            self._check_temperature(self.bed_state, heater_bed, bed_target)

            # Температура и цель для экструдера
            extruder_temp = status.ext_temp
            ext_target = status.ext_target
            self._check_temperature(self.ext_state, extruder_temp, ext_target)

        except AttributeError as e:
            print(f"[TEMP] ОШИБКА: отсутствует поле в status: {e}", flush=True)
        except Exception as e:
            print(
                f"[TEMP] ОШИБКА в TemperaturesNotifier.check: {type(e).__name__}: {e}",
                flush=True,
            )

    def _check_temperature(self, state, temp, target):
        """
        Проверяет температуру компонента и озвучивает события.

        Args:
            state: объект HeaterState для компонента
            temp: текущая температура
            target: целевая температура
        """
        try:
            with self.lock:
                # Получаем секцию конфигурации
                temperature_cfg = self.config_manager.get_config_section("temperature")
                if temperature_cfg is None:
                    print(
                        "[TEMP] ОШИБКА: секция 'temperature' не найдена в конфиге",
                        flush=True,
                    )
                    return

                # Если все уведомления отключены — ничего не делаем
                if not temperature_cfg.get("enable_all_notifications", True):
                    return

                # Конфигурация для конкретного компонента (bed/extruder)
                component_cfg = temperature_cfg.get(state.component_key, {})
                if not component_cfg:
                    print(
                        f"[TEMP] ОШИБКА: конфигурация для '{state.component_key}' не найдена",
                        flush=True,
                    )
                    return

                # Сброс состояния при изменении цели
                if target != state.last_target:
                    state.reset(target)

                # Проверка на отключение нагрева (target <= 0)
                if target <= 0:
                    if (
                        component_cfg.get("heating_off_alert", False)
                        and not state.heater_off_alerted
                    ):
                        enqueue_phrase(
                            ["нагрев", state.component_name, "отключен"],
                            self.sound_manager,
                            self.config_manager,
                        )
                        state.heater_off_alerted = True
                    return
                state.heater_off_alerted = False  # Сбрасываем флаг при наличии цели

                rounded_target = int(round(target))

                # Проверка достижения цели (±1°C)
                if (
                    not state.reached
                    and abs(temp - target) < 1.0
                    and component_cfg.get("heating_complete_alert", False)
                ):
                    words = ["нагрев", state.component_name, "завершен"]
                    if component_cfg.get("heating_complete_show_temp", False):
                        target_words = number_to_words(rounded_target)
                        degree_alias = plural_form(
                            rounded_target, ("градус", "градуса", "градусов")
                        )
                        words += ["температура"] + target_words + [degree_alias]
                    enqueue_phrase(words, self.sound_manager, self.config_manager)
                    state.reached = True

                # Порог отклонения от цели
                threshold = component_cfg.get("threshold_offset", 5)

                # Низкая температура
                if (
                    not state.low_alerted
                    and temp < target - threshold
                    and component_cfg.get("low_temperature_alert", False)
                ):
                    words = ["низкая", "температура", state.component_name]
                    if component_cfg.get("low_temperature_need_temp", False):
                        target_words = number_to_words(rounded_target)
                        degree_alias = plural_form(
                            rounded_target, ("градус", "градуса", "градусов")
                        )
                        words += ["нужно"] + target_words + [degree_alias]
                    enqueue_phrase(words, self.sound_manager, self.config_manager)
                    state.low_alerted = True

                # Высокая температура
                if (
                    not state.high_alerted
                    and temp > target + threshold
                    and component_cfg.get("high_temperature_alert", False)
                ):
                    words = ["высокая", "температура", state.component_name]
                    if component_cfg.get("high_temperature_need_temp", False):
                        target_words = number_to_words(rounded_target)
                        degree_alias = plural_form(
                            rounded_target, ("градус", "градуса", "градусов")
                        )
                        words += ["нужно"] + target_words + [degree_alias]
                    enqueue_phrase(words, self.sound_manager, self.config_manager)
                    state.high_alerted = True

        except Exception as e:
            print(
                f"[TEMP] ОШИБКА в _check_temperature для {state.component_name}: {type(e).__name__}: {e}",
                flush=True,
            )

    def reset(self):
        """Сброс состояния уведомлений"""
        with self.lock:
            self.bed_state.reset(0.0)
            self.ext_state.reset(0.0)
            self.init_complete = False
