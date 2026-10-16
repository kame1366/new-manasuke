# Manasuke — 招待制テスト公開用

このリポジトリはStreamlit / SQLite / OpenAI APIによる学習計画PoCです。**一般公開を想定した認証・運用基盤ではありません。** 少人数の招待制テストに限定し、参加者ごとに異なるアクセスキーを渡してください。

## 初回セットアップ

1. Python 3.13以上を用意し、`uv sync`（または `pip install -e .`）で依存ライブラリをインストールします。
2. `.env.example` を `.env` にコピーし、`OPENAI_API_KEY`、`OPENAI_MODEL` と `MANASUKE_DB_PATH` を設定します。`.env` はGitへコミットしないでください。
3. 参加者用のIDとランダムなキーをそれぞれ用意し、`MANASUKE_INVITE_KEYS_JSON` を設定します。**全員に同じキーを渡さないでください。**
4. 新規DBには `uv run python -m scripts.migrate data/manasuke.db` でMigrationを適用します（既存DBについてはMigration履歴を確認し、バックアップのうえ適用）。
5. `uv run python -m scripts.import_participant examples/participant.sample.json data/manasuke.db` のCLI仕様を確認し、参加者IDをDBに登録します。ログインは**DBに存在するIDのみ**可能です。
6. `uv run streamlit run app.py` で起動します。

### 開発用ダミーデータの投入

ローカル確認用に、学習対象・Goal・空き時間を含むダミー参加者を3件投入できます。

```bash
uv run python -m scripts.seed_dummy_data data/manasuke.db
```

件数と参加者IDの接頭辞は変更できます。既に同じIDが存在する場合は重複エラーになります。

```bash
uv run python -m scripts.seed_dummy_data data/manasuke.db --count 10 --prefix demo-user
```

### 招待キーの生成

各参加者についてローカルのターミナルで以下を実行し、異なるキーを発行してください。

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

`.env` の例（キーはあくまでダミー）：

```dotenv
MANASUKE_INVITE_KEYS_JSON='{"student-a":"REPLACE_WITH_A_RANDOM_SECRET_001","student-b":"REPLACE_WITH_A_DIFFERENT_SECRET_002"}'
```

参加者には「参加者ID」と「その人専用のキー」だけを個別に伝えます。`MANASUKE_EXPERIMENT_ACCESS_KEY`（旧・共通キー）は認証に使用されません。キーを変更した場合、**既存ログインセッションは自動的に失効しません**。セッションを破棄するため、Streamlitプロセスを再起動し、参加者に再ログインを案内してください。

## 公開前の確認（Go / No-Go）

- [ ] 招待者Aのキーでは招待者BのIDでログインできない
- [ ] `.env`、APIキー、招待キー、参加者DBがGitや公開ファイルに含まれていない
- [ ] 参加者DBは永続ディスク上にあり、バックアップ／復元手順がある
- [ ] 公開はHTTPSを経由し、管理画面やサーバーのファイルは外部から見えない
- [ ] 新規StudyTarget・LearningPolicy・Goal・利用可能時間の登録→計画生成→学習結果の登録が一巡できる
- [ ] 計画生成のボタンを何度押しても二重Attemptが発生しない
- [ ] GoalのSTRICT/BEST_EFFORT選択が必要なケースを試した
- [ ] 別参加者でログインし、他人のGoal・予定・実績が表示されない
- [ ] APIエラー／無理な期限設定のとき、エラー内容がユーザーに分かる（スタックトレースは出ない）
- [ ] テストユーザーに生成計画の分かりやすさと実行可能性を聞いた

## テスト

```bash
uv run python -m pytest -q
```

公開前には**全テストの通過が必要**です。AIの実応答、Streamlit UI、HTTPS、ディスク永続化、複数ユーザー同時利用はローカルのユニットテストだけでは確認できません。

## 既知の制限・注意

- AIはOptionalな時間配分の提案を行い、締切やHard ConstraintはPython側で処理します。**学習にとっての「良い計画」を保証するものではありません**。最終的には学習者の評価を集めて改善します。
- 学習設定タブは登録と閲覧を分類しましたが、単一ページのコードは大きいままです。構造の大改修はテスト公開後に進めます。
- 認証には招待者別キーを使いますが、レート制限、失効管理、監査ログ、法令・プライバシー対応など、一般公開用の完全なユーザー管理は未実装です。
- 最新のPlanの設定Versionが変わった場合は再計画が必要なことを案内しますが、完全なOUTDATED_VALID/INVALIDの自動判定は別課題です。
- 計画生成がGoal判断待機中になっている間に設定が変更された場合、続行に失敗し、再度計画を作る必要があります。
