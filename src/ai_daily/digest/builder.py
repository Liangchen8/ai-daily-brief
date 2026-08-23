from __future__ import annotations

from datetime import date

from ..models import ContentItem, EventCluster, NewsAnalysis, PaperAnalysis, SocialAnalysis


class DigestBuilder:
    def build(
        self,
        *,
        report_date: date,
        news_clusters: list[EventCluster],
        news_analyses: list[NewsAnalysis],
        papers: list[ContentItem],
        paper_analyses: list[PaperAnalysis],
        social: list[ContentItem],
        social_analyses: list[SocialAnalysis],
        conflicts: list[str] | None = None,
        watchlist: list[str] | None = None,
        metrics: dict | None = None,
    ) -> str:
        news_by_id = {analysis.cluster_id: analysis for analysis in news_analyses}
        paper_by_id = {analysis.item_id: analysis for analysis in paper_analyses}
        social_by_id = {analysis.item_id: analysis for analysis in social_analyses}
        lines = ["# AI Daily Brief", "", report_date.isoformat(), ""]
        lines += ["## 🔥 今日最重要 AI 新闻 Top 5", ""]
        if news_analyses:
            for index, analysis in enumerate(news_analyses[:5], start=1):
                cluster = next((cluster for cluster in news_clusters if cluster.id == analysis.cluster_id), None)
                score = cluster.heat_score if cluster else 0
                lines += [f"### {index}. {cluster.title if cluster else analysis.cluster_id}", f"Heat Score：{score:.2f}", "", f"**发生了什么**：{analysis.what_happened}", f"**为什么重要**：{analysis.why_it_matters}", f"**关键观点**：{'；'.join(analysis.key_points)}", f"**AI 产品经理视角**：{analysis.product_implication}", "", "来源：" + "；".join(f"[{url}]({url})" for url in analysis.source_urls), ""]
        else:
            lines += ["本次没有完成新闻 LLM 深度分析；未配置可用模型密钥，未生成推测性摘要。", ""]
            raw_news = [item for cluster in news_clusters for item in cluster.items][:5]
            lines += [f"- {item.title}（Heat Score：{item.heat_score:.2f}，来源：{item.source}，[{item.url}]({item.url})）" for item in raw_news]
            lines.append("")
        lines += ["## 📄 今日值得读 AI 论文 Top 5", ""]
        if paper_analyses:
            for index, analysis in enumerate(paper_analyses[:5], start=1):
                item = next((item for item in papers if item.id == analysis.item_id), None)
                lines += [f"### {index}. {item.title if item else analysis.item_id}", f"Paper Score：{item.heat_score:.2f}" if item else "Paper Score：N/A", "", f"**解决什么问题**：{analysis.problem}", f"**过去方案**：{analysis.previous_method}", f"**核心创新**：{analysis.innovation}", f"**实验结果**：{analysis.experiment_result}", f"**限制**：{analysis.limitations}", f"**实际产品价值**：{analysis.product_implication}", f"论文链接：[{analysis.source_url}]({analysis.source_url})"]
                if analysis.github_url:
                    lines.append(f"GitHub：[{analysis.github_url}]({analysis.github_url})")
                lines.append("")
        else:
            lines += ["本次没有完成论文 LLM 深度分析；未配置可用模型密钥，未生成推测性摘要。", ""]
            lines += [f"- {item.title}（Paper Score：{item.heat_score:.2f}，[{item.url}]({item.url})）" for item in papers[:5]]
            lines.append("")
        lines += ["## 🧠 AI 大牛观点 Top 5", ""]
        if social_analyses:
            for index, analysis in enumerate(social_analyses[:5], start=1):
                lines += [f"### {index}. {analysis.author}", f"**原始观点**：{analysis.original_view}", f"**核心观点**：{analysis.core_argument}", f"**为什么值得关注**：{analysis.why_it_matters}", f"**事实或观点**：{analysis.fact_or_opinion}", f"原帖：[{analysis.source_url}]({analysis.source_url})", ""]
        else:
            lines += ["本次没有完成社交观点 LLM 分析；未配置可用模型密钥，未生成推测性观点。", ""]
            lines += [f"- {item.author or item.source}：{item.content[:160]}（[{item.url}]({item.url})）" for item in social[:5]]
            lines.append("")
        lines += ["## ⚔️ 今日观点冲突", ""]
        lines += [*(conflicts or ["未发现已验证的明显观点冲突。"]), ""]
        lines += ["## 🎯 今天只看 3 件事", ""]
        fallback_watchlist = watchlist or [cluster.title for cluster in news_clusters[:3]] or [item.title for item in papers[:3]]
        lines += [f"- {item}" for item in fallback_watchlist[:3]] or ["- 当前没有完成可供提炼的入选内容。"]
        lines.append("")
        if metrics:
            lines += ["## 运行诊断", "", "```text"]
            lines += [f"{key}: {value}" for key, value in metrics.items()]
            lines += ["```", ""]
        return "\n".join(lines)
