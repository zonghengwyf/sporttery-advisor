---
name: china-sporttery-football-advisor
description: Build China Sporttery football betting advice for user-named matches, especially World Cup or international fixtures. Use when the user asks how to buy Chinese sports lottery football markets such as 胜平负, 让球胜平负, 比分, 总进球, 半全场, 单关, 串关, 混合过关, 竞彩, 中国体彩, 体彩, or asks which match outcomes and scorelines are more likely to make money. The workflow combines China Sporttery fixed odds, 海外博彩网站赔率, bookmaker odds, exchange/prediction-market signals, recent team form, 弱队逼平强队后的真实原因, 伤停, player availability and condition, tactical matchup, schedule/travel/rest, group standings, 小组出线形势, 潜在淘汰赛对手, 控分/挑对手动机, cross-group upset patterns, weather, venue, and off-field factors, then converts the evidence into executable Sporttery-style strategies.
---

# China Sporttery Football Advisor

Use this skill to answer football betting questions in the language of China Sporttery markets, not generic football predictions. The goal is to turn evidence into playable options while being explicit about uncertainty, downside, and which matches should be skipped.

## Operating Rules

- Treat the user as asking about China Sporttery/竞彩 unless they clearly request another market.
- Identify the exact market first: 胜平负, 让球胜平负, 比分, 总进球, 半全场, 单关, 串关, or 混合过关. If a handicap like `主+1`, `客-1`, or `让球胜平负` appears, decode settlement before recommending picks.
- Browse or otherwise verify current information before giving picks. Current odds, injuries, lineups, suspensions, team news, and weather are time-sensitive.
- Prefer official or primary sources for China Sporttery odds, squad lists, suspensions, fixture time, and weather. Use reputable odds aggregators or bookmakers for overseas odds.
- Separate 90-minute results from advancement/qualification outcomes. China Sporttery football match-result markets usually settle on regulation time unless the market states otherwise.
- In tournaments, verify current group standings, tiebreakers, possible knockout opponents, and whether either team benefits from a draw, narrow loss, lower scoring pace, rotation, or avoiding a specific bracket route.
- When a recent match contains a surprising draw/upset, classify why it happened before upgrading or downgrading either team. Do not treat "weak team held a strong team" as one automatic signal; separate strong-team control scoring, poor form, missing players, tactical mismatch, goalkeeper variance, red cards, penalties, weather, and real underdog strength.
- Never present a bet as guaranteed. Use probability bands and risk tiers. Include at least one "avoid/skip" call when the evidence is too noisy.
- If the user asks "怎么大概率挣钱", answer with risk-managed strategy, not a promise of profit.
- When data is missing, say what was unavailable and lower confidence instead of inventing details.

## Workflow

1. Normalize matches.
   - Resolve team names, kickoff date/time, competition, neutral/home venue, and whether the user means today's matches in their timezone.
   - If the teams could refer to multiple matches, ask only when the ambiguity changes the betting answer; otherwise state the assumption.

2. Gather data.
   - China Sporttery fixed odds and available markets for each match.
   - Overseas 1X2, Asian handicap, totals, and scoreline odds when available.
   - Recent form: last 5-10 matches, opponent quality, home/away or neutral split, xG or shot quality if available; explain abnormal results instead of only listing scorelines.
   - Team state: injuries, suspensions, likely XI, player minutes, fatigue, star-player form, goalkeeper status, set-piece specialists.
   - Context: motivation, tournament group situation, tiebreakers, likely next-round opponents, rotation incentives, travel/rest, weather, pitch, altitude, referee style, media/off-field issues, and whether other group matches show that "weak" teams are broadly overperforming.
   - Market movement: opening vs current odds, odds divergence between China Sporttery and overseas books, public heat when visible.

3. Score evidence.
   - Read `references/factor-model.md` when choosing weights, confidence, and upset flags.
   - Read `references/tournament-incentives.md` for World Cup/group-stage matches, final-round group matches, already-qualified teams, or any match where choosing a bracket route could affect team behavior.
   - Read `references/form-context.md` whenever either team recently drew/beat a stronger opponent, failed against a weaker opponent, had unusual xG/shot/keeper numbers, or the user asks whether "状态不好" or "控分" explains a result.
   - Label each match as mainline, guarded, upset-cover, or avoid.
   - Identify value only when probability and payout both support it; a likely result is not automatically a good bet.

4. Map to Sporttery plays.
   - Read `references/sporttery-output.md` for market mapping and output shape.
   - Produce at least: 胜平负/让球胜平负 lean, scoreline cluster, total-goals lean, and whether the match belongs in mixed parlays.
   - For multiple matches, output 2-4 tickets: conservative, balanced, higher-odds, and scoreline/small-stake cover.

5. Explain briefly.
   - Keep evidence compact and decision-oriented.
   - Tie every pick back to specific factors, odds value, and settlement mapping.
   - Include stake allocation as percentages or units when the user asks how to buy.

## Default Output

For a request like "今天西班牙沙特、伊朗埃及、乌拉圭佛得角这三场该怎么买能够大概率挣钱", respond in Chinese with:

1. **先翻译市场**: competition/date assumptions, each match's available Sporttery markets, and any handicap settlement.
2. **出线/控分影响**: group table, tiebreakers, next-round opponent route, and whether either team has incentive to rotate, slow the game, accept a draw, avoid overexposure, or protect a narrow result.
3. **状态/异常赛果解释**: identify whether recent surprising results came from real underdog strength, strong-team poor form, control-scoring incentives, key-player issues, tactical mismatch, or variance; include same-tournament weak-vs-strong patterns.
4. **单场判断**: for each match, give recommended markets, likely scorelines, total-goals lean, confidence, and avoid conditions.
5. **混合过关策略**:
   - 稳健票: lower odds, fewer legs, more double-choice/handicap protection.
   - 均衡票: main opinion with one guarded leg.
   - 博高赔票: small stake only, include draw/upset or exact-score cover.
   - 比分小注: 2-4 exact scores per match or selected matches only.
6. **资金分配**: default 60%稳健, 25%均衡, 10%博高赔, 5%比分, unless the user gives a budget.
7. **不买条件**: lineup surprise, odds crash, abnormal handicap move, poor weather, missing key player, unresolved abnormal-form signal, or a group-table scenario that makes the favorite less motivated to win big.

## Sources To Prefer

- China Sporttery official fixture/odds pages or trustworthy mirrors for fixed odds and available markets.
- FIFA, confederation, league, national-team, club, or competition official pages for squads, suspensions, and fixtures.
- FIFA/competition official standings, tiebreaker rules, bracket maps, and same-group kickoff timing when tournament incentives may affect behavior.
- Bookmaker/odds aggregators for overseas odds: Bet365, Pinnacle, OddsPortal, Flashscore, Sofascore, FotMob, Transfermarkt, FBref, Opta-style feeds where accessible.
- Weather services for match venue forecasts.
- Reputable news sources for injuries, coach comments, and off-field factors.

## Installed Context

This skill was designed as a China Sporttery-focused layer inspired by public `sporttery-advisor-skill` style workflows, then expanded for overseas odds, form, player status, and context factors. It should not depend on that repository being installed.
