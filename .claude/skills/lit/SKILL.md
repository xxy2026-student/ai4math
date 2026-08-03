---
name: lit
description: 文献检索与精读笔记：查一个主题、追一条引用线、或精读指定论文。用法：/lit <主题、问题或论文标识（arXiv 号/标题）>
---

# /lit — 文献检索与笔记

输入：$ARGUMENTS

1. 判断任务类型：
   - **主题检索**：派 scholar 沿 survey → 引用图收缩，产出/更新
     `literature/maps/<主题>.md` + 代表作笔记；
   - **精读单篇**：scholar 抓全文（arXiv HTML / ar5iv），写
     `literature/papers/<bibkey>.md` 精读笔记；
   - **追引用线**：从某篇已有笔记出发，用 Semantic Scholar 的
     citations/references 找前驱后继，扩充地图。
2. 已有笔记的论文不重复抓取，增量更新即可（frontmatter 的 accessed 刷新）。
3. 汇报：新增/更新的笔记清单、地图变动、以及「这对我们哪个想法/问题有什么用」
   ——文献工作必须挂回研究目标，不做无目的的收藏。

纪律同 scholar：禁止凭记忆引用；access-level 如实标注；
secondhand 的论文不得支撑具体论断。
