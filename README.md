# 长报告分析项目

一个主控 Skill、三个场景包和一个 Python 包。当前`0.1.0`是**M0配置骨架**：CLI 能从安装包读取并校验场景定义、计算算子引用、章节依赖和 Word 模板资源。完整报告生成、持久项目状态、补件改稿和发布仍按[首期实施蓝图](docs/首期实施蓝图-主控Skill与CLI三场景.md)实施；M0不代表首期工程验收通过。

## 安装与调用

需要 Python 3.12 或更新版本。在项目根目录运行：

```sh
python -m pip install .
report scenarios
report scenario budget_operations --version 0.1.0
report scenario credit_review --version 0.1.0
report scenario compensation_analysis --version 0.1.0
```

也可使用 `python -m long_report` 代替 `report`。命令成功时在 stdout 输出 JSON，含 `ok: true`、`capability: scenario_contract_only` 和 `data`；配置、版本或引用错误时在 stderr 输出 `ok: false`，退出码为 1。`report scenario` 返回四份配置和内容指纹，不依赖当前工作目录。

| 场景 ID | 用途 | 当前定义缺口 |
|---|---|---|
| `budget_operations` | 预算经营分析 | 预算版本规则、合并口径、计量单位 |
| `credit_review` | 财务公司授信评审 | 授信政策、专业来源接入、等级期限映射 |
| `compensation_analysis` | 人力薪酬分析 | 薪酬组成与期间、人数口径、人效公式、小样本阈值 |

配置在 `scenarios/<id>/`，每个场景有 `scenario.yaml`、`outline.yaml`、`analysis.yaml`、`quality.yaml` 和版本化 Word 模板。模板是版式起点，尚未接入报告渲染器。主控 Skill 的维护源是 [.agents/skills/long-report/SKILL.md](.agents/skills/long-report/SKILL.md)；Claude Code 入口链接到同一文件。场景配置只引用核心注册算子，不执行场景脚本。

## 开发验证

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
report scenarios
```

已有 `data/` 和 `results/` 可能含业务材料或生成结果，不纳入发行包；新运行项目放在被忽略的 `projects/` 下。三宿主完整报告验收、材料解析、项目更新及 MD/DOCX 生成尚未执行。Q59规定首期以合成服务验证通用南向HTTP/MCP来源契约，真实供应商联调另验；当前M0的三个场景均关闭检索，因为尚无执行器。上传专业记录不等于已完成实时接入。
