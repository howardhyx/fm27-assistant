# Assistant for Football Manager 27

一个只读本地 Football Manager 27 存档的 Agent Skill。按需读取球队、已保存战术、双阶段阵型与角色、指令、选人、球员、合同、赛程、比赛统计与事件、历史战术及已记录的临场修改。字段含义与覆盖限制随结果说明，不内置固定的战术或转会推荐规则。

## 使用条件

- Windows x64、Python 3.12。依赖运行库随 `scripts/vendor` 提供。
- 已有 `27.0.0+2493426` 与 `27.0.1+2494687` 的分能力适配。版本与 DLL 指纹不再作为准入阻断；未匹配历史验证组合时明确提示未经验证，仍严格检查数据结构与统计一致性，详见[维护说明](references/maintenance.md)。`27.0.1` 的赛季合计读取因完整性检查失败继续停用；开源不表示自动兼容所有 FM27 更新、FM26、macOS 或 Linux。
- 用户自行安装游戏并提供本地存档；包中不包含游戏 DLL 或私人存档。

## 安装与首次使用

技能标识为 `fm27-assistant`。将完整的 `fm27-assistant` 文件夹放入所用 Agent 的技能目录；例如 Codex 的用户技能目录为 `~/.codex/skills/`。也可直接让支持本地技能的 Agent 读取本目录的 [SKILL.md](SKILL.md)。Python 命令在本目录执行：

```powershell
python scripts/fm.py baseline
# 可选：诊断并记住当前存档与游戏路径
python scripts/fm.py doctor --remember-paths
```

首次从系统文档目录和 Steam 库发现位置，可直接读取；`doctor --remember-paths` 是可选配置步骤，通过结构检查后才将路径保存到仅本机使用的 `local/paths.json`。后续直接复用。找不到目录、切换存档或安装目录不可写时，参阅[本地配置](references/local-setup.md)。个人路径不写进公共 Skill 文档。

## 读取范围

[数据类型与命令](references/data-types.md)列出筛选方式；[字段与关联规则](references/semantics.md)解释 ID、原值和覆盖范围。只读本地文件，不操作游戏界面、进程或原存档；未知结构、数据越界或统计交叉检查失败时明确报错，版本不匹配仅提示。完整触球流、热图、连续跑位、完整定位球指令和实时数据尚不支持，部分字段语义仍未确认。

## 依赖与致谢

本项目借助了以下开源项目，感谢原作者及社区贡献者的工作。

| 项目 | 版本或引用方式 | 在本项目中的用途 |
|---|---|---|
| [fmsave](https://github.com/rhiever/fmsave) | 0.10.0，随包运行依赖 | 提供存档读取基础，包括打开存档、读取球员、球队、合同、赛程、已保存战术及部分统计。 |
| [fm-tactics-lab](https://github.com/lqf0624/fm-tactics-lab) | 战术目录与字段参考 | 参考战术指令、角色目录及部分原生字段位置与结构，再对照对应版本的本地游戏文件校验。 |
| [backports.zstd](https://github.com/rogdham/backports.zstd) / [Zstandard](https://github.com/meta/zstd) | backports.zstd 1.8.0，随包运行依赖 | 解压存档和比赛缓存中的压缩数据，底层采用 Zstandard。 |
| [Unicorn](https://github.com/unicorn-engine/unicorn/tree/2.1.4) | 2.1.4，随包运行依赖 | 在隔离的虚拟 CPU 中模拟少量原生标量读取逻辑，辅助解码比赛球员统计。 |

研究阶段还使用了 [Capstone](https://github.com/capstone-engine/capstone) 查看游戏文件中的机器指令，追踪字段、战术对象和修改队列。它属于研究工具，未随最终工具包分发，也不是运行本 Skill 所需的依赖。

在这些项目的基础上，本项目将读取能力组织为面向 Agent 的按需 JSON 接口，补充了指定 FM27 构建的战术与比赛记录适配、来源和覆盖范围说明、结构交叉校验、本地路径发现与记忆，以及 Skill 指令和字段解释文档。

各组件保留原有版权与许可；具体许可文件、分发说明和 Unicorn 源码归档见 [第三方组件说明](THIRD_PARTY_NOTICES.md)。

## 验证与打包

```powershell
python -B -m unittest discover -s tests -v
python -B scripts/package_release.py --out "<仓库外的发布包.zip>"
```

路径测试使用合成文件和隔离配置，不需要读取个人存档；测试夹具写在已忽略的 `local/test-runs/`。发布脚本排除本地配置、测试夹具、工作输出、存档及游戏 DLL，但保留所需运行库和对应第三方源码归档。不要直接把使用过的整个文件夹压缩上传。

原有读取器的历史验证记录保留在 `references/validation.json`，其样本结果不是对任意新游戏版本的兼容承诺。此次路径改造的验证记录与历史读取器报告分开。

## 许可与来源

本项目自有代码和说明采用 [GNU GPL v2](LICENSE)（GPL-2.0-only）；随附第三方组件保留各自许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。Unicorn 的对应源码归档随包保留。本项目是非官方工具，与游戏厂商无隶属关系；游戏文件不在本项目许可范围内。

