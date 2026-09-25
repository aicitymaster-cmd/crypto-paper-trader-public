# 仮想通貨・PAPER検証用の安全な土台（試作）

- AI CITY本体とは別リポジトリです。
- 本公開版は**PAPER専用**です。実口座、実注文、送金、出金、レバレッジ、先物、空売りの機能はありません。
- APIキー、パスワード、秘密鍵、口座情報、個人情報は使いません。
- 公開情報の取得は、承認済みの固定HTTPS公開エンドポイントへの**GETのみ**を許す境界に限定します。認証付きAPIや書き込み通信はありません。
- GitHub Actionsの監査ワークフローは `permissions: {}` で、外部PR起動や第三者Actionを使いません。
- 利益を保証するシステムではありません。まず仮想売買で検証します。

## Security

ローカルの公開候補パッケージで実施済み:
- `python security_guard.py .` -> `SECURITY_GUARD_OK`
- `python -m unittest discover -q` -> 236 tests, OK

GitHub上の公開版は、投入後に別途GitHub Actionsで再検証してからPAPER運転を有効化します。

詳細は `SECURITY.md` と `SECURITY_AUDIT_PUBLIC.md` を参照してください。

## 重要

実資金への接続・認証・実注文は、この公開リポジトリの対象外です。
