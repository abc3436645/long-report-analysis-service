# 江铜华北双模型报告差异调查

Status: ready-for-human

用户已确认Build。调查、场景/引擎修复及真实双模型起草修订已完成，提交Runtime检查与新的独立Verifier；业务签认仍待完成。

- [差异审查及已复现错误](../../docs/scenarios/财务公司授信评审-江铜华北双模型差异审查.md)
- [输入及交付哈希、PDF探测和复算证据](evidence.json)
- [变更范围及验收标准](../../docs/comet/changes/due-diligence-model-consistency/brief.md)
- [目标契约](../../docs/comet/changes/due-diligence-model-consistency/specs/financial-evidence-quality/spec.md)

## Comments

2026-10-30：用户选择新worktree，原目录数据只读引用。尚未修改产品代码、场景配置和主Skill，尚未重跑两款模型；调查阶段检查不能算修复后回归通过。

2026-10-30 Build：用户指定gpt-6.1-sol medium及gpt-6.1-terra medium。新报告通过标准发布链，旧材料只读保留；开发检查不替代最终Runtime与Verifier回执。参见[交付索引](deliverables/README.md)及[执行边界](experiment/FINAL_GATE.md)。
