from shared_utils import enqueue_phrase
from ws_client import CompletionState

class PrintStatusNotifier:
    """
    Отвечает за уведомления о статусе печати:
    начало, пауза, возобновление, завершение, отмена.
    """

    def __init__(self, config_manager, sound_manager, ws, progress_notifier=None):
        self.config_manager = config_manager
        self.sound_manager = sound_manager
        self.ws = ws
        self.print_started = False
        self.cancel_alert_sent = False
        self.complete_alert_sent = False
        self.last_print_state = "—"
        # Сохраняем ссылку на ProgressNotifier для сброса его состояния
        self.progress_notifier = progress_notifier

    def check(self, status):
        """
        Проверяет статус печати и выполняет озвучку в зависимости от событий
        начала, паузы, возобновления, завершения или отмены печати.
        Все настройки читаются из конфигурации print_status.notifications.

        Args:
            status: объект статуса принтера
        """
        config = self.config_manager.get_config_section("print_status").get(
            "notifications", {}
        )

        state = status.print_state
        completion = status.completion_state

        # Обработка начала печати (только первый старт, не после паузы)
        if state == "printing":
            if not self.print_started:
                if config.get("started", True):
                    enqueue_phrase(
                        ["начало", "печати"], self.sound_manager, self.config_manager
                    )
                # Сброс флага расчётного времени при старте новой печати
                if self.progress_notifier is not None:
                    self.progress_notifier.reset_initial_estimate_flag()
                self.print_started = True
                self.cancel_alert_sent = False
                self.complete_alert_sent = False

        # Обработка завершения
        elif completion == CompletionState.COMPLETE.value:
            if not self.complete_alert_sent and config.get("completed", True):
                enqueue_phrase(
                    ["печать", "завершена"], self.sound_manager, self.config_manager
                )
                self.complete_alert_sent = True
            self.print_started = False

        # Обработка отмены
        elif completion == CompletionState.CANCELLED.value:
            if not self.cancel_alert_sent and config.get("cancelled", True):
                enqueue_phrase(
                    ["отмена", "печати"], self.sound_manager, self.config_manager
                )
                self.cancel_alert_sent = True
            self.print_started = False

        # Обработка смены состояний (пауза/возобновление)
        if state != self.last_print_state:
            if state == "paused" and config.get("paused", True):
                enqueue_phrase(
                    ["пауза", "печати"], self.sound_manager, self.config_manager
                )
            elif (
                state == "printing"
                and self.last_print_state == "paused"
                and config.get("resumed", True)
            ):
                enqueue_phrase(
                    ["возобновление", "печати"], self.sound_manager, self.config_manager
                )

        self.last_print_state = state

    def reset(self):
        """Сброс состояния уведомлений"""
        self.print_started = False
        self.cancel_alert_sent = False
        self.complete_alert_sent = False
        self.last_print_state = "—"
