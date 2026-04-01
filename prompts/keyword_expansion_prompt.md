# 关键词扩展提示词模板

你正在帮助电池研究者构建高精度文献检索画像。
仅返回严格 JSON，不要返回其他说明文字。

## 输入
- 研究主题：{{TOPICS}}
- 必含方法学词：{{MUST_HAVE_TERMS}}
- 排除词：{{EXCLUDE_TERMS}}
- 目标期刊：{{TARGET_JOURNALS}}
- 时间窗口：{{TIME_WINDOW}}

## 任务
围绕“水系锌离子电池 Zn 负极界面机制”生成并迭代关键词组。
优先保证机制证据召回，而非仅性能指标表述。

## 输出 JSON 模板
{
  "core_groups": [
    {
      "name": "string",
      "terms": ["string"],
      "reason": "string"
    }
  ],
  "must_have_logic": {
    "mode": "at_least_n",
    "n": 2,
    "terms": ["string"]
  },
  "exclude_logic": {
    "terms": ["string"],
    "notes": "string"
  },
  "journal_bias": {
    "tier_1": ["string"],
    "tier_2": ["string"],
    "tier_3": ["string"]
  },
  "queries": {
    "broad": "string",
    "balanced": "string",
    "strict": "string"
  },
  "quality_checks": [
    "string"
  ]
}

## 硬性约束
- 聚焦以下 3 个机制问题：
  1) Zn2+ 界面发生了什么变化？
  2) HER 是如何被抑制的？
  3) NH3 或 acetate 化学体系具体改变了哪一步？
- 避免只体现性能而缺乏机制证据的检索词。
- 必须覆盖同义词、缩写和常见变体写法。
