# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

## 暂估签认（量价分离）

`GET /api/provisional` 返回 `{rows,metrics}`，metrics含records、pending_price、adjudicated、held_total、payable_total。`POST /api/provisional` 接收claim_id、period(YYYY-MM)、confirmed_qty，可选provisional_price（缺失或哨兵值时暂缓金额为空）、item、unit、run_id；传run_id时按claim_id在批次各阶段定位原申报并固化来源行与快照。首次创建201，同业务键同载荷重试200幂等，同键不同载荷409(ALREADY_CONFIRMED)。

`POST /api/provisional/<business_key>/approval` 接收version、approved_price、approval_ref，条件更新版本并在同一事务写入price_approvals；陈旧版本409(STALE_VERSION)、重复批价409(ALREADY_ADJUDICATED)，非法价格422且整体回滚。`GET /api/provisional/<business_key>` 返回confirmation与approvals（含original_snapshot原申报快照）。`GET /api/provisional-approvals` 返回全部批价对应关系。暂估签认独立于runs表，不改变既有批次run_id与证据导出。
