# 数控刀补复核台

操作员提交刀具编号与刀补微米值；后台 worker 用 PostgreSQL 行锁（`select_for_update(skip_locked=True)`）认领待复核记录，按绝对值是否不超过 12 微米给出「合格」或「超差」。

连续超差缓领：操作员可设置「连续超差条数阈值」与「缓领秒数」。最近结清记录中连续超差达到阈值即进入缓领——缓领秒数内 worker 停领普通刀补，急补仍可认领；到期后自动解除并恢复普通认领。开始与解除各写一条追加式流水（快照当时阈值/秒数，改配置不追溯旧流水）。「是否在缓」由 `desk.services.sync_hold_state` 单一来源判定，worker 认领跳过与缓领台状态灯共用，不会分叉。

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Django 5 + django-ninja（ASGI / uvicorn） |
| 前端 | SolidJS + Vite，nginx 反代 `/api` |
| 数据库 | PostgreSQL 16 |
| 鉴权 | JWT（python-jose），令牌存浏览器 localStorage |

## 端口

| 服务 | 地址 |
|------|------|
| 页面 | http://localhost:3196 |
| 接口 | http://localhost:8196 |
| PostgreSQL | localhost:54396（库名 `cncoffset`） |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| machinist | machine123456 | 可提交刀补 |
| auditor | audit123456 | 只读列表 |

## 启动

```bash
cd projects/17-cnc-tool-offset-desk
docker compose up --build
```

健康检查：`GET http://localhost:8196/api/health` → `{"status":"ok"}`

## 验收

1. machinist 登录后，种子数据应显示刀具 T01 合格（刀补 5 µm）、T09 超差（刀补 20 µm）。
2. 提交一条新刀补后，状态先为「待复核」，数秒内 worker 处理为「已完成」并给出结论。
3. auditor 登录后只能看列表，没有提交表单。
4. 缓领台（菜单进入，总览不挂角标）：操作员设阈值 2、秒数若干；复核员只能看，不能改阈值/秒数。
5. 连交两笔注定超差的普通刀补（如 ±20 µm）后，缓领台状态灯转「在缓」，出现一条「开始」流水（含阈值、秒数、连续数、触发刀具）。
6. 缓领中再交普通刀补应一直停在「待复核」不被认领；交一笔急补仍会被认领结清。
7. 秒数到后出现「解除」流水，状态灯熄灭，积压的普通刀补恢复认领。
8. 中途改阈值/秒数只影响之后，旧流水保留当时快照、不追溯。

## 目录

```text
backend/          Django 工程（config/、desk/、worker.py）
frontend/         SolidJS 单页
docker-compose.yml
PRD.md
```
