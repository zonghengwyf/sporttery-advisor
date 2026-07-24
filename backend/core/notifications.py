"""Webhook 通知模块 — 支持 Generic / 企业微信 / 钉钉 / 飞书"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def send_webhook(url: str, webhook_type: str, payload: dict) -> bool:
    """向指定 URL 发送 Webhook 通知，返回是否成功。"""
    body = _build_body(webhook_type, payload)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=body)
            r.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("Webhook 发送失败 (%s): %s", webhook_type, exc)
        return False


def _build_body(webhook_type: str, payload: dict) -> dict:
    text = payload.get("text", "")
    title = payload.get("title", "竞彩早报")

    if webhook_type == "wechat":
        return {"msgtype": "markdown", "markdown": {"content": f"## {title}\n{text}"}}

    if webhook_type == "dingtalk":
        return {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": f"## {title}\n\n{text}"},
            "at": {"isAtAll": False},
        }

    if webhook_type == "feishu":
        return {
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": title}},
                "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": text}}],
            },
        }

    # generic — 原样发送
    return payload


async def build_daily_briefing(matches: list[dict], predictions: list[dict]) -> dict:
    """将今日赛事 + 预测汇总成早报 payload。"""
    today = date.today().strftime("%m月%d日")
    title = f"竞彩早报 · {today}（共 {len(matches)} 场）"

    lines: list[str] = []
    pred_map = {p["match_id"]: p for p in predictions}

    for m in matches[:10]:  # 最多 10 场
        pid = m.get("id")
        pred = pred_map.get(pid, {})
        risk = pred.get("risk_label", "")
        risk_icon = {"mainline": "★", "guarded": "◆", "upset_cover": "◇", "avoid": "✗"}.get(risk, "·")

        line = f"{risk_icon} **{m.get('home_team')} vs {m.get('away_team')}**（{m.get('league', '')}）"
        sp_odds = m.get("sporttery_odds") or {}
        if sp_odds:
            line += f"  竞彩：{sp_odds.get('home','-')}/{sp_odds.get('draw','-')}/{sp_odds.get('away','-')}"

        fp = pred.get("fused_probs") or pred.get("stat_probs") or {}
        if fp:
            home_pct = fp.get("home", fp.get("home_win", 0))
            draw_pct = fp.get("draw", 0)
            away_pct = fp.get("away", fp.get("away_win", 0))
            line += f"  概率：{home_pct:.0%}/{draw_pct:.0%}/{away_pct:.0%}"
        lines.append(line)

    if len(matches) > 10:
        lines.append(f"…… 另有 {len(matches) - 10} 场未列出")

    text = "\n".join(lines) or "今日暂无赛事"
    return {"title": title, "text": text, "match_count": len(matches)}
