# 仮想通貨・仮想売買の安全な土台（試作）

- AI CITYと無関係のオフライン試作です。取引所への接続、APIキー、実際の売買注文、外部通信、自動起動、AIモデルの呼び出しは**ありません**。
- 入力する価格と独立情報源の判断は仮の値です。利益が出る売買方法を作成・検証したものではありません。
- 本公開版はPAPER専用です。実口座・送金・出金・レバレッジ・先物・空売りの機能はありません。
- GitHub Actionsの監査ワークフローは `permissions: {}` で、外部PR起動や第三者Actionを使いません。

## Security

公開前のローカル監査:
- `python security_guard.py .` -> `SECURITY_GUARD_OK`
- `python -m unittest discover -q` -> 236 tests, OK

詳細は `SECURITY.md` と `SECURITY_AUDIT_PUBLIC.md` を参照してください。

## 重要

このコードは安全性とPAPER検証のための試作であり、利益を保証しません。
実資金への接続・認証・実注文は含めていません。