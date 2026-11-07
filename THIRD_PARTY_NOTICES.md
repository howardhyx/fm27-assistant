# 第三方组件

第三方组件保持各自版权及许可；根目录 LICENSE 不替换其已有许可。发布包保留下列文件及元数据。

| 组件 | 版本或用途 | 许可与随包文件 |
|---|---|---|
| [fmsave](https://github.com/rhiever/fmsave) | 0.10.0，存档结构读取 | MIT；`scripts/vendor/fmsave-0.10.0.dist-info/licenses/LICENSE` |
| [backports.zstd](https://github.com/rogdham/backports.zstd) | 1.8.0，Zstandard 解压 | `scripts/vendor/backports_zstd-1.8.0.dist-info/licenses/LICENSE.txt` 及 `LICENSE_zstd.txt`，包含 Python/Zstandard 等上游声明 |
| [Unicorn](https://github.com/unicorn-engine/unicorn/tree/2.1.4) | 2.1.4，隔离虚拟 CPU | GPL v2；`references/licenses/unicorn-COPYING.txt`；对应源码 `references/licenses/unicorn-2.1.4-source.tar.gz`；Python 包和 DLL 保持原样 |
| [fm-tactics-lab](https://github.com/lqf0624/fm-tactics-lab) | 指令/角色目录和部分字段参考 | MIT；`references/licenses/fm-tactics-lab-LICENSE.txt` |

Unicorn 对应源码归档 SHA256：`00567a70e323f749b419cd86bee4f9115beab7ebba32194581c090cbb7c59cff`。原有许可、来源与技术说明亦见 `references/maintenance.md`。游戏 DLL 由使用者自己的安装提供，本发布包不包含该文件。

## 研究工具

研究阶段使用了 [Capstone](https://github.com/capstone-engine/capstone) 查看机器指令，辅助追踪原生字段、战术对象及修改队列。最终工具包未分发 Capstone，其运行入口也不依赖它；这里作为研究工具致谢列出。
