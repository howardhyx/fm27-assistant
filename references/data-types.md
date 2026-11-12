# 数据类型与命令

下列命令省略公共前缀 `<python-3.12> <skill>/scripts/fm.py`。可在任意命令后加 `--save <file.fm>`、`--game-dir <game>`、`--club-uid <uid>`、`--team-id <id>`、`--out <workspace/file.json>`。ID从实际 `context/baseline/fixtures` 获取，示例占位符不是固定ID。

## 1. 来源与必读包

仅查询日期、版本或文件来源：

```text
metadata --save <file.fm>
```

`metadata` 不依赖游戏安装或 DLL，返回 `game_date/build/save_name/time_slot/clock_source/metadata_schemas` 和完整文件来源。它只接受存档和输出参数，不接受球队、游戏目录或字段裁剪参数。日期来自结构化存档摘要；若该时钟不可验证则拒绝，不猜测内部时钟。`coverage.metadata_only=true` 表示未读取球队、战术或比赛，此时不执行 `baseline`。这不是新版本的完整适配证明。

```text
doctor --save <file.fm>
baseline --save <file.fm> --out <workspace/work/baseline.json>
context
```

`doctor` 是可选诊断，不是读取前置步骤。它报告解释器、存档、版本、指纹及缓存目录是否可读，不解码整个比赛集。未知指纹或存档/DLL版本不同不阻断读取；`profile.version_check_enforced=false`，未匹配历史验证组合时原生适配标记为未经验证，结构检查仍严格执行。缓存条数来自当前存档，不能把开发验证中的2,201条当成固定值。

`27.0.1+2494687` 的 `doctor.profile.unsupported_commands` 明列 `season`。`baseline.coverage.saved_tactic_collection` 记录首部声明块数、顺序遍历边界和集合外字节数。历史战术和时间线仍是部分结构读取；时间线载荷类型5尚不支持，应单独请求已支持的 `summary/players/events/tactics`，不能跳过未知指令后拼成完整时间线。

`baseline.data`：

- `context`：游戏内日期、俱乐部、球队列表与选定球队。
- `tactics[]`：该球队每一份已保存战术，含 `index/name/style_name/mentality`。全部返回，不选“看起来最常用”的一套。
- `tactics[].formation[]`：11个槽位，每个槽有 `in_possession` 与 `out_of_possession`，含 `position_labels/position_mask/current_role_name/current_role_label/current_role_flags/duty_bits/personal/player_overrides`；`out_of_possession_index` 是无球槽位排列。
- `team_instructions.groups[]`：每组的内部名、中文释义、有球/无球阶段、内部选项名、选项释义、是否存在显式设置位。`unknown_set_bits` 必须检查。
- `personal.instructions/instructions_zh` 是当前角色下保存的覆盖项；`personal=null` 与 `instructions=[]` 不自行等同于“没有任何角色行为”。
- `selection[]`：首发/替补、槽位和球员UID；与战术槽位关联，但不是已确认的下一场名单。

单独重读同类数据：`tactics` 或 `selection`。必读阶段不通过 `--fields` 剪掉阵型和指令。

## 2. 球员、属性和习惯

```text
players --scope team --fields uid,unique_id,name,age,positions,traits
players --scope club --age-max 21 --fields uid,name,team_id,positions,attributes
players --player-uid <uid> --fields uid,unique_id,name,attributes,positions,traits,left_foot,right_foot
players --scope all --position dc --position-min 15 --attribute-min pace=14 --attribute-min jumping_reach=14 --limit 20
```

`--scope team`（默认）按当前选定球队；`club` 含该俱乐部球员，可能含梯队/租借；`all` 是整个存档数据库，不是球探已知列表。使用 `--scope all` 应由明确的外部球员数据需求触发，不为普通球队读取遍历输出全库。

过滤器：`--player-uid`、`--player-unique-id` 可重复；`--name` 不区分大小写的子串匹配；`--age-min/max`；`--position`；`--attribute-min 名称=最低值` 可重复；`--value-max` 按存档原始基础币种过滤，未知身价不通过此条件。

位置键：`gk dc dl dr dm mc ml mr aml amc amr stc wbl wbr`。`position-min` 默认15，是本次查询的熟练度阈值，不能翻译成某个已确认角色适配评分。

公开属性键按实际返回的 `attributes` 对象选择，如 `pace/acceleration/stamina/work_rate/positioning/decisions/passing/tackling/jumping_reach`。未知属性名会报错，不允许猜隐藏字段路径。

`condition_raw/match_sharpness_raw` 保留原尺度，不直接标百分比；`natural_positions/accomplished_positions` 与数值位置熟练度并存。CA、PA和隐藏性格/比赛属性不返回。

## 3. 合同、租借与停赛

```text
contracts --scope club --fields uid,name,contract.end,contract.end_source,contract.wage,contract.squad_status
players --player-uid <uid> --fields uid,name,contract,on_loan,loan_parent_club_uid,suspensions
```

`contracts` 是球员读取器的合同投影，默认只返回身份、球队和合同。合同含开始/结束、结束字段来源、队内地位、合同类型、已识别条款、租借。空合同、未命名条款和未知期限保留为空/原码。

工资值的货币和周期未在本接口独立核实，不能擅自称为当前界面“周薪”。`suspensions` 不是完整伤病历史；没有提供通用伤病读取命令。

## 4. 赛程与详细比赛目录

```text
fixtures --played yes --since YYYY-MM-DD --until YYYY-MM-DD --limit 10
fixtures --played no --limit 5
cache-matches --since YYYY-MM-DD --limit 5
cache-matches --date YYYY-MM-DD
```

`fixtures` 是赛程/赛果，含双方球队ID、日期、是否已赛、比分、赛事ID。`--played no` 按日期正序返回接下来的比赛；已赛按日期倒序。梯队与一线队必须用选定球队ID隔离。

`cache-matches` 是可读详细缓存目录：先读取各压缩帧的有界前缀，只对筛选命中的指定记录解压并核对球队头。不会解码全部比赛里的球员事件。返回 `cache_key/kick_off/home_team_id/away_team_id/home_goals/away_goals/expected_goals`。

两种目录不是同一个概念：赛程有记录不保证详细缓存仍在；缓存本身也不是整个生涯。应比较请求范围与实际覆盖。

## 5. 指定比赛

```text
match --match-key <cache_key> --part summary
match --date YYYY-MM-DD --part players --side selected --fields identity.name,stats.shots,stats.expected_goals,stats.key_passes
match --match-key <key> --part events
match --match-key <key> --part shots --name <球员子串>
match --match-key <key> --part advanced-shots
match --match-key <key> --part snapshots
match --match-key <key> --part tactics --side selected
match --match-key <key> --part tactic-timeline --side selected
match --match-key <key> --part tactic-timeline --side selected --fields index,recorded_minute,native_tick,type,payload
```

没有 `--match-key/--date` 时选择所选球队最近一场可读缓存，并在结果返回key与时间；同日多场必须用key消歧。`--side selected` 只返回所选球队的行，默认双方。逐人/事件/射门可用球员UID、唯一编号和姓名过滤。`--part all` 仅用于确需单场完整结构，不用作默认准备动作。

各 `part`：

- `summary`：双方xG、射门、射正、传球、成功传球、比分和按控球计数计算的百分比。
- `players`：身份、39项详细球员统计、上下场时刻原码。主要 `stats` 键：`goals/assists/expected_goals/non_penalty_expected_goals/expected_assists/shots/shots_on_target/shots_outside_box/free_kick_shots/passes_attempted/passes_completed/progressive_passes/key_passes/open_play_key_passes/clear_cut_chances_created/crosses_attempted/crosses_completed/open_play_crosses_attempted/dribbles/offsides/distance_km/high_intensity_sprints/aerial_challenges_attempted/headers_won/key_headers/tackles_attempted/tackles_completed/key_tackles/interceptions/possession_won/possession_lost/blocks/shots_blocked/clearances/fouls_made/fouls_against/yellow_cards/red_cards/mistakes_leading_to_goal`。
- `events`：已命名 `goal/own_goal/penalty_goal/yellow_card/second_yellow/red_card`；`other_player` 是关联者，普通/点球进球中与同队有效球员关联时可核对助攻。其余类型为 `unconfirmed` 并保留 `kind`。
- `shots`：每次射门的球员、分钟/秒原值、tick、结果码、标记、4个坐标原值。结果码1与进球计数一致，1+4与射正计数一致；不能擅自解释全部其他码。
- `advanced-shots`：另一种附加射门结构，不保证包含全部射门；类型、状态和坐标语义部分未确认，不把它直接称为完整射门地图或VAR清单。
- `snapshots`：比赛内缓存的战术/选人结构，含个人唯一编号引用、原始角色/标记。不要直接当作逐分钟的阵型变化或换人时间线。
- `tactics`：模拟状态内双方球队主战术对象，含 `name/mentality/team_instructions/formation`，双阶段位置、角色和当前角色的个人覆盖。`--side selected` 仅取所选队；该结构不支持球员过滤或 `--fields` 行裁剪。返回 `state_scope/evidence`：球队根位置、主/次对象顺序及结构检查；不以战术名称推断归属，不查询当前保存战术来补历史。`opening_tactic_confirmed/whole_match_tactic_confirmed=false` 表示时点和全场覆盖未确认。29组映射外的非零位保留于 `unknown_set_bits`，不得猜成某项开关。个人默认、临场切换和定时指令变化未展开。
- `tactic-timeline`：`initial_state.teams` 为修改队列前序列化的经理基线；`changes[]` 含 `index/recorded_minute/native_tick/side/team_id/type/payload`。当前支持的种类见返回值；包括球队基础设置替换（含 `base_setting_changes`）、双阶段单槽角色和个人覆盖、槽位对应关系、战术改名、换人、快捷调整启停以及讲话等伴随记录。快捷调整返回内部名称、绝对覆盖、档位变化原码和心态覆盖；不能只看基础设置替换就声称那是全部有效指令。讲话内容及部分针对性引用维持原码。支持 `--side`、行投影、`--limit`，不支持球员姓名/UID过滤。`count` 是完整队列记录数，返回行数和截断状态看 `coverage`。

时间线按计数精确逐条读取到帧末尾、核对原生时刻顺序，并把换人的时刻与独立球员上下场统计交叉核对；任何未知种类、结构、错位或歧义均失败，不能跳过后继续生成“完整时间线”。原生时刻保留整数，分钟采用记录自身字段；不自行换算秒数或补时显示。队列完整不等于全部AI决策或所有实际行为都被保存，也不等于所有覆盖层已重放。

每次单场完整读取会核对双方汇总与球员相加，以及逐人进球、助攻、红黄牌与事件表。失败会返回错误，不能继续称为已验证数据。`coverage.unparsed_following_bytes` 是统计解码器后方区域的长度；`tactics/tactic-timeline/all` 会在该区域另行定位战术对象，时间线另返回 `coverage.tactical_command_queue`，该长度不等于完全未读字节数。`all` 包含历史战术及修改队列，未知布局时明确报错。

## 6. 赛季累计

```text
season --kind overall --fields player_uid,player_name,minutes,goals,assists,expected_goals,expected_assists
season --player-uid <uid> --kind overall
```

只取选定球队的行。`--kind` 是返回数据的统计类别，默认 `overall`；需要其他类别时先查询模型枚举或实际值，不能按自创赛事分类汇总。可用姓名、UID、唯一编号过滤。

不要把overall与其包含的分项相加。赛季累计与详细缓存、短期逐场历史的范围不同，直接差值不等于解析错误。门将赛季字段如 `saves_held/saves_parried/saves_tipped/shots_on_target_faced/expected_goals_prevented` 有单独口径。

## 7. 历史财务、定位球名称

```text
finances --limit 3 --fields month,balance,transfer_budget_remaining,wage_budget_weekly,wage_payroll_weekly
set-pieces --fields team_id,slot,name
```

财务是历史月末数据，`month` 是事实所对应日期，不是存档当天余额。所有金额为未换算的存档基础币种；`transfer_budget_allocated` 含义未确认，不能当董事会分配预算。已命名weekly字段按周理解，其他工资字段依各自说明。

定位球只读出套路名与槽位，不能声称读到完整跑位、盯人或站位指令。

## 输出协议

成功：`ok/schema_version/data_type/source/coverage/filters/notices/interpretation_status/data`。失败：`ok=false/error_type/message/data_type`，进程非零退出。

`--fields` 为行投影，点路径结果按请求原样作键，如 `"stats.expected_goals"`，不是重新嵌套的对象。`--out` 返回输出路径摘要；需要解释字段时再读取所保存JSON。输出文件只能是工作区JSON，不能是 `.fm`、游戏安装内文件或存档目录内文件。
