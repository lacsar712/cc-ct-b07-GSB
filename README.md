# 数控刀补复核台

操作员提交刀具编号与刀补微米值（普通/急补）；后台 worker 用 PostgreSQL 行锁（`select_for_update(skip_locked=True)`）认领待复核记录，按绝对值是否不超过 12 微米给出「合格」或「超差」。

最近结清记录连续超差达到操作员设定的条数阈值时触发**缓领**：缓领秒数内 worker 停领普通刀补，急补仍可认领；秒数尽自动解除并恢复。开始与解除各记一条流水（留存当时阈值/秒数快照），修改阈值不追溯旧流水。

## 缓领规则

- 阈值（连续超差条数）与缓领秒数由操作员在「缓领台」设置，立即生效；复核员只读。
- 「是否在缓」只有一个判定口径（`desk.services.get_active_slowdown`）：worker 认领跳过普通刀补与缓领台状态灯同源，不可能各说各话。
- 连续超差的统计区间为上一轮解除流水之后；中间出现合格即打断计数。
- 开始流水关联触发它的那几笔刀补；解除流水与开始流水按轮次（episode）配对。
- 缓领期间急补照常认领；急补结论不影响本轮缓领（不重入、不延长）。

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
| machinist | machine123456 | 可提交刀补、设置缓领阈值与秒数 |
| auditor | audit123456 | 只读（列表与缓领台，不能改设置） |

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
4. 缓领台：菜单进入（总览角标不计数），含阈值、秒数、是否在缓状态灯、起止流水总览；auditor 只见只读数值，不能改。
5. 阈值保持 2、秒数设短（如 10 秒），连续提交两笔绝对值大于 12 µm 的**普通**刀补：结清后缓领台状态灯转「缓领中」，流水出现一条「开始」并关联这两笔记录。
6. 缓领中再提交普通刀补应一直停留「待复核」；提交**急补**仍会被秒级认领结清。
7. 秒数尽后流水出现配对的「解除」，状态灯熄灭，滞留的普通刀补恢复认领。
8. 事后修改阈值/秒数，旧流水的阈值、秒数快照不变。

## 目录

```text
backend/          Django 工程（config/、desk/、worker.py）
frontend/         SolidJS 单页
docker-compose.yml
PRD.md
```
