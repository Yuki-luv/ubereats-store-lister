"""
Uber Eats Japan スクレイピングモジュール
scrape_worker.py をサブプロセスとして起動し、結果を受け取る
"""
import json
import subprocess
import sys
import os
import tempfile

def run_scraper(
    address_query: str,
    max_stores: int = 50,
    exclude_chains: bool = False,
    progress_callback=None,
    status_callback=None,
    exclude_urls: list = None
) -> list[dict]:
    """
    別プロセスでスクレイパーを実行して結果を取得する。
    """
    worker_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scrape_worker.py")
    
    # Windows で UTF-8 を強制するための環境変数
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    
    cmd = [sys.executable, "-X", "utf8", worker_script, address_query, str(max_stores)]
    if exclude_chains:
        cmd.append("--exclude-chains")
    
    tmp_file = None
    if exclude_urls:
        # 除外URLリストを一時ファイルに書き出す
        fd, tmp_path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(list(exclude_urls), f)
            cmd.extend(["--exclude-file", tmp_path])
            tmp_file = tmp_path
        except Exception:
            pass

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=os.path.dirname(os.path.abspath(__file__)),
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1
        )
        
        stores = []
        total_count = 0
        
        # リアルタイムで出力を読む
        if process.stdout:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    msg = json.loads(line)
                    msg_type = msg.get("type", "")
                    
                    if msg_type == "status" and status_callback:
                        status_callback(msg.get("message", ""))
                    elif msg_type == "result":
                        stores = msg.get("data", [])
                        total_count = msg.get("total_count", 0)
                    elif msg_type == "error":
                        if status_callback:
                            status_callback(f"エラー: {msg.get('message', '')}")
                except json.JSONDecodeError:
                    continue
                except Exception:
                    continue
            
        process.wait()
        
    except Exception as e:
        if status_callback:
            status_callback(f"スクレイパーの起動に失敗しました: {str(e)}")
        return []
    finally:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except:
                pass

    return stores, total_count if 'total_count' in locals() else len(stores)
