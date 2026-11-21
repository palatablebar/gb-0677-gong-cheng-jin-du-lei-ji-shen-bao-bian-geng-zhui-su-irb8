# 计量定义

claim_id唯一；item为清单编码，支持钢筋与001等别名。period为YYYY-MM。累计数量按t或m³保存，当前周期工程量=本次累计-前期已审累计。previous_revisions参数可指定更正后的前审数量，重新计算形成不同批次，不覆盖旧证据。

C0原始价100元，C1自2026-11生效为120元，DRAFT未批准不可结算。负进度必须reversal=approved作为已批冲回标记。扣留质保金5%、预付款扣回10%分别按分量化，净额=本期总额-质保金-预付款扣回，负进度同步冲回扣留。reported为原申报净额，差异=复算净额-reported。

业务ID和超大整数按文本保形；Decimal参与数量金额计算，对外序列化为字符串。哨兵集合定义在app/values.py，缺失值不能当零。所有时间带UTC偏移，先转UTC比较，业务日按指定地区划分。区间统一[start,end)。重复业务键保留第一条、完全相同行计重复；值冲突行隔离且保留原值。空文件、全空白、仅表头分开拒绝。

运行清单包括输入sha256、规则版本、参数、生成时刻与耗时。源行编号以CSV解析器的物理结束行号表示，引号内换行不增加记录数。输入超过4MB返回413，非法表头和类型返回422，失效版本复核返回409。

## 暂估签认（M8）

业务键 `business_key=claim_id|period`（文本保形，全程字符串）。confirmed_qty为已确认工程量，Decimal归一且不可为负；provisional_price为暂估价，缺失、空串或哨兵集合值视为无价，此时held_amount为空而不是0。裁决固定口径：status为`待批价`时payable_amount强制`0.00`；held_amount=confirmed_qty×provisional_price，仅作暂缓展示，不进入付款。

记录字段：run_id/source_lines保留与原批次及来源行的对应；original_declaration为原申报不可变快照（批价后同样不覆盖）；approved_price、approval_ref在批价后追加，version自1递增。SQLite表provisional_confirmations按business_key唯一，price_approvals保存from_version/to_version及original_snapshot。条件更新 `WHERE business_key=? AND version=? AND status='待批价'` 与审批插入同事务，失败整体回滚。规则版本独立编号PROVISIONAL_RULE_VERSION，不影响七阶段批次的输入摘要。