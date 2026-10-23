# Project Foundation Kit · 0.3.0

Самостоятельный методический комплект для инженерных решений, проверки поведения, сопровождения знаний и проектирования интерфейсов. Это не архив исходного продукта, не runtime framework и не автоматический менеджер слияния. Переносится **весь этот каталог**, вместе с `skills/`, `references/`, `templates/`, `integrations/` и поставляемыми `tools/`.

## Начать за один короткий маршрут

1. Поместить **содержимое `pack/`** в `tools/project-foundation/` целевого проекта; не вложить лишний уровень `pack/`. Для существующего проекта выбрать совместимое место, не менять принятое дерево.
2. Подключить нужному клиенту: [Pi](integrations/pi.md), [Hermes](integrations/hermes.md) или [явное чтение](integrations/generic.md). Глобальные навыки/профили не менять. Один только AGENTS не означает одинаковую загрузку всеми клиентами.
3. Поручить: «Прочитай действующие правила проекта и `tools/project-foundation/skills/pf-bootstrap/SKILL.md`; разверни достаточную основу, сохрани местные решения, до записи назови конечный список путей». Без необходимости создавать всё дерево не нужно.

Одиночное копирование одного SKILL без общих ресурсов **не поддерживается**. Пакет при обычной работе read-only по договорённости, но каталог не является технической write protection. Обновление самого комплекта — отдельная работа.

## Что выбирать

| Навык | Когда | Конечный результат |
|---|---|---|
| [pf-bootstrap](skills/pf-bootstrap/SKILL.md) | Новый проект или внедрение в существующий | Достаточные адаптированные основы/инструкции/вход, профиль либо ссылки на существующий канон |
| [pf-plan](skills/pf-plan/SKILL.md) | Существенная функция, смена поведения, архитектура, эксперимент | Сценарий и минимальный исполнимый план; малому фиксу достаточно краткой задачи |
| [pf-maintain](skills/pf-maintain/SKILL.md) | Сопровождение знания/инструкций | Обновить/create/link/archive/no-impact без второго канона |
| [pf-quality](skills/pf-quality/SKILL.md) | Выбор/оценка тестов и диагностики | Достаточное evidence, безопасная изоляция и полезный/приватный вывод |
| [pf-guides](skills/pf-guides/SKILL.md) | Пользовательские руководства/переводы | Фактический сценарий, версия/ограничения, связанные языковые редакции |
| [pf-ui-design](skills/pf-ui-design/SKILL.md) | Экран, форма, диалог или переход | Ограниченное UI-решение/разрешённая дельта; состояния и честные source/rendered/interaction/behavioral observations |
| [pf-command-first](skills/pf-command-first/SKILL.md) | CLI-утилита, независимое ядро, новая оболочка или общий владелец состояния | Соразмерный прикладной контракт и план/разрешённая дельта без второй предметной логики |

Одна сессия применяет только нужные навыки. Семь навыков не семь обязательных подагентов.

## Общие источники, а не семь пересказов

- [lifecycle](references/lifecycle.md): соразмерность, пять типов изменений, знания/приёмка/finish, повтор и обновление.
- [metadata](references/metadata.md): единые типы/kind/status, паспорт, языковые связи и native-format исключения.
- [quality](references/quality.md): уровни доказательства, проверки и ограничения инструмента.

При подходящей задаче: [эволюция контрактов](references/methods/contract-evolution.md), [влияние изменения](references/methods/change-impact.md), [поведенческая регрессия](references/methods/behavior-regression.md). UI читает только [web/React](skills/pf-ui-design/references/web-react.md) или [desktop/PySide6](skills/pf-ui-design/references/desktop-pyside6.md), не оба приложения для каждого проекта.

Философия объясняет причины/компромиссы; инструкция — действия по trigger; шаблон — форму; навык — применение; заполненный принятый документ принадлежит проекту. Принятый план не реализованная функция, дата текста не проверка кода, green Markdown не product PASS.

Минимальное внедрение: [полный учебный пример CLI](references/minimal-adoption.md).
Роли основ/инструкций можно совместить в одном достаточном документе; отдельный YAML-профиль необязателен.

## Программируемое ядро и графическая оболочка

Операции и правила принадлежат Application API; CLI, GUI и MCP обращаются к нему,
не копируя логику. Простому скрипту не обязательны очередь, IPC или MCP; совместная
живая сессия требует общего владельца состояния, а не только общей библиотеки.

- [Command-first](references/architecture/command-first/README.md) — короткий вход в пять полных исходных документов; сложность A–D выбирается по гарантиям.
- [Маршрут FigCraft](skills/pf-ui-design/references/figcraft-handoff.md) — только если выбран этот редактор; [полное руководство](references/ui/figcraft/FigCraft_AI_GUI_Design_Guide_RU.md) описывает исходную редакцию 0.10.0.

Все шесть исходников сохранены побайтно, не являются действующей архитектурой
проекта и не загружаются целиком по умолчанию. Читайте нужные разделы. Дизайн не
реализация, а общий API снижает цену новой оболочки, не гарантирует отсутствие
будущей переделки. Происхождение и контрольные суммы — в [UPSTREAM](UPSTREAM.md).

## Формы по потребности

`{{field_name}}` заполняет **автор/агент**, это не универсальные переменные Obsidian Templates. Формы `.tmpl` не действующие принятые документы. В результате заполнить существенные поля, удалить author hints/неприменимые секции и пересчитать ссылки **от места результата**. Не оставлять десятки N/A или фиктивный accepted-пример.

| Семейство | Основы |
|---|---|
| Корень/профиль | [AGENTS](templates/AGENTS.md.tmpl), [project-profile](templates/project-profile.yaml.tmpl) |
| Четыре философии | [проект](templates/foundation/project-philosophy.md.tmpl), [архитектура](templates/foundation/architecture-principles.md.tmpl), [тестирование](templates/foundation/testing-strategy.md.tmpl), [наблюдаемость](templates/foundation/observability-policy.md.tmpl) |
| Практические инструкции | [разработка](templates/instructions/development.md.tmpl), [планирование](templates/instructions/planning.md.tmpl), [документация](templates/instructions/documentation.md.tmpl), [создание инструкций](templates/instructions/instruction-authoring.md.tmpl), [тесты](templates/instructions/testing.md.tmpl), [логи](templates/instructions/logging.md.tmpl), [Git](templates/instructions/git.md.tmpl), [руководства](templates/instructions/guides.md.tmpl) |
| Сценарий/план | [необязательное UI-решение](templates/documents/ui-design.md.tmpl), [история](templates/documents/user-story.md.tmpl), [сценарий](templates/documents/scenario.md.tmpl), [план функции](templates/documents/feature-plan.md.tmpl), [ADR](templates/documents/adr.md.tmpl), [ограниченное исследование](templates/documents/research.md.tmpl) |
| Текущее знание | [docs index](templates/documents/docs-index.md.tmpl), [архитектура](templates/documents/current-architecture.md.tmpl), [контракт](templates/documents/interface-contract.md.tmpl), [паспорт возможностей](templates/documents/capability-passport.md.tmpl) |
| Поддержка/закрытие | [разбор бага](templates/documents/bug-analysis.md.tmpl), [техзаметка](templates/documents/technical-note.md.tmpl), [значимая запись](templates/documents/activity-record.md.tmpl), [handoff](templates/documents/handoff.md.tmpl), [проверка/закрытие](templates/documents/verification.md.tmpl), [release notes](templates/documents/release-notes.md.tmpl), [архив](templates/documents/archive-frame.md.tmpl) |
| Руководство/новый навык/views | [формы руководств](templates/guides/), [форма проектного навыка](templates/skills/), [Obsidian](templates/obsidian/README.md) |

## Размещение в принимающем проекте

Для **нового** проекта исходная схема: `docs/README.md`, `foundation/`, `instructions/`, `architecture/`, `scenarios/`, `decisions/`, `plans/`, `research/`, `guides/ru/`, `guides/en/`, `_templates/`, `views/`, `assets/`, `archive/` под `docs/`. Создавать только наполненные нужные места. Не заводить вложенный Git или вторую копию вики. В существующем проекте фактические owners/расположение важнее схемы.

Markdown работает без открытого Obsidian. `.base` — представления над теми же документами; их синтаксическая проверка не визуальная аттестация. Встроенный Templates знает ограниченные переменные title/date/time; агентские поля цели, owner-а и проверки он сам не выводит. Скриншот реализации и концепт будущего интерфейса различаются.

## Повторное применение и обновление

Повторить bootstrap: найти существующие owners/локальные дополнения → сравнить только нужное → no-op при отсутствии дельты. Не переписывать даты, не создавать дубликаты, не заменять локальное решение шаблоном. Конфликт показать конкретно с влиянием; вопрос нужен для существенного решения, не каждой обычной строки.

Обновлять универсальный пакет отдельно от адаптированных философий/инструкций. Проверить версию источника, предложить только относящиеся изменения, сохранить местные добавления. Нет автоматической замены проектных документов и второго редактируемого instruction-канона. При переносе root пакета ресурсы навыков остаются относительными; пути целевого проекта всегда задаются явно.

## Проверка и границы

Следовать [quality](references/quality.md), [фактическому интерфейсу checker-а](tools/README.md) и проверенным командам целевого проекта. Его `--pack` по умолчанию определяет pack относительно самого файла, не cwd; проектный запуск требует явного project/corpus. Шаблон проверяется как форма, заполненный результат — по своей authoring/native грамматике. Не импортировать приложение, читать рабочие secrets/runtime данные или менять index ради проверки документов. Изоляция до первого возможного обращения к рабочим настройкам. Различать написано, выполнено, пропущено, отменено, blocked и независимо принято.

Перед завершением: актуальны затронутые знания/руководства/переводы либо обоснован no-impact; достаточные checks/limits; приёмка по [местной политике](references/lifecycle.md#владелец-приёмки-и-повторных-проверок) и разрешённое сохранение; один ясный итог и остановка. Отложенный обязательный перевод не становится актуальным от смены даты. Разрешение публиковать данные принимающего проекта не возникает автоматически от использования комплекта.

## Лицензия

Комплект распространяется под [MIT](LICENSE). При переносе и распространении сохраняйте LICENSE, [UPSTREAM](UPSTREAM.md) и [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md), включая оба MIT notices ECC/UIZZE. Выбранные процедуры адаптированы, полный ECC/runtime не включён. Лицензия комплекта сама по себе не меняет лицензию принимающего проекта или внешних материалов.
