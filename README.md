\# Picking ToDo with GitHub Backup



ピッキング ToDo v4.9.9 をベースに、FastAPI + Git を使った

`backup.json` 自動コミット機能を追加した構成です。



\## 構成



\- `frontend/index.html`

&nbsp; - GitHub Pages などで公開するフロントエンド

\- `backend/app/main.py`

&nbsp; - FastAPI + GitPython バックエンド

&nbsp; - `/api/backup` で `backup.json` の読み書きを提供



\## フロントエンドの使い方



1\. `frontend/index.html` を GitHub Pages で公開

2\. コード内の `API\_BASE` をバックエンドのURLに合わせて変更

3\. ブラウザからページにアクセス

4\. 「サーバーから読込」「サーバーへ保存」ボタンでバックエンドと連携



\## バックエンドの起動



```bash

cd backend

pip install -r requirements.txt



export REPO\_PATH=..                # このリポジトリのルート

export REPO\_BRANCH=main

export API\_TOKEN=your-secret-token # 任意。未設定なら認証スキップ



uvicorn app.main:app --reload --host 0.0.0.0 --port 8000



