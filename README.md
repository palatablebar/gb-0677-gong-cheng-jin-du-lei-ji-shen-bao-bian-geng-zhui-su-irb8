# 工程进度累计申报与变更追溯

供总包项目计量审核员核对原始记录、处理差异并封存证据。

## 启动

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
```

打开 http://localhost:18246 。首次进入自动运行仓内脏样例。工具条可重跑、切换样例或上传CSV。SQLite保存在命名卷records中，重建服务保留批次。

## 模块

- 1. 申报采信：`/claims`，`/api/claims`。
- 2. 清单映射：`/billitems`，`/api/billitems`。
- 3. 变更定版：`/changes`，`/api/changes`。
- 4. 累计还原：`/increment`，`/api/increment`。
- 5. 扣回核算：`/deductions`，`/api/deductions`。
- 6. 进度对账：`/valuation`，`/api/valuation`。
- 7. 签证归档：`/certificates`，`/api/certificates`。
- 8. 暂估签认：`/provisional`，`/api/provisional`（量价分离工作台）。

## 核心规则

累计申报必须减前期已审金额，变更按审批生效版本覆盖；负进度需关联冲回证据。

新增钻孔等已完工但新增单价未批的工作，按**量价分离**裁决：已确认工程量按实签认避免跨月断档；价格依据缺失时 `payable_amount` 一律为 `0.00`，不生成付款金额；暂估价只折算 `held_amount`（暂缓金额）单列，禁止并入本期签证。后续批价以新版本追加付款，原申报快照与已确认量永不覆盖，同一工作量重试不重复确认，版本切换失败保留旧版并整体回滚。

### 暂估签认接口

- `GET /api/provisional`：工作台列表与汇总（签认项、待批价、已批价、暂缓金额合计、可付金额合计）。
- `POST /api/provisional`：签认工程量。字段 `claim_id`、`period`(YYYY-MM)、`confirmed_qty` 必填，`provisional_price` 可空（仅用于暂缓金额），可传 `run_id` 链接既有批次定位原申报。首次 201，同载荷重试 200 幂等，同键不同载荷 409。
- `GET /api/provisional/<claim_id%7Cperiod>`：签认明细及该工作的全部批价记录。
- `POST /api/provisional/<key>/approval`：后续批价，需 `version`、`approved_price`、`approval_ref`；陈旧版本或重复批价返回 409，失败不改动原记录。
- `GET /api/provisional-approvals`：批价与原申报快照的对应关系总表。

## 演示

1. 打开首页，核对当次计算、差异和隔离原因。
2. 切换模块查看源行及裁决依据。
3. 重跑相同样例，批次号与行数保持一致。
4. 复核后导出一份证据CSV。版本已变化的复核提交返回409。

## 输入与输出

输入列见 `docs/DATA-DICTIONARY.md`。项目包含dirty.csv、clean.csv、legacy.csv，统一走实际导入路径。上传限制4MB，拒绝不带时区的时间。业务键按字符串保留，Decimal参与计算，空值不会当零。

`POST /api/runs` 接收sample或csv；`GET /api/runs`返回历史批次；`POST /api/runs/<id>/review`需要version与decision；`GET /api/runs/<id>/archive`返回唯一证据导出。

## 范围

样例均为虚构。单机复核工具不连接生产系统；不提供登录、远端数据库或自动支付。内存计算按4MB输入上限控制，SQLite事务保证结果完整写入。

## 目录

app为服务与规则，sample_data为输入，tests为测试，docs为定义与深度登记。
