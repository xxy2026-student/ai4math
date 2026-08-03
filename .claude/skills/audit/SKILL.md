---
name: audit
description: skeptic 独立审计一条证明草稿；通过后才能把猜想标为 proved 并登记引理。用法：/audit <C-编号或猜想文件路径>
---

# /audit — 独立审计

输入：$ARGUMENTS

1. 派 **skeptic** subagent。给它的输入**只有**：猜想陈述、证明草稿全文、
   model.md 路径。不要转述 prover 的意图、不要附上你对证明的评价——
   审计的价值全在独立性。
2. skeptic 把审计写入 `problems/<p>/audits/<id>-audit-<日期>.md`，
   结论为 PASS 或 FAIL（漏洞清单）。
3. **PASS** → 主 agent：
   - 猜想文件 frontmatter 加 `audit: <审计文件路径>`，status 改为 proved
     （hook 会核验审计文件存在）；
   - 在 `lemmas/L-xxx.md` 登记引理卡片：陈述、依赖假设、指向证明与审计的链接，
     frontmatter `status: proved` + 同样的 audit 字段。
4. **FAIL** → 漏洞清单原样汇报给用户；重大漏洞建议开新一轮 /attack，
   小漏洞可让 prover 修补后**重新走一遍 /audit**（新审计文件，不覆盖旧的）。
5. 同一猜想的每轮审计都留档：audits/ 下按日期编号，形成审计历史。
