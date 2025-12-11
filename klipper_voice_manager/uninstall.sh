#!/bin/bash

echo "Удаление Klipper Voice Notification Service..."

SERVICE_NAME="klipper_voice_notify.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"

# 1. Однократный запрос пароля sudo в начале
if [ "$EUID" -ne 0 ]; then
    echo "Для удаления сервиса требуется доступ sudo."
    echo "Введите пароль (будет использован для всех операций):"
    sudo -v
    if [ $? -ne 0 ]; then
        echo "Ошибка: неверный пароль или отказано в доступе."
        exit 1
    fi
fi

# 2. Проверка существования сервиса
if [ ! -f "$SERVICE_PATH" ]; then
    echo "Сервис $SERVICE_NAME не найден в $SERVICE_PATH"
    
    # Дополнительная проверка через systemctl
    if ! systemctl list-unit-files | grep -q "$SERVICE_NAME"; then
        echo "Сервис не обнаружен в системе. Выход."
        exit 0
    fi
fi

# 3. Остановка сервиса (если запущен)
if systemctl is-active "$SERVICE_NAME" > /dev/null 2>&1; then
    echo "Останавливаю сервис..."
    sudo systemctl stop "$SERVICE_NAME"
else
    echo "Сервис не запущен"
fi

# 4. Отключение автозапуска
echo "Отключаю автозапуск..."
sudo systemctl disable "$SERVICE_NAME"

# 5. Удаление файла сервиса
echo "Удаляю файл сервиса: $SERVICE_PATH"
sudo rm -f "$SERVICE_PATH"

# 6. Перезагрузка systemd
echo "Перезагружаю systemd..."
sudo systemctl daemon-reload

# 7. Проверка удаления
if ! systemctl list-unit-files | grep -q "$SERVICE_NAME"; then
    echo "✅ Сервис успешно удалён из системы"
else
    echo "⚠  Сервис всё ещё присутствует в конфигурации systemd"
    echo "Попробуйте: sudo systemctl reset-failed"
    exit 1
fi

# 8. Опциональное удаление из группы audio
echo ""
echo "Удалить текущего пользователя из группы 'audio'? (y/n)"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    CURRENT_USER=$(whoami)
    echo "Удаляю $CURRENT_USER из группы audio..."
    sudo gpasswd -d "$CURRENT_USER" audio
    echo "Пользователь $CURRENT_USER удалён из группы audio"
else
    echo "Сохранение пользователя в группе audio"
fi

# 9. Итоговые рекомендации
echo ""
echo "=========================================="
echo "✅ Удаление завершено!"
echo "=========================================="
echo ""
echo "Рекомендации:"
echo "1. Перезагрузите систему: sudo reboot"
echo "2. Проверьте отсутствие сервиса:"
echo "   systemctl status $SERVICE_NAME"
echo "   ls $SERVICE_PATH"
echo "3. Для удаления Python-пакетов выполните:"
echo "   sudo pip3 uninstall pygame websocket-client pyyaml numpy watchdog"
