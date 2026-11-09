# 丹麦博物馆速查

聚合丹麦各博物馆的开放时间、票价和当前展览。纯静态站点，GitHub Actions 每天用 Playwright 读取官网页面，规则解析开放时间/票价/优惠/展览（无需任何付费 API）并发布到 GitHub Pages。

- `scraper/museums.yaml` — 博物馆配置（地址、开放时间、票价、展览页抓取规则）。新增博物馆在这里加一项即可。
- `scraper/scrape.py` — 抓取脚本，输出 `data/museums.json`；某馆抓取失败时保留旧数据并标记 stale。
- `site/` — 前端（按日期/周末/丹麦公共假日筛选）。
- `.github/workflows/update.yml` — 每天 05:00 UTC 定时运行并部署。

本地预览（需 `pip install -r requirements.txt && playwright install chromium`；`--dump DIR` 可保存页面文本调试规则）：`python3 scraper/scrape.py && mkdir -p site/data && cp data/museums.json site/data/ && cd site && python3 -m http.server`

首次部署：仓库 Settings → Pages → Source 选 "GitHub Actions"。

解析失败的字段会保留上次的值；规则失效（网站改版）时该馆显示“可能不是最新”。调试某个馆：`python scraper/scrape.py --only smk --dump /tmp/dump`。
