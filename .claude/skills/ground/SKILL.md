---
name: ground
description: 把抽象的研究想法通过文献落地成具体的候选形式化。这是抽象想法的入口，在 /explore 建模之前用。用法：/ground <想法名或一段想法描述>
---

# /ground — 想法落地

输入：$ARGUMENTS

## 第一步：把想法写下来

- 若 `ideas/<想法名>.md` 已存在，读它；否则先跟用户对话，把想法记录成
  `ideas/<想法名>.md`。追问要少而准（3~5 个问题），例如：
  想刻画的核心现象是什么？谁在跟谁博弈、冲突/错位在哪？
  什么是外生的、什么是要内生解出来的？心目中的「理想定理」长什么样？
- 想法文件不求形式化，求**要素清楚**：现象、玩家、张力、理想结论。

## 第二步：文献侦察（派 scholar）

- 从想法要素生成 3~5 条检索线（例：平台与商家的动态定价 → two-sided
  markets / dynamic mechanism design / relational contracts / learning
  in repeated games），交给 **scholar** subagent。
- scholar 每条线找代表作与最近邻，写 `literature/papers/` 笔记，
  汇总成 `literature/maps/<想法名>.md` 文献地图。
- 文献量大时可分两轮：先 abstract 级扫描 10~20 篇定坐标，再挑 3~5 篇
  最近邻精读全文。

## 第三步：产出落地报告

写 `ideas/<想法名>-grounding.md`，核心是 **2~3 个候选形式化**，每个包含：

1. 模型要素草案（players、时序、信息结构、支付、解概念——到能交给
   modeler 的精度）；
2. 刻画了想法的哪部分、牺牲了哪部分；
3. 与最近邻文献 [bibkey] 的**逐条假设差异**——这就是新颖性声明的雏形；
4. 技术可行性预判：像哪个已知模型，可能借用什么证明技术，风险在哪。

外加：若 scholar 发现想法已被做过大半，如实报告重合度与剩余空间。

## 第四步：用户拍板 → 交接

- 报告给用户，等用户选定（或修改）一个候选。
- 选定后派 **modeler** 把它写成 `problems/<p>/model.md`（正常进入
  /explore → /conjecture → /attack 管线），并在 model.md 里链接
  grounding 报告与文献地图。

纪律：候选形式化里引用的每篇文献必须在 `literature/papers/` 有笔记；
新颖性声明只能说「在检索范围内未见」，并附检索线清单。
