# Сценарии ПДД

Этот документ описывает контракт между картой, сервером и будущим клиентским
интерфейсом сценариев. Сценарий начинается в зоне ожидания перед перекрёстком,
а заканчивается после того, как каждый участник достиг своего выезда и сервер
оценил его действия.

Финальные координаты и идентификаторы появятся после обновления карты. До этого
сервер может разрабатывать жизненный цикл сценария на временной конфигурации,
не меняя формат.

Текущий серверный smoke-сценарий называется `priority-test`. Он использует
временные координаты текущей карты, рассчитан на двух игроков и уже проверяет
переход `world:main -> scenario:1`, общий `scene_start`, раздельные snapshot и
прибытие в индивидуальные финишные зоны и серверный расчёт XP. Эти координаты
не являются финальным контентом и будут заменены после импорта новой карты.

Сценарное состояние находится в [`server/scenarios.py`](server/scenarios.py), а
сетевое orchestration сценариев вынесено в
[`server/scenario_handlers.py`](server/scenario_handlers.py). WebSocket endpoint
и lifecycle v2 вынесены в
[`server/websocket_handlers.py`](server/websocket_handlers.py); в
[`server/app.py`](server/app.py) осталось связывание endpoint-ов и зависимостей.
Геометрические проверки движения находятся в
[`server/scenario_rules.py`](server/scenario_rules.py). Для сценария без
`rule_config` проверки отключены до появления логических данных карты.

## Жизненный цикл

```text
world:main
  -> scenario_waiting
  -> scenario_assigned
  -> scene_prepare
  -> scene_ready от всех участников
  -> scene_start с общим startTick
  -> running
  -> индивидуальные финиши
  -> scenario_result
  -> через 5 секунд scene_prepare для world:main
  -> возврат в world:main
```

Состояния экземпляра:

| Состояние | Значение |
| --- | --- |
| `waiting` | Игроки собираются в зоне ожидания общего мира |
| `loading` | Участники выбраны, сервер готовит экземпляр |
| `countdown` | Все ресурсы готовы, идёт отсчёт до общего старта |
| `running` | Участники выполняют свои маршруты |
| `finished` | Все участники достигли назначенных выездов |
| `cancelled` | Сценарий отменён из-за выхода игрока или технической ошибки |

Техническая отмена не считается нарушением и не уменьшает опыт.

## Что ожидает сервер от карты

Карта должна отдавать отдельные JSON-данные для серверной логики. GLB-модель
сама по себе не является описанием правил.

Для каждого сценария нужны:

- стабильный `scenarioId`;
- `mapId` и версия контента;
- зона регистрации перед перекрёстком;
- минимальное и максимальное число участников;
- роли;
- стартовая точка каждой роли;
- целевая зона каждой роли после перекрёстка;
- направленные полосы и их ширина;
- стоп-линии и осевая разметка;
- границы перекрёстка;
- разрешённые маршруты;
- главная и второстепенная дороги;
- ограничения скорости;
- идентификаторы объектов, которые используются правилами.

Координаты должны быть в тех же осях и единицах, что и физика сервера:
`x/z` в метрах, `heading` в радианах, скорость в м/с.

## Формат сценария

Ниже полный пример целевого JSON-объекта. Координаты условные и будут заменены
после готовности карты.

```json
{
  "id": "priority-crossroad-01",
  "version": 1,
  "mapId": "compact-reference",
  "title": "Главная дорога и поворот",
  "description": "Участники проезжают перекресток по правилам приоритета.",
  "enabled": true,
  "minPlayers": 2,
  "maxPlayers": 3,
  "timeLimitSeconds": 60,
  "waitingZone": {
    "id": "junction-01-waiting",
    "shape": "box",
    "minX": 56.0,
    "maxX": 61.0,
    "minZ": 36.0,
    "maxZ": 44.0,
    "requireStop": true,
    "maxSpeed": 0.5
  },
  "intersection": {
    "id": "junction-01",
    "bounds": {
      "minX": 48.0,
      "maxX": 68.0,
      "minZ": 10.0,
      "maxZ": 30.0
    },
    "lanes": [
      {
        "id": "north-main-in",
        "direction": "south",
        "width": 3.2,
        "centerline": [[58.5, 40.0], [58.5, 30.0], [58.5, 20.0]],
        "priority": "main",
        "allowedRoutes": ["north-to-south", "north-to-east"]
      },
      {
        "id": "east-secondary-in",
        "direction": "west",
        "width": 3.2,
        "centerline": [[72.0, 20.0], [68.0, 20.0], [58.5, 20.0]],
        "priority": "secondary",
        "allowedRoutes": ["east-to-north"]
      }
    ],
    "stopLines": [
      {
        "id": "east-secondary-stop",
        "from": [68.0, 18.4],
        "to": [68.0, 21.6],
        "allowedDirection": "west",
        "laneIds": ["east-secondary-in"]
      }
    ],
    "conflictAreas": [
      {
        "id": "junction-01-conflict",
        "polygon": [[54.0, 16.0], [63.0, 16.0], [63.0, 24.0], [54.0, 24.0]]
      }
    ]
  },
  "roles": [
    {
      "id": "main-straight",
      "title": "Главная дорога: прямо",
      "vehicleType": "car",
      "spawn": {
        "x": 58.5,
        "z": 36.0,
        "heading": 3.141592653589793
      },
      "route": {
        "id": "north-to-south",
        "fromLaneId": "north-main-in",
        "toLaneId": "south-main-out",
        "destination": {
          "id": "south-main-exit",
          "shape": "box",
          "minX": 56.8,
          "maxX": 60.2,
          "minZ": 4.0,
          "maxZ": 10.0,
          "requireStop": true,
          "maxSpeed": 0.5
        }
      },
      "rules": ["keep_lane", "speed_limit", "complete_route"]
    },
    {
      "id": "secondary-turn",
      "title": "Второстепенная дорога: уступить и повернуть",
      "vehicleType": "car",
      "spawn": {
        "x": 72.0,
        "z": 20.0,
        "heading": -1.5707963267948966
      },
      "route": {
        "id": "east-to-north",
        "fromLaneId": "east-secondary-in",
        "toLaneId": "north-main-out",
        "destination": {
          "id": "north-main-exit",
          "shape": "box",
          "minX": 62.0,
          "maxX": 68.0,
          "minZ": 28.0,
          "maxZ": 32.0,
          "requireStop": true,
          "maxSpeed": 0.5
        }
      },
      "rules": ["yield_to_main", "keep_lane", "speed_limit", "complete_route"]
    }
  ],
  "rules": {
    "speedLimits": [
      {
        "id": "junction-01-limit",
        "area": "junction-01",
        "maxSpeed": 8.3333333333
      }
    ],
    "definitions": {
      "keep_lane": {
        "severity": "violation",
        "xp": 0,
        "message": "Не пересекайте границы своей полосы."
      },
      "yield_to_main": {
        "severity": "violation",
        "xp": 0,
        "message": "Уступите автомобилю на главной дороге."
      },
      "speed_limit": {
        "severity": "violation",
        "xp": 0,
        "message": "Снизьте скорость перед перекрестком."
      },
      "complete_route": {
        "severity": "success",
        "xp": 100,
        "message": "Маршрут завершён."
      }
    }
  },
  "experience": {
    "enabled": true,
    "baseXp": 100,
    "completionXp": 100,
    "perfectBonusXp": 50,
    "participationXp": 10,
    "violationPenalties": {
      "keep_lane": 25,
      "yield_to_main": 40,
      "speed_limit": 15
    },
    "minimumXp": 0,
    "maximumXp": 150
  }
}
```

## Правила опыта

Опыт рассчитывается только сервером после завершения участником маршрута.
Клиент не передаёт `xp` и не может изменить результат.

Базовая формула:

```text
xp = participationXp
if маршрут завершён:
    xp += completionXp
if нарушений нет:
    xp += perfectBonusXp
xp -= сумма штрафов за уникальные нарушения
xp ограничивается [minimumXp, maximumXp]
```

Каждое нарушение имеет стабильный `eventId` и учитывается один раз. Повторное
сообщение о том же событии не должно повторно уменьшать опыт.

Пример:

```text
10 за участие
+100 за завершение
+50 за чистый проезд
-15 за превышение скорости
=145 XP
```

Если игрок завершил маршрут с нарушением, он всё равно может получить опыт за
участие и завершение. Если сценарий отменён технически, опыт не начисляется.
Если игрок сам покинул активный сценарий, это отдельное игровое решение, которое
будет зафиксировано после согласования правил прогресса.

## Геометрические проверки

Серверный движок в
[`server/scenario_rules.py`](server/scenario_rules.py) принимает описание
логики дороги и проверяет движение по серверным координатам. Поддерживаются:

- ограничение скорости;
- расстояние до центральных линий полос;
- выход за допустимую ширину полосы;
- пересечение стоп-линии без предварительного снижения скорости.

Проверки включаются только если у сценария есть `rule_config`. Поэтому
временный `priority-test` продолжает работать без финальной metadata карты.
Каждое новое нарушение фиксируется один раз через `ScenarioManager`, после
чего отправляется `rule_event` и учитывается при расчёте XP.

Если у разных ролей разные полосы или стоп-линии, конфигурация задаётся через
`rule_config.role_rules` с ключами `roleId`. Это не меняет карту: карта
описывает постоянные полосы, а сценарий выбирает, какая полоса разрешена
конкретной роли.

## Что сервер отдаёт клиенту

### Ожидание участников

```json
{
  "type": "scenario_waiting",
  "sceneId": "world:main",
  "epoch": 1,
  "scenarioId": "priority-crossroad-01",
  "waiting": 1,
  "required": 2
}
```

### Назначение роли

```json
{
  "type": "scenario_assigned",
  "sceneId": "world:main",
  "epoch": 1,
  "scenarioId": "priority-crossroad-01",
  "sessionId": "scenario:1",
  "roleId": "main-straight"
}
```

После назначения сервер отправляет `scene_prepare` с `sceneKind: "scenario"`,
`mapId`, `scenarioId`, `roleId`, spawn игрока, списком участников и планом
ресурсов. Клиент отвечает `scene_ready`; движение разрешается только после
общего `scene_start`.

При нормальном завершении сервер фиксирует фактическую позицию каждого игрока
в момент `scenario_result`, сохраняет её как безопасную мировую позицию и
возвращает игрока в `world:main` в эту же точку. Если игрок добровольно
покидает сценарий, результат не начисляется, сессия отменяется, а игрок
возвращается в `return_spawn` сценария — центр перекрёстка. Если игрок
отключается от сервера во время сценария, сессия также отменяется, но его
безопасная позиция в БД сбрасывается на обычный `spawn` мира. При следующем
подключении он появится на этой точке.

### Подсказка и нарушение

```json
{
  "type": "rule_event",
  "sceneId": "scenario:1",
  "epoch": 2,
  "eventId": "event-17",
  "tick": 301,
  "playerId": "p1",
  "ruleId": "speed_limit",
  "severity": "violation",
  "text": "Снизьте скорость перед перекрестком."
}
```

### Индивидуальное завершение

```json
{
  "type": "scenario_player_finished",
  "sceneId": "scenario:1",
  "epoch": 2,
  "scenarioId": "priority-crossroad-01",
  "sessionId": "scenario:1",
  "playerId": "p1",
  "roleId": "main-straight",
  "passed": true,
  "violationIds": [],
  "xp": 150
}
```

### Общий результат

```json
{
  "type": "scenario_result",
  "sceneId": "scenario:1",
  "epoch": 2,
  "resultId": "result-1",
  "scenarioId": "priority-crossroad-01",
  "status": "completed",
  "reason": null,
  "players": [
    {
      "id": "p1",
      "roleId": "main-straight",
      "passed": true,
      "violationIds": [],
      "xp": 150
    },
    {
      "id": "p2",
      "roleId": "secondary-turn",
      "passed": false,
      "violationIds": ["event-17"],
      "xp": 95
    }
  ]
}
```

При `status: "cancelled"` используются причины `participant_left`,
`load_timeout`, `load_failed` или `server_cancelled`. В этом случае `xp` не
начисляется, а `passed` имеет значение `null`.

## Локальная проверка временного сценария

Пока клиентский интерфейс регистрации ещё не подключён, сценарий можно
проверять через WebSocket-клиент или временный вызов из DevTools. Каждый
участник должен быть авторизован под отдельным аккаунтом и сначала дождаться
`scene_start` общего мира. Затем отправляется:

```json
{
  "type": "scenario_join",
  "scenarioId": "priority-test"
}
```

Первый игрок получит `scenario_waiting`. После регистрации второго сервер:

1. назначит роли `main-straight` и `secondary-turn`;
2. увеличит `epoch` и отправит обоим `scene_prepare` с `sceneKind: "scenario"`;
3. дождётся `scene_ready` от обоих;
4. отправит одинаковый `startTick` в `scene_start`;
5. будет рассылать snapshot только участникам этой сценарной сцены;
6. завершит игрока в его destination-зоне.

Сейчас результат и XP рассчитываются сервером, сохраняются в SQLite, а после результата участники
получают новый `scene_prepare` общего мира через 5 секунд. UI подсказок,
правила ПДД и клиентское отображение накопленного XP ещё не подключены.

## Что нужно сделать после появления финальной карты

1. Заменить временные `mapId`, координаты и идентификаторы на данные импортёра.
2. Проверить, что spawn и destination находятся на соответствующих полосах.
3. Реализовать переход `world:main` → `scenario:<id>` и возврат назад.
4. Реализовать проверку линий, полос, скорости и приоритета на сервере.
5. Подключить `rule_event` и `scenario_result` к клиентскому UI.
6. Подключить клиентское отображение накопленного XP и истории результатов.
7. Добавить интеграционные тесты на сценарий из двух и трёх участников.

До появления этих данных сервер не должен использовать выдуманные координаты в
боевом сценарии: временная конфигурация допустима только для локального smoke-
теста.
