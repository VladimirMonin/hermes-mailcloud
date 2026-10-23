# Происхождение процедур и библиотеки знаний · PFK 0.3.0

Это каноническая карта адаптации, переносимая вместе с pack. Выбранные процедуры
переведены и содержательно переработаны, **не написаны «с нуля»**. Полные сторонние
skill-пакеты, runtime, hooks, assets и настройки не включены. Собственная лицензия
[PFK MIT](LICENSE) сохраняется; относящиеся полные donor notices —
[THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md).

## ECC: фиксированная редакция

Донор: [affaan-m/ECC, commit 30b68924ae9729159f44326aa3134b1d9d67c0e2](https://github.com/affaan-m/ECC/tree/30b68924ae9729159f44326aa3134b1d9d67c0e2).
Пути получателей ниже относительно pack; AD — определения случаев разработки,
не обещание их модельного PASS. Фактическая квалификация публикуется в записи приёмки
репозитория PFK, отдельно от этого переносимого материала.

| Exact donor source | Получатель / фактическое использование | Сохранено / изменено или исключено | Случай |
|---|---|---|---|
| [skills/contract-first/SKILL.md](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/skills/contract-first/SKILL.md) | [contract-evolution](references/methods/contract-evolution.md), routes plan/quality, interface-contract form; переработка процедуры | Один канон, стороны, serialized boundary; code-first разрешён, нет обязательных schema/generator/E2E для всего | AD-02/03/05 |
| [skills/change-impact/SKILL.md](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/skills/change-impact/SKILL.md) | [change-impact](references/methods/change-impact.md); адаптация | Подтверждённые связи до и actual diff после; без полного audit и impact-report по умолчанию | AD-01/07 |
| [skills/module-regression/SKILL.md](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/skills/module-regression/SKILL.md) | change-impact и route quality; адаптация | Downstream и корректная база включая committed; без REGRESSION.md, TEST-ID квот и exit=verdict | AD-07 |
| [skills/tdd-workflow/SKILL.md](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/skills/tdd-workflow/SKILL.md) | [behavior-regression](references/methods/behavior-regression.md), testing route; адаптация | Достигнутый путь, RED/та же GREEN; нет 80%, TDD для всего, detector-а и checkpoint commits | AD-01/06 |
| [skills/ai-regression-testing/SKILL.md](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/skills/ai-regression-testing/SKILL.md) | behavior-regression/contract-evolution; критически переработанные примеры | Непустой field input и отдельный empty; обе ветки для parity. Условный assertion на пустом массиве и sandbox-only proof не перенесены | AD-03/04/05 |
| [skills/test-collaboration/SKILL.md](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/skills/test-collaboration/SKILL.md) | behavior-regression; адаптация связи requirement/test/evidence | Используется существующая verification-форма, не новый registry/runtime | AD-04/06 |
| [skills/living-docs-governance/SKILL.md](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/skills/living-docs-governance/SKILL.md) | [pf-maintain](skills/pf-maintain/SKILL.md), archive-frame; адаптация | Четыре роли, не четыре файла; rationale/replacement/revisit значимого удаления в существующей истории | AD-11/12 |
| [skills/docs-governance/SKILL.md](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/skills/docs-governance/SKILL.md) | Только сопоставление с уже существующими lifecycle/quality | Механика не смысловая приёмка; router/audit/docs-map не включены, отдельного переноса текста нет | AD-01/12 |
| [skills/frontend-design-direction/SKILL.md](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/skills/frontend-design-direction/SKILL.md) | [pf-ui-design](skills/pf-ui-design/SKILL.md), ui-design form; основной UI-донор, перевод/переработка | Задача, hierarchy, применимые states, rendered evidence; без эстетических bans, memorable-detail обязанности, JSON/Node/MCP gate | AD-08/09/10 |
| [skills/design-system/SKILL.md](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/skills/design-system/SKILL.md) | pf-ui-design, web appendix; выборочная адаптация | Reuse tokens/components; без обязательных трёх competitor sites/artifacts и score gate | AD-08 |
| [skills/frontend-a11y/SKILL.md](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/skills/frontend-a11y/SKILL.md) | [web-react](skills/pf-ui-design/references/web-react.md); выборочная адаптация вопросов | Семантика/labels/focus; учебный modal без полного trap не копируется, ARIA не переносится на Qt | AD-08/10 |
| [skills/loop-design-check/SKILL.md](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/skills/loop-design-check/SKILL.md) | Только исследовательская ссылка, ничего исполняемого/нового метода | Вопросы будущего анализа Quality Engine; его API, циклы/квоты/права не проектируются здесь | Не qualification PFK runtime |

## UI lineage и лицензии

ECC называет UI-источник community salvage: **PR #1659, linus707**. State/evidence
линия пришла через **PR #2814** из
[UIZZE anti-ui-slop, 1b74390b28c18e54a87a23e7d9171101af304ae9](https://github.com/uizze/uizze/tree/1b74390b28c18e54a87a23e7d9171101af304ae9/skills/anti-ui-slop).
PFK перерабатывает вопросы «trigger/feedback/safe next action» и разделение
rendered/untested из этой линии; поэтому сохраняются **оба MIT notices**:
ECC — Copyright (c) 2026 Affaan Mustafa; UIZZE — Copyright (c) 2026 UIZZE.

Это не адаптация canonical Anthropic frontend-design: сам ECC его не rebundle.
Платные сервисы/рекламные директивы, изображения, контакты, scripts и runtime UIZZE
не включены. Их лицензии/названия не дают прав на сторонние fonts/images/services.

ECC [check-evidence.js](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/skills/frontend-design-direction/scripts/check-evidence.js)
рассмотрен как ограниченный shape/file checker, не truth/visual evaluator. Не включён
и не требуется. [.pi adapter](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/.pi/README.md)
и [root manifest](https://github.com/affaan-m/ECC/blob/30b68924ae9729159f44326aa3134b1d9d67c0e2/package.json)
подключают не только skills: extension содержит lifecycle hooks/common-rule injection.
Ни адаптер, ни commands/extensions/config/memory не копируются и не устанавливаются.

## Полные исходные материалы · 0.3.0

Владелец предоставил эти шесть документов для открытой публикации в составе PFK.
Это оригинальная библиотека знаний, не сторонний skill-пак: имена, YAML, текст,
примеры и ссылки сохранены **побайтно**, без сокращения или исправления исходников.
К ним применима [лицензия комплекта](LICENSE); внешние источники и продукты имеют
свои условия, их код, бинарники и графические ресурсы не включены.

Пути и SHA-256 фиксируют исходную редакцию, не доказывают её поведение:

| Исходный документ / расположение | SHA-256 |
|---|---|
| [00_README.md](references/architecture/command-first/00_README.md) | `78eaccb46f521037842850e1926a222d1f3a53032dcb4384d444b1114b59be59` |
| [01_Command_First_Introduction.md](references/architecture/command-first/01_Command_First_Introduction.md) | `ebd34e1749bbc4bc47fd250bf10363bd9e97223bae762781315ed8f733f709dd` |
| [02_Command_First_Architecture_and_Contracts.md](references/architecture/command-first/02_Command_First_Architecture_and_Contracts.md) | `cc052f1190a06f7305e73fd68d5ce9a1ea84e43aa7cf9d20746019f43bf168a9` |
| [03_Command_First_Architecture_Variants.md](references/architecture/command-first/03_Command_First_Architecture_Variants.md) | `a31c2bdb7cfaa82f09ad756a5da9f5504225dce2d3702634e8487760d491542c` |
| [04_Command_First_Image_Converter_Architecture.md](references/architecture/command-first/04_Command_First_Image_Converter_Architecture.md) | `5e192de874844862046c9d737ceda63fc7cb61bc024118c63d8553dcc5ebf0b8` |
| [FigCraft_AI_GUI_Design_Guide_RU.md](references/ui/figcraft/FigCraft_AI_GUI_Design_Guide_RU.md) | `008d346da4df289f84799661bf2dee74258a02cf691484541ace819511b071cd` |

[pf-command-first](skills/pf-command-first/SKILL.md) и короткий [вход в серию](references/architecture/command-first/README.md)
выбирают нужные разделы, не загружают все статьи для каждого изменения.
[FigCraft-маршрут](skills/pf-ui-design/references/figcraft-handoff.md) расширяет существующий
UI-навык только при выборе этого редактора. Схемы операций, контракты и критерии
качества остаются у действующих владельцев, второго реестра нет.

Собственные шапки статей — описание источника, не accepted-статус документов проекта.
ImageConverter — архитектурный пример, не готовая реализация. Руководство FigCraft
отражает редакцию **0.10.0**, а его описанный эксперимент не новый runtime-тест PFK.
Свежие возможности выбранной версии проверяются при применении. Оригинальные
Obsidian-ссылки оставлены вместе с обычной Markdown-навигацией; воспроизведение
их отображения и практическое применение новой методики — отдельные проверки.

В исходной статье 04 сохранены четыре HTML-комментария со служебными метками цитат
первоначального разбора. Это неприменимые вне источника указатели, не действующие
ссылки на поставляемые ресурсы; для использования методики они не нужны. Исключение
из прежнего запрета таких меток связано только с путём и точным SHA-256 этого снимка,
не отменяет проверку секретов, личных данных и остальных файлов.

## Первичные технические ссылки, не заимствованный payload

[React useEffect](https://react.dev/reference/react/useEffect) — cleanup/out-of-order и
предпочтение принятой fetching-архитектуры; [W3C modal dialog](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)
— реальная модальность/Tab trap/initial-return focus. [Qt High DPI](https://doc.qt.io/qt-6/highdpi.html)
— coordinates/DPR; [Qt for Python threads](https://doc.qt.io/qtforpython-6/overviews/qtdoc-threads-qobject.html)
— GUI thread/affinity/queued delivery. Web и [desktop appendix](skills/pf-ui-design/references/desktop-pyside6.md)
излагают вопросы своими словами; большие тексты, код и assets этих docs не включены.
Qt for Python documentation имеет GFDL 1.3 notice, не перелицензируется MIT ECC.

[GFM §§6.3/6.5](https://github.github.com/gfm/) и
[GitHub section links](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax#section-links)
— основания bounded checker fix; это собственная реализация, не полный GFM parser.

## Обновления

Нет runtime-загрузки donor main. Новая редакция требует source/license diff только
затронутых материалов, осознанного отбора и повторения относящихся случаев. Она не
перезаписывает локальные правила/адаптации и не создаёт обязательство принять весь ECC.
