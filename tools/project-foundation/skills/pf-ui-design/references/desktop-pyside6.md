# Приложение: desktop / PySide6

Читать только для desktop-задачи с [UI-навыком](../SKILL.md). Это самостоятельная
платформенная адаптация PFK, не готовый Qt-навык ECC. Web evidence не native proof.

## Окно, масштаб и клавиатура

Найти принятые widgets/actions/theme/tokens и layout. Выбрать из требований размеры
окна/минимальный размер, панели, длинные подписи и существенные scale/DPR условия.
Qt использует device-independent coordinates; geometry и raw image pixels не одно
и то же. Browser viewport не описывает native среду. В наблюдении указать целевую
ОС, редакцию приложения, window geometry и существенный scale/DPR, не полный env dump.
Первичный справочник: [Qt High DPI](https://doc.qt.io/qt-6/highdpi.html).

Проверить доступность главного действия после resize, wrap/scroll, tab order,
shortcuts, видимый focus, подписи и возврат focus после диалога по архитектуре
приложения. Использовать native actions/widgets; **не переносить ARIA в Qt**.
Screenshot не подтверждает keyboard и screen reader. Непроверенная accessibility
граница остаётся непроверенной; отсутствие инструмента не делает её неприменимой.

## Операции и native lifecycle

Найти существующий operation owner и настоящий путь signals/slots. QWidget обновляется
только в GUI/main thread. Учесть QObject affinity, queued delivery и lifetime;
успешный import не доказывает безопасное соединение worker → UI. Первичный источник:
[Qt for Python — Threads and QObjects](https://doc.qt.io/qtforpython-6/overviews/qtdoc-threads-qobject.html).
Документация Qt здесь только ссылка/собственное изложение, не включённый GFDL payload.

Для затронутой длительной операции проверить:
- окно остаётся отзывчивым, начало/прогресс и terminal outcome различимы;
- отмена использует существующую семантику owner-а, скрытие окна не выдаётся за cancel;
- retry/следующая операция не дублирует применение и остаётся возможной после отказа;
- A→B, ответ B и поздний A: старый callback не заменяет текущий B;
- закрытие поверхности во время работы не обновляет уничтоженный widget;
- свои connections/subscriptions/workers/resources освобождаются и при partial setup,
  по действующему lifecycle, а не новым manager-ом в UI.

Это выбор рисков задачи, не обязательный полный ресурсный audit для смены подписи.
Для детерминированного behavior-теста допустим synthetic источник внешних событий,
если настоящее применение результата/owner остаются subject. Он не доказывает внешний
сервис или native event loop, если они заменены.

## Доказательства и ограниченный выход

Разделить source (реальные owners/wiring), rendered (фактическое окно/условия),
interaction (resize/keyboard/focus/close/cancel), behavioral (результат/stale/readback).
HTML-макет может помочь проектированию, но не доказывает Qt-layout/диалоги/DPR.
Mock, импорт модуля и screenshot не заменяют native lifecycle/actions.

Без готового разрешённого GUI-входа дать полезный source/design результат и назвать
native/visual/interaction NOT_RUN, конкретный сценарий и условия следующей проверки.
Не устанавливать Qt или demo-продукт и не запускать частное приложение ради отчёта.
Приватность/cleanup принадлежат [quality](../../../references/quality.md), не второму
журналу UI. Адаптация и первичные references — [UPSTREAM](../../../UPSTREAM.md).
