# 项目工作入口

每次开始项目任务时，先从仓库根目录列出项目维护的 skill 文档，再逐份完整阅读，然后开始设计、修改或验证。即使任务只涉及某个子目录，也要完成这一步。可使用以下命令发现文档：

```sh
rg --files --hidden --no-ignore -g 'SKILL.md' -g '!.git' -g '!node_modules' -g '!.venv' | sort
```

若客户端没有 shell 或未安装 rg，使用工作区文件搜索，包含隐藏目录，按文件名 SKILL.md 查找并读取。仅支持上传附件的客户端，由交接方提供本文件、搜索到的全部 skill 和任务涉及的各级 AGENTS.md。技能中的客户端专属操作按当前工具的等效能力执行，提交署名应符合实际参与者。

当前入口包括：

- [.agents/skills/scoped-engineering/SKILL.md](.agents/skills/scoped-engineering/SKILL.md)
- [.claude/skills/develop-this-project/SKILL.md](.claude/skills/develop-this-project/SKILL.md)

以每次发现的结果为准。先了解所有 skill 的适用范围，再按当前任务采用相关流程。涉及后端、前端或前端应用壳时，同时阅读从根目录到目标文件路径上各级的 AGENTS.md；跨目录任务覆盖每个涉及的分支。
