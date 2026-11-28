# LUMI — контекст для нового чата (28.11.2026)

## Источник истины
Последняя кодовая сборка: `LUMI_015_0_RELEASE_CANDIDATE.zip`. Приложить её вместе с этим файлом. Следующий этап 016.0 — закрытые испытания и запуск, затем 017.0 Analytics & Growth. Не выдавать план за реализованную функцию. Не переписывать проект с нуля.

## Продукт и неизменяемые требования
LUMI — Telegram-бот знакомств 18+ с Mini App, социально-игровой платформой, административным ботом, SQLite и Cloudflare Worker/D1. Сохранить согласованный премиальный визуальный стиль, палитру, KIGURUMI, OBSIDIAN (21 герой), EDITORIAL, нижние иконки SIGNATURE, парящие 3D-карточки главной и дуэлей. Тапалку не возвращать. Возрастные настройки не менять по просьбе владельца; остаточные риски оценить перед релизом. Не удалять существующие функции. Предоставлять полные архивы и актуальный handoff, минимум ручных действий и повторных вопросов.

## Состояние
В 015.0 накоплены изменения безопасности, авторизации, экономики, антифрода, платежей, кешей, SQLite, восстановления, модерации, медиа, контроля релизов. Предыдущий отчёт: 182 Python + 67 JS + 30 тестов инструментов = 279, 427 файлов. Это исторические результаты, не новый прогон. В текущем чате CRC исходного ZIP проверена, исходники не менялись. Внутренний файл 00_НАЧНИ_ЗДЕСЬ.md содержит исходный план запуска. В ZIP имя кириллического файла может отображаться неверно в некоторых распаковщиках.

## Запуск и блокеры
Отдельные тестовые токены и базы, не использовать исходные настройки Worker для deploy. Проверить резервирование SQLite/D1, миграции 0001–0005, TLS/CSP, реальный Telegram Android/iOS/Desktop, платежи Stars, отзыв сессий, удаление аккаунтов и сетевые сбои. Онлайн CVE-аудит, нагрузочные испытания, полное шифрование рабочей базы, независимый пентест и подпись постоянным ключом владельца ещё не подтверждены. Не публиковать до закрытия критических проблем. Секреты не помещать в архивы и чат. Не обещать фоновые работы.

## Бизнес-цель
Оценка компании более $2 млн — цель, а не текущая стоимость. Предыдущая оценка воспроизведения кода $80–150 тыс. была ориентировочной, не независимой экспертизой. Приоритет: плотность локальной аудитории, качественные знакомства, удержание, подтверждённая выручка и положительная экономика. Не добавлять все новые функции до проверки спроса.

План: 016.0 закрытая бета и выпуск; 017.0 аналитика и рост; 018.0 AI-рекомендации при подтверждённом спросе; 019.0 магазин и экономика; 020.0 сообщества и совместные активности; 021.0 локализация; 022.0 инвесторский пакет. Нумерация ориентировочная. Сценарий пользователя: 29 000 MAU, 5% платящих, $5 за месяц на платящего, условный множитель 3x: $7 250/месяц, $87 000 годового темпа, $261 000 условной оценки. Это не фактические показатели.

## Следующая работа
Использовать `LUMI_016_LAUNCH_PLAN.md` как план закрытой беты. Существующий модуль `01_BOT/lumi_operations.py` уже выводит агрегаты профилей, лайков, взаимных симпатий, Premium и ошибок; это не измерение уникальных DAU/MAU или когортного удержания. Следующим кодовым изменением проектировать минимальную приватную аналитику, с определениями событий, удалением данных и тестами. Сначала проверить схему и существующие обработчики. Не добавлять внешние трекеры без необходимости.

## 017.0 — Analytics & Growth (первый модуль)
Комплект LUMI_017_ANALYTICS_GROWTH.zip содержит неизменённый исходный ZIP 015.0, план запуска, отдельный инструмент lumi_growth.py и тесты. Запуск: python lumi_growth.py путь/к/lumi.db (на локальной копии базы). Тесты: python -m unittest -v test_lumi_growth. 4/4 новых тестов прошли на синтетической SQLite. Инструмент читает только агрегаты: уникальные просмотрщики за день/7 дней, возврат вчерашних просмотрщиков, число анкет, неотменённые покупки и Stars за 7 календарных дней UTC. browse_daily очищается через 8 дней; полноценные MAU и когортное удержание не измеряются. Сегодняшний день может быть неполным. Stars не являются чистой выручкой в долларах. Интеграции в бота, новых миграций и трекеров нет. Следующий приоритет: закрытая бета и минимальная аналитика событий с ограниченным хранением и удалением при удалении аккаунта; затем AI-рекомендации при подтверждённом спросе. Исторические результаты 279 тестов не перепроверялись.

## 017.1 — Event analytics prototype
Latest full kit: LUMI_017_1_EVENT_ANALYTICS.zip (includes unchanged 015.0 source archive). Added analytics/lumi_events.py and seven tests; 11/11 combined analytics tests passed locally. Separate SQLite store, pseudonymous HMAC identifiers, five allowed events, daily deduplication, completed-day DAU/WAU/MAU, exact-day D1/D7/D30 signup cohort return, explicit deletion and 90-day pruning. No automatic collection, scheduling, bot integration or real metrics yet. Coverage start must be verified; outages not automatically detected. Next: integrate authenticated server events, deletion and pruning into bot/Mini App with privacy review and beta testing; then evaluate AI matching. Keep design and age rules unchanged. Full functional tests and production checks remain pending.

## 017.2 — Bot activity integration
Latest full source: LUMI_017_2_BOT_ANALYTICS.zip (direct source tree, no nested archive). Modified bot.py, added lumi_analytics_live.py and six passing SQLite tests, preserved previous analytics prototypes. Default off; optional operator flag LUMI_ANALYTICS_ENABLED=1 and user /analytics_on after privacy notice; /analytics_off removes consent and activity. Random pseudonym mapped to user ID in same database; daily dedup; deletion trigger; 90-day pruning; observed 1/7/30-day counts only, not full DAU/MAU. New tables automatically created. No Mini App or signup cohort integration. aiogram absent, live bot not tested; prior full test results historical. Next: test on beta, implement matching prototype with explicit preferences and existing safety filters; preserve age settings and visual design. Do not equate metrics or projected valuation with actual business results. See 03_DOCS/ANALYTICS_017_2.md.

## 018.0 — Matching experiment
Текущий источник: LUMI_018_MATCHING_EXPERIMENT.zip. Добавлен локальный экспериментальный рейтинг в 01_BOT/lumi_matching.py и вызов в next_candidate за флагом LUMI_MATCHING_EXPERIMENT=1 (по умолчанию выключен). Семь тестов алгоритма прошли. Сохранены обязательные фильтры, возрастные ограничения, прежний режим сортировки, Premium-бонус и дизайн. Нет внешнего AI, миграций, измеренного эффекта или проверки в Telegram. Следующий приоритет — закрытая бета и проверка качества рекомендаций, затем 019.0 магазин с защищённой экономикой. Не выдавать эксперимент за доказанный рост или обученную модель.

## 019.0 — Marketplace prototype
Актуальная сборка: LUMI_019_MARKETPLACE_PROTOTYPE.zip. Добавлены автономные lumi_marketplace.py и test_marketplace.py: три демонстрационных косметических товара, серверные цены, атомарное списание тестовых кредитов, защита от дублей и повторов, откат при сбое. 8 тестов прошли, включая 32 конкурентные покупки. Нет интерфейса, авторизации, реальных платежей, выдачи косметики в приложении или миграции рабочей базы. Использовать только отдельную тестовую SQLite. Бот, Mini App, дизайн и возрастные правила не изменены. Следующий этап: интеграция каталога и инвентаря с авторизацией и удалением данных, затем платежи Stars с проверкой возвратов; после проверки спроса — 020.0 Social Ecosystem. Реальные испытания и полный регресс остаются открытыми.

## 019.1 — Marketplace integration
Latest full source: LUMI_019_1_MARKETPLACE_INTEGRATION.zip. See 03_DOCS/MARKETPLACE_019_1.md. /shop demo behind LUMI_SHOP_DEMO=1, 300 free nonmonetary credits, authenticated sender, existing eligibility, atomic inventory and deletion trigger. 14 focused tests passed; bot syntax valid. Real Telegram, full regression, actual payments, Mini App and application of cosmetic effects not tested or implemented. Age rules and design unchanged. Next: test demo on staging, then inventory visuals and validated payment flow; avoid real sales until verified.

## 019.2 — Cosmetic system (LATEST SOURCE, supersedes earlier source references)
Актуальный полный архив: LUMI_019_2_COSMETIC_SYSTEM.zip. В /shop за прежним флагом LUMI_SHOP_DEMO=1 доступны выбор одного приобретённого предмета и снятие оформления. В новых сообщениях анкет отображается декоративная текстовая метка, не графическая рамка или свечение. Проверка владения, блокировки, эпохи аккаунта и удаление выбора вместе с профилем. Новая таблица SQLite создаётся автоматически; перед обновлением сохранить базу. 31 выбранный тест прошёл, включая 3 новых теста выбора. Mini App, дизайн, возрастные ограничения, реальные платежи и EXP без изменений. Полный регресс, реальный Telegram, онлайн CVE и нагрузка не проверены. Архив требует подписи владельца. Далее: закрытая бета и оценка спроса на косметику, затем графическое оформление и интеграция Mini App либо 020.0 Social Ecosystem; не включать реальные продажи без проверки платежей. Цель $2 млн не является фактической оценкой.

## 020.0 — Social Ecosystem pilot (LATEST SOURCE)
Актуальный архив: LUMI_020_SOCIAL_ECOSYSTEM.zip. Добавлен /clubs за выключенным по умолчанию флагом LUMI_CLUBS_DEMO=1. Четыре фиксированных клуба, максимум 3 на пользователя и 200 записей членства на клуб (включая заблокированных). Только личный чат, прежняя проверка допуска, уникальная эпоха аккаунта, атомарное вступление/выход, удаление при удалении анкеты. 7 новых тестов и 17 тестов магазина прошли; синтаксис bot.py проверен. Новые таблицы создаются автоматически. Нет групповых чатов, списка участников, интерфейса Mini App, новых платежей. Дизайн и возрастные ограничения неизменны. Полный регресс, реальный Telegram, онлайн CVE и нагрузка не проверены. Перед обновлением резервная копия, подпись владельца. Следующий этап: тест пилота, затем безопасные совместные активности или 021.0 локализация. Не выдавать цель $2 млн за фактическую оценку.

## 020.1 — Social Activities (LATEST SOURCE)
Актуальный архив: LUMI_020_1_SOCIAL_ACTIVITIES.zip. В /clubs при LUMI_CLUBS_DEMO=1 добавлена кнопка активностей недели: четыре фиксированных тематических задания, личные отметки без наград, проверки выполнения или публичного списка. Проверка членства, допуска, эпохи аккаунта и недели UTC в транзакции. Повторы не создают дубликаты; отметки удаляются при выходе и удалении профиля; старые недели очищаются при следующем использовании, глобальная очистка не подключена. Новая таблица и триггер создаются автоматически. 11 тестов клубов прошли, включая 4 новых; синтаксис bot.py проверен. Полный регресс и живой Telegram не проверены. Дизайн, Mini App и возрастные настройки неизменны. Перед обновлением резервная копия, подпись владельца, закрытая бета. Далее 021.0 локализация и 022.0 инвесторский пакет; цель $2 млн не фактическая оценка.

## 021.0 — GLOBAL EXPANSION pilot (LATEST SOURCE)
Актуальный архив: LUMI_021_GLOBAL_EXPANSION.zip. Русская и английская локализация /clubs и недельных активностей по language_code Telegram; остальные языки используют русский. Переведены кнопки, статусы и ошибки. Авторизация и callback ID сохранены, флаг LUMI_CLUBS_DEMO=1 по-прежнему нужен. Новых миграций, сбора данных и изменений дизайна или возрастных правил нет. 5 тестов локализации и 11 тестов клубов прошли; синтаксис bot.py проверен. Не полная локализация: Mini App, основной бот вне клубов, пользовательский контент и ручной выбор языка не переведены. Реальный Telegram, полный регресс, CVE и нагрузка не проверены. Архив требует подписи владельца. Далее 022.0 INVESTOR READY: финансовая модель с явно обозначенными допущениями, план беты и инвестиционный пакет; цель $2 млн не фактическая оценка.


## 022.0 — INVESTOR READY (LATEST PACKAGE)
Архив LUMI_022_INVESTOR_READY.zip: исходники 021.0 без изменений, инвестиционный черновик в 03_DOCS/INVESTOR_022/INVESTOR_BRIEF.md, финансовые сценарии и план закрытой беты. Версия кода 021.0 сохранена намеренно. Исправлена кодировка имён шести документов при распаковке по исходному SHA-256-манифесту. Цель $2 млн не фактическая оценка. Реальные показатели неизвестны. Следующий шаг — staging, онлайн-аудит, закрытая бета и измерение спроса; не добавлять функции без доказательства пользы. Возрастные правила, дизайн, герои и анимации неизменны. Функциональные тесты заново не запускались; проверка манифеста и синтаксиса JS выполнена. Требуется подпись владельца.


# LUMI 023.0 — PLACES & EVENTS
Новый раздел на главной Mini App, парящая карточка, диалог с шестью демонстрационными форматами и фильтрами. Избранное в памяти страницы; не сохраняется после перезагрузки. Нет реальных анонсов, геолокации, бронирования, оплаты, серверного каталога или публичных списков. Следующий этап: модерируемый каталог реальных мест и мероприятий с городом, датой, источником, организатором и безопасной записью. Возрастные настройки и Python-бот не изменены. 69 локальных JS-тестов, включая два новых теста с имитацией DOM; визуальные испытания в Telegram не проведены. Архив требует подписи владельца.

## 023.1 — BUSINESS NETWORK (актуальная сборка)
Архив LUMI_023_1_BUSINESS_NETWORK.zip. # 023.1 BUSINESS NETWORK
Mini App: отдельная кнопка делового круга внутри Places & Events; шесть бизнес-форматов, три цели (партнёры, стартапы, опыт и навыки), десять форматов всего. Избранное остаётся в памяти страницы. Все форматы демонстрационные: нет живого каталога, профилей предпринимателей, заявок, платежей и обмена контактами. Python, возрастные ограничения и серверная авторизация не изменены. 70 JS-тестов прошли локально, включая новый тест фильтрации в имитации DOM. Реальное отображение Telegram не проверено. Перед релизом требуется подпись владельца, проверка сервера и модерируемый каталог.

## 023.2 BUSINESS IDENTITY
# 023.2 BUSINESS IDENTITY
В «Места & Ивенты» добавлен приватный черновик деловой визитки: имя/псевдоним, роль, сфера, навыки, цель. Предпросмотр через textContent, ограничение длины, проверка ролей и целей. Подбор демонстрационных форматов по выбранной цели. Черновик очищается при закрытии диалога или вручную; не отправляется и не сохраняется приложением. Публичный каталог, серверные профили и реальные мероприятия отсутствуют. Возрастные правила, бот и остальные разделы не менялись. Проверка: 72 JS теста, браузер и Telegram не проверены. Архив требует подписи владельца.

Следующий этап: серверный каталог деловых профилей с добровольной публикацией, контролем доступа и удалением. Актуальный архив LUMI_023_2_BUSINESS_IDENTITY.zip.

## 023.3 BUSINESS DISCOVERY (актуальная сборка)
Архив LUMI_023_3_BUSINESS_DISCOVERY.zip. Серверный пилот делового каталога: явное согласие, отправка на ручную модерацию, статус, удаление собственной визитки, выдача только одобренных незаблокированных профилей (до 20, фильтр цели). Telegram ID не выдаются. Действующая сессия и лимиты API переиспользуются. Миграция D1 0006_business_directory.sql обязательна до включения LUMI_BUSINESS_DIRECTORY=1; по умолчанию выключено. При редактировании одобрение сбрасывается, триггер удаляет визитку при удалении аккаунта. Ручная модерация через доверенного оператора D1 с проверкой revision, отдельного интерфейса нет. 74 JS-теста прошли, включая два новых. Реальные D1, Telegram, полный Python-регресс не проверены. Возрастные правила, графика и Python-бот неизменны. Далее: интерфейс модерации, жалобы и безопасные приглашения, затем реальные мероприятия. Архив требует подписи владельца. Цель $2 млн не фактическая оценка бизнеса.

## 023.4 BUSINESS CONNECT
Актуальный архив: LUMI_023_4_BUSINESS_CONNECT.zip. Добавлены приглашения, принятие, отказ, отмена, проверка владения и очистка при изменении визитки. 75/75 JS тестов локально. Миграция 0007, оба флага каталога и приглашений только для staging. Контакты и чат не подключены. Лимит 10/сутки сбрасывается при изменении визитки. Жалобы, блокировки пары и модерация приглашений — следующий этап. Возраст и дизайн существующих разделов не изменены. Python и реальный Telegram/D1 не проверены.

## 023.5 BUSINESS TRUST & SAFETY (актуальная сборка)
Архив LUMI_023_5_BUSINESS_TRUST_SAFETY.zip. Лимит приглашений сохраняется при редактировании визитки, добавлены жалобы и блокировки пары. Миграция 0008 обязательна. 76/76 JS тестов локально. Жалобы требуют ручной обработки, нет интерфейса разблокировки, блокировка не скрывает визитку в каталоге. Реальный Telegram/D1 и Python-регресс не проверены. Возраст и дизайн сохранены. Далее: модерация и реальные мероприятия.

## 023.6 BUSINESS MODERATION (актуальная сборка)
Архив LUMI_023_6_BUSINESS_MODERATION.zip. Серверная очередь модерации, список доверенных ID модераторов, проверка активной сессии, решения по конкретной версии визитки, защита от самопроверки и повторного решения, отметка обработки жалоб. Миграция 0009 обязательна перед включением каталога. Модерация выключена по умолчанию. GUI, журнал решений с ID модератора, автоматические санкции отсутствуют. 77 локальных JS-тестов. Возрастные правила, графика и Python-бот сохранены. Реальный Telegram/D1 и Python-регресс не проверены. Архив требует подписи владельца. Далее 023.7 LIVE EVENTS.

## 023.7 LIVE EVENTS (актуальная сборка)
Архив LUMI_023_7_LIVE_EVENTS.zip.
# 023.7 LIVE EVENTS
Пилотный каталог реальных анонсов внутри Places & Events, отделённый от демонстрационных форматов. Три события во Франкфурте, проверенные 28.11.2026 по опубликованным источникам. Франкфурт выбран как пилотный город, не запрашивается геолокация.

Источники: https://www.starthub-hessen.de/de/events/ (Frankfurt Connect 30.11.2026, Founders MIXed Space 01.12.2026); https://www.ba-frm.de/veranstaltung/matching-07-12-2026/ (Matching 07.12.2026).

Каталог редактируется вручную в public/live-events.js. Только HTTPS и разрешённые домены; ссылки открываются отдельно без referrer. Фильтры города и формата, сортировка по дате, скрытие прошедших дней по Europe/Berlin. Доступность мест и отмены не проверяются автоматически. Регистрация у организатора, не в LUMI. Новых миграций нет. Возраст, бот и существующие разделы не изменены. 80/80 JS тестов локально; браузер, Telegram, Cloudflare и Python-регресс не проверены. Архив требует подписи владельца. Следующий этап: модерируемое создание мероприятий организаторами.

## 023.8 EVENT ORGANIZER
Актуальный архив: LUMI_023_8_EVENT_ORGANIZER.zip.

# 023.8 EVENT ORGANIZER

Пилот: Mini App → Места & Ивенты → Создать событие. Название, город, место, дата/время, формат, описание и согласие. Местное время устройства переводится в Unix timestamp; проверяйте часовой пояс места. События сообщества доступны только авторизованным участникам после ручного одобрения. Организатор может отменить собственное событие. Редактирование не предусмотрено: отмена и новая заявка. Публичный список не содержит Telegram ID.

## Включение на тестовом окружении
1. Сделать резервную копию D1 и применить миграции по порядку, включая `0010_event_organizer.sql`.
2. Установить `LUMI_EVENT_ORGANIZER=1`, `LUMI_BUSINESS_MODERATION=1` и настроить `LUMI_BUSINESS_MODERATOR_IDS` (доверенные Telegram ID). Не размещать секреты в архиве. По умолчанию API отключён.
3. Модератор через существующую авторизованную сессию: GET `/api/events/moderation/list`, POST `/api/events/moderation/decide` с `{id,state}` (approved/rejected). Заголовок `x-lumi-session`. Нет отдельной визуальной панели; самоподтверждение запрещено.
4. Проверить создание, одобрение, отмену, видимость и часовые пояса в Telegram staging.

Лимиты: 5 заявок за 24 часа, 20 активных будущих событий, выдача до 50, планирование до 366 дней. Удаление аккаунта удаляет мероприятия через триггер. Нет автоматического подтверждения личности организатора, регистрации участников, оплаты, уведомлений, пагинации или автоматической очистки старых мероприятий. Ручная модерация должна проверять безопасность места и достоверность объявления. Возрастные правила и Python-бот не изменены.

Проверено локально: 81/81 JavaScript-тест, включая интеграционный тест на SQLite с имитацией D1. Python-регресс, реальный Telegram, Cloudflare и визуальные испытания не проводились.

Следующий этап: 023.9 EVENT REGISTRATION — запись, отмена записи, лимит мест, защита от дублей и контроль доступа. Затем 024.0 BUSINESS ECOSYSTEM — полный регресс. Сохранить дизайн, героев, возрастные ограничения и все существующие функции.

## 023.8.1 — EDITORIAL TYPOGRAPHY
Только типографика Places & Events: крупные жирные заголовки, карточки, читаемые подписи и кнопки. Дизайн остальных разделов, логика, палитра и возрастные настройки сохранены. 81/81 JS тестов, 493 файла по манифесту, 46 JS файлов проверены на синтаксис. Визуальный тест Telegram не выполнен. Следующий этап 023.9 EVENT REGISTRATION.


## 023.8.2 — INTERACTIVE 3D EDITORIAL
Актуальный архив: LUMI_023_8_2_INTERACTIVE_EDITORIAL.zip.

# 023.8.2 INTERACTIVE 3D EDITORIAL
Discover / Places & Events only. All result cards, the featured business card and collapsible section headers receive responsive perspective tilt and pointer-following highlight. One frame per update; angle up to 8 degrees per axis. Vertical scrolling remains native (pan-y). Drag suppresses pointer activation; keyboard activation is unaffected. Reduced-motion mode disables effects. Only the featured business card floats continuously. Three lightweight local vector UI illustrations (coffee, startup pitch, city) decorate selected demonstration formats, not actual event photos. Forms remain stable. Existing backend, age rules, palette, hero art, and other sections unchanged. No migration. 84 JavaScript tests including three new motion tests. Browser preview was blocked by the test environment (ERR_BLOCKED_BY_ADMINISTRATOR); visual verification, actual touch gestures in Telegram, Python regression and performance measurements remain outstanding. Archive requires owner's signature. Next: 023.9 event registration; 024.0 business ecosystem.

Пользователь просит сохранять крупную жирную типографику, подвижные UX/UI карточки как в Дуэлях и использовать иллюстрации выборочно, без перегруза. Не усиливать возрастные ограничения.

## 023.8.3
# 023.8.3 — Discover / original editorial style
Split composition based on user screenshot of Duel/Games. Home and section entries have text left, single violet faceted object right; existing touch tilt, reduced motion and click suppression retained. Three original SVG objects added; no photos or remote assets. No backend changes. Browser/Telegram visual validation outstanding. Next: event registration 023.9.


## 023.9 EVENT REGISTRATION
# 023.9 EVENT REGISTRATION
Apply migration 0011_event_registration.sql before enabling LUMI_EVENT_REGISTRATION=1 alongside LUMI_EVENT_ORGANIZER=1. Both remain disabled by default. Existing events default to 20 seats; organizers should verify this before enabling. New events accept 1–500 seats. Free registration only, explicit consent, atomic capacity check and unique event/user key. Users can cancel their own registration, view upcoming registrations including cancelled events. No attendee identities exposed. Account/event deletion triggers remove registrations; scheduled cleanup removes registrations 30 days after start when both flags are enabled. Cancelled events retain registrations until cleanup so participants see cancellation. No automatic notifications, payments, waitlists, attendance verification or external event booking. Capacity input is visible even if registration is disabled; legacy submit uses default capacity in that case. Existing visual styles reused. Local SQLite integration tests; no Cloudflare concurrency/load or real Telegram test. Python unchanged and not retested.


# 024.0 BUSINESS ECOSYSTEM — local integration release

Discover now has four quick navigation buttons: Afisha, People, My registrations, Create. They open the appropriate existing section and focus/scroll to the relevant control without submitting forms or making automatic requests. Existing signature cards, motion and typography remain. Clarified private preview versus consensual publishing, and external versus community registration.

Regression: 86 JS tests, 228 bot Python tests, 30 tool tests passed locally. Fixed eight marketplace test setup errors caused by the legacy test-only global SQLite connection patch by explicitly selecting the standard SQLite connection factory in marketplace tests. No production Python changes.

## Staging checklist
- Back up D1; apply migrations in order through 0011. Verify existing capacity values.
- Configure existing business directory/connect/moderation and event organizer/registration feature flags and authorized moderator IDs per earlier docs. Leave disabled until staging passes.
- Test two separate Telegram accounts and a separate moderator: publish/reject/withdraw business card; invite/accept/report/block; create/approve/cancel event; join/leave/full event; deletion and blocked access.
- Verify real device scrolling, reduced motion, layout at narrow widths, keyboard focus, date/time zone and cancellation visibility. Verify real D1 concurrency and live deployment.
- Review organizer legitimacy, event location safety and privacy before publishing. External events remain manually curated; no payment or notifications.
- Online dependency audit, owner signature and deployment approval remain outstanding. Not a production-approved release. No new migration or age-setting change.

## 025.0 CITY EXPERIENCE
- One bold dimensional heading, regular flat subtitle in Discover.
- Four city format collections with external Google Maps search links; no verified venue catalog, bookings, location access or new backend. Existing interactive motion reused.
- 87/87 JS tests passed; visual Telegram and Python regression not rerun.

## 025.1 CITY DISCOVERY
Six source-linked locations in Frankfurt and Berlin, city/category filters and in-memory favorites. No location tracking or persistent favorites; no restaurant booking or live opening hours. Existing signature cards and typography retained. 88 JS tests passed; Telegram visual and Python regression not rerun. Next: curated venue partnerships.

## 025.2 LUMI PARTNERS
# 025.2 LUMI PARTNERS
Editorial partner catalog, empty by default. No actual partner agreements or discounts. To publish, obtain written approval and verify terms, city, HTTPS official source and validity interval (ISO 8601 with offset); add a record to offers in public/city-partners.js with id, name, terms, city, status confirmed, start, end, url. Remove revoked offers and redeploy promptly. No payment, coupon redemption, tracking, server admin or automatic revocation. Client filtering is display logic, not authorization. Commercial model for future pilot: fixed placement fee or commission on independently verified redemptions, with advertising disclosure. No revenue assumed. Existing design and age settings unchanged. Test actual Telegram before release.


# 025.3 PRIVILEGES
Migration 0012_partner_privileges.sql; LUMI_PRIVILEGES=1 only after signed partner terms and migration. Default off. Operator inserts confirmed offers manually into partner_privileges, enabled defaults to 0. merchant_id must be the authenticated merchant Telegram account ID. Times are Unix seconds. IDs ASCII letters/digits/_/- (1–64). No seeded offers. One random code per account per offer, idempotent claim; merchant API POST /api/privileges/redeem with {code,consent:true} requires merchant session and atomically marks once. No merchant UI, no payments, no overall inventory cap. Account deletion removes codes and disables merchant offers; deletion/recreation may allow reissue, so do not enable high-value offers. Codes are bearer secrets, display only at venue; do not log. No production deployment or mobile visual verification. Existing static city offers independent. Existing age rules untouched.
# 025.4 Partner Studio
Requires migration 0012 already shipped. No new migration. Set LUMI_PRIVILEGES=1 and LUMI_PARTNER_STUDIO=1 only after owner verifies signed partners; set LUMI_PARTNER_IDS to comma-separated verified Telegram user IDs. Studio allows creation of disabled drafts, listing own offers with aggregate issued/redeemed counts, and pausing. Owner must verify terms and explicitly enable drafts in D1; no self-publication. Pausing disables unused codes; owner must resolve obligations before pausing. Existing redemption endpoint retains merchant ownership checks. Maximum 20 unexpired offers per merchant, 50 listed, maximum horizon 366 days. Dates interpreted in device timezone. No payments, contracts, admin approval UI, global inventory limit or real Telegram test. Existing deletion behavior still permits re-claim after account recreation. Statistics reflect currently retained code records, not lifetime totals. No independent security audit. Existing design and age rules unchanged.


# 025.5 CITY MATCH
Local, deterministic place suggestions from the existing six-place editorial catalog. Select city and two interests manually. Shared interest scores 2; either interest scores 1. No matches produce an explicit empty state. No inferred preferences, profile matching, network requests, location access, or persistence. Closing the section or dialog resets the form. External source links require a user click. Existing signature card motion is reused. No server migration or bot changes. 92 JS tests passed; visual Telegram and Python regression not run. Catalog coverage and availability remain limited; no booking or live hours.

## 025.6 DATE PLANNER
- Local private meeting draft: city, catalog place, future date/time Europe/Berlin, copy invitation manually. No server invite or tracked acceptance; no reservation.
- Existing style and age settings unchanged; no migration. 94/94 JS tests passed. Telegram visual and Python regression not run.
- Next: authenticated mutual invitation only after verifying dating match and block integration; avoid mixing business directory with dating.


# 025.7 DATE CONNECT
Apply migration 0013_date_connect.sql before enabling LUMI_DATE_CONNECT=1. Default disabled. Recipient creates a random single-use 128-bit code valid for 10 minutes and shares it privately. The sender submits a public catalog place and future Berlin-local date/time. Recipient explicitly accepts or declines; either may cancel. No Telegram identifiers are returned. Five invitations per sender per 24 hours; account deletion removes plans and keys; scheduled cleanup removes expired keys and plans older than 90 days while enabled. No booking, notifications, romantic match integration or bot-side personal block synchronization. Global bans checked. Codes are bearer secrets: share only with intended person. No identity display in plan list. Existing style reused. Local SQLite integration and JS regression 95/95; no deployed Telegram/D1 or Python regression.

# 025.8 LUMI MOMENTS
Private chronological agenda in Places & Events: confirmed future dates and active joined community events, filters, manual refresh, Berlin time. Uses existing authenticated list APIs; no new migration, persistent client storage, or automatic reminders. Clears on section/dialog close and discards late results; partial source failures explicitly shown. Existing API lists capped at 50 each; not an exhaustive calendar. Corrected missing registration actions in inline event API allowlist and refreshed CSP hash. Existing age rules and design unchanged. 97 JS tests passed; no production Telegram/D1, mobile visual, or Python regression. Existing features default off; enable only after previous migration and rollout requirements. Next priority: safety integration and real staging smoke tests before additional expansion.
# 025.9 CITY EXPERIENCE FINAL
- Quick navigation to city discovery and personal moments; existing signature cards and typography retained.
- DATE CONNECT has participant-only, explicit block action. Blocking cancels active plans in both directions, hides pair plans and prevents new invites either way; no user IDs exposed. Cancelling is permitted even if the other party is globally banned. Deletion removes block records. No unblock UI or synchronization with bot/business blocks; deleting/recreating an account may remove protection. No claims of physical safety.
- Apply migration 0014_date_safety.sql before enabling DATE CONNECT. Keep default-off flags and prior rollout requirements. No new payments or notifications. Codes remain private bearer secrets. First meetings in public places advised.
- Local regression: 97 JS, 228 Python (24 subtests), 30 tool tests passed. No live Telegram, Cloudflare D1, visual device testing or online dependency audit. Owner approval/signature outstanding. Not production approved.


# 026.0 — LUMI EXPERIENCE

First design-system pass: a separate CSS layer after existing styles; shared focus, touch size, support text and transition tokens. City controls receive a 44px minimum height, disabled styling and navigation hover/press states. Secondary city copy is flat and normal weight. Four main views and city dialog use short opacity-only entrances when reduced motion is not requested. Original 3D geometry, assets, gestures, bot, API and age settings remain unchanged. No new dependencies or migrations.

Verification: 98/98 Node tests (one new static design-contract test). No device/browser visual test, performance benchmark, live Telegram/Cloudflare or Python rerun. Focus and animation rendering still require device verification. Next: device testing and measured loading optimization.


# 026.1 — LUMI FLUID
Decorative infinite animations on existing home, duel and business cards pause outside the viewport (32 px margin) via IntersectionObserver. Background visibility is initialized immediately and duel animation loops also pause in hidden tabs. Older WebViews without IntersectionObserver retain background-only behavior. No polling, asset changes, new dependencies or migrations. Pointer tilt, geometry, typography, bot and age rules unchanged. This is a targeted animation optimization, not a measured loading-speed or battery improvement. The 7.3 MB mascot GLB remains unchanged; existing viewer already gates frame rendering by visibility. Actual mobile FPS, battery, network timing and Telegram rendering require staging measurement.

Verification: 100/100 Node tests passed. Python and real-device benchmarks not run. Next: staging performance and asset loading measurements.
# 026.2 INSTANT
- Welcome poster remains immediately available; renderer is dynamically loaded after 650 ms only when welcome is visible, motion is enabled and saveData is off.
- Closing welcome or hiding the document cancels the timer and aborts ongoing model fetch; completed geometry is cached in memory. Renderer script itself may finish downloading after cancellation, but cannot mount stale content.
- Kigurumi model unchanged (7,637,356 bytes). Fixed scope of lazy drop renderer loader shared by hero gallery.
- No backend or age changes. 103 Node tests pass, including mocked cancellation tests; no mobile browser timings or Python rerun. Actual network bytes saved depend on browser/cache and dismissal time.

## 026.3 MICROINTERACTIONS
Scoped native Telegram selection feedback and press states for places and tabs; 100 ms debounce; existing tilt and typography preserved. 106 JavaScript tests passed. No backend or age changes. Hardware and Python regression not tested. Next: 026.4 navigation and recovery UX.

## 026.4 SEAMLESS
# 026.4 — SEAMLESS
Telegram native BackButton closes the last opened dialog before returning from a non-home tab to Home. On Home and during welcome it is hidden. Existing dialog close handlers and tab click handlers are reused; no browser history or persistent state is changed. Unsupported SDKs retain existing navigation. MutationObserver tracks dialog visibility and current tab. Mock tests cover return, nested dialogs, welcome and absent SDK. Real Telegram and Python regression not run. No backend, design assets, age settings, migrations or dependencies changed.

109/109 Node tests passed. Next: staging readiness and real-device navigation testing.
# 026.5 RESILIENCE
- Общий JSON API: дедлайн 10 секунд на запрос и чтение ответа; AbortController при наличии. Без автоматического повтора операций записи. Таймаут не гарантирует отмену операции на сервере: обновить данные перед повтором.
- При 401 сбрасывается кеш обещания сессии, следующий ручной запрос получает новую сессию.
- Системные offline/online события отображают ненавязчивое сообщение; online не гарантирует доступность сервера. Локальные разделы не блокируются.
- CSP хеш обновлён. 112 JavaScript-тестов прошли. Реальный Telegram, мобильные устройства, Python и Cloudflare не проверены. Возрастные правила, графика и серверная логика не менялись.
- Следующий этап: 026.6 RELEASE READY.

# 026.6 RELEASE READY
Актуальный архив: LUMI_026_6_RELEASE_READY.zip. Документация и версия обновлены; код неизменен. 370 локальных тестов (112 JS, 228 Python, 30 инструменты) прошли; offline gate код 2, не разрешение релиза. aiogram отсутствует; онлайн CVE, Telegram/D1, мобильные замеры, нагрузка, TLS, пентест и подпись владельца не проверены. Миграции 0001–0014, staging отдельно. См. 03_DOCS/RELEASE_026_6.md. Далее закрытая бета.
