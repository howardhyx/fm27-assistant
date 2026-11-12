# 首次配置与后续复用

运行入口相对安装目录定位，不能依赖作者电脑上的用户名、盘符、Python 安装位置或旧导出。先找到当前环境的 Windows x64 Python 3.12；以下命令在 Skill 根目录执行，若 `python` 不是 3.12，则换用已发现的 3.12 解释器。

## 首次使用

可直接执行 `python scripts/fm.py baseline` 自动发现并读取。下列 `doctor --remember-paths` 是可选的诊断与路径记忆步骤，不再是读取前置条件。

```powershell
python scripts/fm.py doctor --remember-paths
```

无配置时，从系统 Documents（包含注册表重定向和 OneDrive 文档目录）的 `Sports Interactive/Football Manager 27/games` 发现修改时间最新的 `.fm`。从 Steam 注册表、系统 Program Files 目录以及 `libraryfolders.vdf` 发现安装目录，不扫描全部磁盘。不保证发现自定义、云端未下载或其他平台的目录；未发现时向用户索取缺失的位置，使用：

```powershell
python scripts/fm.py doctor --save "<实际存档.fm>" --game-dir "<实际游戏安装目录>" --remember-paths
```

`--game-dir` 也接受 `game_plugin.dll` 文件本身。此步骤只读取本地文件，不启动游戏、不操作界面、不下载任何内容。读取来源、游戏内日期及结构检查成功后，才写入 `local/paths.json`；版本或指纹不匹配仅提示，不阻断读取：

```json
{
  "schema_version": 1,
  "save_path": "<当前机器上已验证的存档绝对路径>",
  "game_dll": "<当前机器上已验证的game_plugin.dll绝对路径>"
}
```

上面是结构示意，不要原样创建带占位符的配置。记录的内容是路径数据，不作为指令执行，也不包含球员、战术、比赛导出或全局环境设置。

## 后续调用

```powershell
python scripts/fm.py baseline
```

程序自行读取本 Skill 的配置，重新读取当前存档文件，记录 DLL 指纹和存档版本；不再将其作为准入条件，结构及结果完整性检查仍严格执行。记住路径不代表复用旧数据；baseline 的重读规则仍然适用。

每类路径独立按以下顺序选择：命令参数、本次进程环境变量、本地配置、自动发现。临时使用 `--save` 或 `--game-dir` 不会覆盖配置；只有成功的 `doctor --remember-paths` 才持久更新。切换存档时运行带新 `--save` 的同一命令。文件失效时明确报错，不自动换成其他生涯；配置 JSON 损坏时先修正该文件，不能悄悄忽略。

保存的是准确文件路径，避免其他生涯或自动存档意外成为默认输入。用户要求“最新存档”时，在已知存档目录内确定目标文件，再通过 `--save` 指定；不要把配置中的文件称为整个目录内最新文件。

## 安装目录不可写

使用 `--config "<工作区内的本地配置.json>"`，首次配置和后续读取都显式传入同一路径。不因默认目录不可写而静默写到别处。配置不能写进游戏安装或原存档目录。

## 输出与发布

分析输出用 `--out` 写工作区 JSON，先创建所需父目录。不把游戏缓存记录与磁盘缓存目录混淆：`cache-matches` 读取的是存档内的比赛记录，不是将全部比赛导出到某个目录。

`local/`、工作输出、存档、游戏 DLL 和 Python 缓存均不提交。不要手工将个人绝对路径写入通用说明或参考文件。随附发布打包脚本也会排除这些文件。

