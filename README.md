# Bloomberg Morning X Automation

Bloomberg日本語公式Xアカウント `@BloombergJapan` の「今朝の5本」投稿を入口にして、毎朝6:30 JSTに要約投稿します。

投稿ルール:

- 先頭は `【サラリーマン必見】`
- 5項目の短いニュース要約
- 市場示唆は `↑↑買い目線` / `↓↓売り目線` の2行
- Bloomberg記事リンクを含める
- 280文字以内

## GitHub Actions版

`.github/workflows/morning-bloomberg-x.yml` が毎朝6:30 JSTに動きます。

GitHubの `Settings > Secrets and variables > Actions` に以下を登録します。

Secrets:

- `X_BEARER_TOKEN`
- `X_API_KEY`
- `X_API_KEY_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`
- `OPENAI_API_KEY`

Variables:

- `OPENAI_MODEL`: 省略可。既定値は `gpt-5-mini`
- `DRY_RUN`: テスト時は `1`、本番投稿は `0`

## ローカル投稿テスト

```powershell
python .\post_to_x.py .\post_2026-05-22.txt
```

## 注意

`.env` はローカル用の秘密ファイルです。GitHubにはアップロードしません。
