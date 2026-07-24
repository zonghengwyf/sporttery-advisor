# China Sporttery Market Mapping And Output

Use this reference when turning match analysis into executable China Sporttery advice.

## Market Language

- 胜平负: regulation-time home win/draw/away win.
- 让球胜平负: apply the listed handicap to the home team first, then settle home win/draw/away win.
  - Example: `主+2`; if home loses by 1, result is 主胜; loses by exactly 2, result is 平; loses by 3+, result is 主负.
  - Example: `主-1`; if home wins by 2+, result is 主胜; wins by exactly 1, result is 平; draw/loss is 主负.
- 比分: exact regulation-time score unless the market states otherwise.
- 总进球: total regulation-time goals.
- 半全场: half-time result plus full-time result.
- 混合过关: combine different Sporttery market types across matches; avoid too many fragile legs.

## Single-Match Output Template

Use this compact shape:

```text
### 西班牙 vs 沙特
倾向: 主胜 / 让胜(若主-1) / 总进球 2-4
信心: 68/100, 可做串关主腿
出线/控分影响: 若已出线或只需小胜，降低让胜和大比分权重
状态/异常赛果解释: 上轮强队被逼平是控分/状态差/战术克制/偶然之一；据此决定是否防平或跳过
理由: ...
比分: 2-0, 3-0, 2-1; 防冷 1-1
不买条件: ...
```

## Multi-Match Ticket Template

Use 2-4 tickets, not one all-or-nothing ticket:

```text
稳健票:
- A场 胜平负: 主胜
- B场 让球胜平负: 主+1 胜/平 或 胜平负 双选
- C场 胜平负: 主胜
- 资金: 60%
- 逻辑: ...

均衡票:
- ...

博高赔票:
- ...

比分小注:
- A场 2-0/3-0
- B场 1-1/2-1
- C场 2-0/2-1
```

## Strategy Rules

- Use favorites as parlay anchors only when lineup and odds agree.
- Use handicap markets to protect against favorite narrow wins or underdog narrow losses.
- Avoid putting three volatile outcomes into one main ticket.
- If one match has high uncertainty, isolate it in a small-stake ticket instead of forcing it into every parlay.
- For exact scores, cluster around tactical expectation: low block = 1-0/2-0/2-1; open match = 2-1/3-1/2-2; weak favorite motivation = 1-1/1-0/2-1.
- When group-table incentives create 控分/挑对手 risk, downgrade handicap wins, big-score parlays, and over bets; prefer ordinary win, draw cover, under/low total goals, or skip.
- If two teams both benefit from a draw or narrow result, avoid using either side as a main parlay anchor unless odds clearly compensate.
- If a favorite recently failed against a weaker team for form/tactical reasons, do not use it as a conservative parlay anchor; use 胜/平 protection, handicap against the favorite, or skip.
- If an underdog recently held a favorite for repeatable reasons, upgrade its 让球 protection and draw cover in the next match.
- If a surprising result was likely control scoring, keep the next-match attacking upside only when the group table now rewards winning or goal difference.
- State "临场阵容出来后复核" when star players, goalkeeper, or rotation risk matters.

## Suggested Stake Allocation

If no budget is provided:

- 60% conservative ticket.
- 25% balanced ticket.
- 10% high-odds cover.
- 5% exact-score small stake.

If the user gives a budget, convert percentages to units and keep exact-score exposure small.
