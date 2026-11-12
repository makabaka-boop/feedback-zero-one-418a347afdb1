# repairjson — 最大权重修复与查询确定性分析

科研主数据中互相矛盾的声明不能靠任意去重消除：那会把**不确定的答案伪装成事实**。
本作业从零（仅用 Python 标准库）实现一个后端分析器：

1. 读取 UTF-8 JSON（`columns` / `rows` / `dependencies` / `query`）；
2. 在「只能删除整行、必须同时满足全部函数依赖」的前提下，求保留权重总和最大的
   **全部**最优修复；
3. 在每个修复后的同表上执行等值自连接查询，输出全部可能结果元组，并标注每个元组
   由多少个最优修复产生、是否在**所有**最优修复中出现（确定答案）。

## 运行方式

需要 Python 3.9+，无第三方依赖。

```bash
# 入口：python -m repairjson.cli 输入.json 输出.json
python3 -m repairjson.cli examples/master_data.json /tmp/out.json
```

也可作为库调用：

```python
from repairjson import run, InputError

try:
    result = run(payload)          # payload 为 json.load 得到的 dict
except InputError as exc:
    print(exc.path, exc)           # 带 JSONPath 的拒绝原因
```

非法输入**整次拒绝**：CLI 以状态码 1 退出并打印定位路径（如
`$.rows[2].values.K`），输出文件不会被创建或替换（成功时先写同目录临时文件再
`os.replace` 原子替换）。

## 输入契约

| 部分 | 要求 |
| --- | --- |
| `columns` | 非空 ASCII 字母数字下划线串数组，唯一 |
| `rows[].id` | 同规则标识符，全表唯一 |
| `rows[].weight` | 正整数；**布尔不是整数**，`true/false` 被拒 |
| `rows[].values` | 恰含全部列，单元格为字符串或 `null` |
| `dependencies[]` | `lhs`、`rhs` 均为非空列数组，内部无重复，引用必须存在 |
| `query.aliases` | 非空唯一别名数组，全部绑定修复后的**同一张表**（可绑定同一行） |
| `query.conditions` | `[alias.column, alias.column]` 二元数组；两侧**均非 null 且值相等**才成立 |
| `query.projections` | 非空 `alias.column` 数组，决定输出元组的列顺序 |

依赖判定中 `null == null` 视为相等：两条保留行在 lhs 全部相等（含 null）时，
rhs 也必须全部相等。无任何条件时，别名的任意绑定都产生见证。

## 输出契约

```json
{
  "optimal_weight": "19",
  "optimal_repair_count": "2",
  "tuples": [
    {
      "tuple": ["X1", "4.1"],
      "optimal_repair_count": "1",
      "in_all_optimal_repairs": false
    }
  ]
}
```

* 所有权重与计数均为**十进制字符串**，避免大整数精度歧义；
* 元组按投影位置逐位比较：字符串按 UTF-8 字节序，`null` 排在所有字符串之后；
* 同一修复内多个查询见证只计一次（修复内按集合去重）后再跨修复计数；
* 空表恰有一个空修复（权重 `"0"`，修复数 `"1"`，无结果元组）；
* 不同 `id` 即使各单元格完全同值也是不同记录。

## 设计要点

### 修复 = 冲突图上的最大权独立集

`repairjson/solver.py` 先构建**冲突图**：对每条依赖按 lhs 值分组（null 参与
分组），同组内 rhs 存在不一致的行对连边。任意修复合法当且仅当它是该图的独立集，
于是「最大化保留权重」即最大权独立集（MWIS）。

求解分两阶段，均为自行实现的分支定界：

1. `maximum_retained_weight` 求最优权重（贪心独立集给初始下界，上界剪枝，
   无冲突顶点强制纳入，按剩余度选分支点）；
2. `enumerate_optimal_repairs` 以该权重为目标枚举**全部**最优独立集，
   供查询答案计数。

### 查询评估

`repairjson/query.py` 对别名做修复后行集的笛卡尔积（`itertools.product`，
别名允许同行；空修复自然无绑定），逐条校验等值条件（双非空 + 相等），投影后
按集合去重。

### 确定性不能用「必留行」代替

两条等权冲突行投影同一个键时，该键在两个最优修复中都出现，仍是确定答案，
尽管没有任何一行是必留的。因此本实现**不**走「只在必留行上查一次」的捷径，
而是对每个最优修复独立评估再聚合（见
`tests/test_exhaustive.py::test_equal_weight_conflict_key_is_certain`）。

## 验收测试

全部测试使用标准库，建议以隔离模式运行：

```bash
python3 -I tests/test_exhaustive.py   # 独立 2^n 暴力 Oracle + 400 组随机小表
python3 -I tests/test_validation.py   # 非法输入定位、布尔拒绝、输出原子替换
python3 -I tests/test_stress.py       # 中规模 Oracle 对拍 + n≤24 独立 DP 对拍
```

`tests/test_exhaustive.py` 中的 Oracle 是**另写的一份**直接基于原始 dict 的
暴力实现（枚举全部行子集、独立实现查询语义），不与生产代码共享求解逻辑。

手工场景覆盖：

* **多依赖交叉冲突**：`A→B` 与 `B→C` 产生交叉冲突边，3 个等优修复；
* **权重取舍**：同 lhs 组内高权行唯一胜出，唯一最优修复；
* **自连接见证切换**：双别名 `t.A = u.A`，冲突行切换后 `(30,30)` 见证仍在；
* **null 语义**：依赖中 `null=null` 造成冲突；查询等值遇 null 不成立；
  排序时 null 置后，字符串按 UTF-8 字节序（`a < b < é`）；
* 同修复多见证只计一次；空表的空修复。

## 模块布局

```
repairjson/
  validate.py   严格结构校验，错误带 JSONPath
  model.py      不可变数据模型
  solver.py     冲突图 + 分支定界 MWIS，枚举全部最优修复
  query.py      修复表上的自连接等值查询
  pipeline.py   端到端编排与输出排序/聚合
  cli.py        命令行入口，原子写输出
tests/          Oracle 对拍、校验、压力三套验收
examples/       master_data.json（多依赖+null）、self_join.json（自连接）
```
