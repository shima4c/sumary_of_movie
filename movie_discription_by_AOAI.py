import os
import time
import json
import requests
import ffmpeg
import shutil
from openai import AzureOpenAI
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient

# .envのファイルを読み込む
load_dotenv()

# ====== 環境変数読み込み ======
# Azure Speech環境変数
SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
SPEECH_REGION = "japaneast"          # Bach Transcription対応リージョンを使用
SPEECH_API_VERSION = "2024-11-15"           # 例：Speech to Text APIのバージョン

# Azure OpenAI環境変数
OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
OPENAI_ENDPOINT = "https://test-ej-ml-openai.openai.azure.com/" # ：Visuamallで利用のAzure OpenAIリソースのエンドポイント
OPENAI_DEPLOYMENT = "gpt-4.1"           # AOAIのモデル(Deployment)名
OPENAI_API_VERSION = "2025-03-01-preview"   # 例：AOAIのAPIバージョン

# Azure Blob Storage環境変数
BLOB_ACCOUNT_NAME = os.getenv("BLOB_ACCOUNT_NAME")  # ストレージアカウント名
BLOB_ACCOUNT_KEY = os.getenv("AZURE_STORAGE_KEY")  # アクセスキー
BLOB_CONTAINER_NAME = "speek2text"              # コンテナ名
BLOB_CONTAINER_RESULT = "result"        # 結果コンテナ名

# ====== 接続文字列を生成 ======
connection_string = (
    f"DefaultEndpointsProtocol=https;"
    f"AccountName={BLOB_ACCOUNT_NAME};"
    f"AccountKey={BLOB_ACCOUNT_KEY};"
    f"EndpointSuffix=core.windows.net"
)

# ====== 設定 ======
MOVIE_DIR = "movies/"           # 動画ファイルディレクトリ
AUDIO_DIR = "audios/"           # 音声ファイルディレクトリ
TRANSCRIPT_DIR = "transcripts/"   # 文字起こしファイルディレクトリ
PROMPT_DIR = "prompt/"       # プロンプトテンプレートディレクトリ
MOVIE_FILE_EXT = ".mp4"  # 動画ファイル拡張子
AUDIO_FILE_EXT = ".mp3" # 音声ファイル拡張子

INPUT_BLOB_DIR = f"https://{BLOB_ACCOUNT_NAME}.blob.core.windows.net/{BLOB_CONTAINER_NAME}/"      # 例: https://xxx.blob.core.windows.net/input/
OUTPUT_CONTAINER_SAS_URL = f"https://{BLOB_ACCOUNT_NAME}.blob.core.windows.net/{BLOB_CONTAINER_RESULT}"  # 例: https://xxx.blob.core.windows.net/result?sv=...

LOCALE = "ja-JP"
SUMMARY_LENGTH = 500  # ← ここを変えると文字数変更可
SPEECH_API_BASE = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/v3.2/"


# ===== parameter ======
transcription_mode = "fast" # 文字起こしモード： batch or fast mode
movie_file = "test30m"   # MP4ファイル名（拡張子なし）

# ====== 1. MP4 → MP3（64kbpsモノラル） ======
def convert_mp4_to_mp3(input_file, output_file):
    (
        ffmpeg
        .input(input_file)
        .output(output_file, acodec="libmp3lame", ac=1, ab="64k")
        .overwrite_output()
        .run(quiet=True)
    )
    #print(f"Converted {input_file} → {output_file}")


def ensure_ffmpeg_available():
    """ffmpeg バイナリが PATH に存在するか確認し、無ければわかりやすい例外を投げる"""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg executable not found. Please install ffmpeg on your system. "
            "On Debian/Ubuntu: sudo apt update && sudo apt install -y ffmpeg"
        )

# ====== 2.Blob Storageへアップロード ======
def upload_to_blob(connection_string, container_name, local_file, blob_name):
    # Blobサービスクライアントを作成
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)

    # コンテナクライアントを取得
    container_client = blob_service_client.get_container_client(container_name)

    # コンテナが存在しない場合は作成
    try:
        container_client.create_container()
        #print(f"コンテナ '{container_name}' を作成しました。")
    except Exception:
        #print(f"コンテナ '{container_name}' は既に存在します。")
        pass

    # Blobクライアントを取得
    blob_client = container_client.get_blob_client(blob_name)

    # ファイルをアップロード
    try:
        with open(local_file, "rb") as data:
            blob_client.upload_blob(data, overwrite=True)
            #print(f"✅ {local_file} をアップロードしました → blob://{container_name}/{blob_name}")
    except Exception as e:
        print("upload_to_blob で例外発生:", repr(e))
        raise
    #return blob_client.url  # アップロードしたBlobのURLを返す

    # 完全な URL を返す（SAS は付いていない点を注意）
    try:
        url = blob_client.url
    except Exception:
        url = None
    #print("Uploaded blob URL (no SAS):", url)
    return url

# ====== 2.1. Batch Transcription 実行 ======
def batch_transcription_job(input_sas, output_sas):
    url = SPEECH_API_BASE + "transcriptions"
    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Content-Type": "application/json"
    }
    body = {
        "displayName": "mp3_batch_transcription",
        "locale": LOCALE,
        "contentUrls": [input_sas],
        "destinationContainerUrl": output_sas,
        "properties": {
            "punctuationMode": "DictatedAndAutomatic",
            "wordLevelTimestampsEnabled": False,
        }
    }
    resp = requests.post(url, headers=headers, json=body)
    # デバッグ出力: ステータスコードとボディを必ず表示
    #print("create_transcription_job -> status:", resp.status_code)
    #try:
    #    print("create_transcription_job -> body:", resp.text)
    #except Exception:
    #    pass

    #print("Response Status:", resp.status_code)
    #resp.raise_for_status()

    # 失敗時は詳細を見て例外にする
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        print("create_transcription_job failed. Response headers:", dict(resp.headers))
        raise

    transcription_id = resp.headers["Location"].split("/")[-1]
    print(f"Job submitted: {transcription_id}")
    return transcription_id

def get_transcription_status(transcription_id):
    url = SPEECH_API_BASE + f"transcriptions/{transcription_id}"
    headers = {"Ocp-Apim-Subscription-Key": SPEECH_KEY}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

def wait_for_completion(transcription_id):
    while True:
        status = get_transcription_status(transcription_id)
        # 全体を出力して原因解析を容易にする
        #print("get_transcription_status ->", json.dumps(status, ensure_ascii=False, indent=2))
        s = status["status"]
        print(f"Status: {s}")
        if s in ["Succeeded", "Failed"]:
            return status
        time.sleep(15)

def get_transcription_text(transcription_id):
    url = SPEECH_API_BASE + f"transcriptions/{transcription_id}/files"
    headers = {"Ocp-Apim-Subscription-Key": SPEECH_KEY}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    files = resp.json()["values"]
    # kind=Transcription の contentUrl を探す
    file_url = next(f["links"]["contentUrl"] for f in files if f["kind"] == "Transcription")
    data = requests.get(file_url).json()
    texts = [p.get("display") for p in data.get("combinedRecognizedPhrases", []) if p.get("display")]
    return "\n".join(texts)

# ====== 2.2. fast transcriptionでテキストに変換 ======
def fast_transcription(audio_path: str, locales=None, diarization=False, max_speakers=2):
    """
    locales: 例 ["ja-JP"]。未指定 or [] なら自動判定/多言語モデル
    diarization: True で話者分離（単一チャネル時）
    """
    url = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/" \
          f"speechtotext/transcriptions:transcribe?api-version={SPEECH_API_VERSION}"

    definition = {}
    if locales is not None:
        definition["locales"] = locales
    if diarization:
        definition["diarization"] = {"enabled": True, "maxSpeakers": max_speakers}

    headers = {"Ocp-Apim-Subscription-Key": SPEECH_KEY}
    files = {
        # 音声ファイル本体
        "audio": (os.path.basename(audio_path), open(audio_path, "rb")),
        # 設定は JSON 文字列で送る
        "definition": (None, json.dumps(definition), "application/json"),
    }

    resp = requests.post(url, headers=headers, files=files, timeout=300)
    resp.raise_for_status()
    data = resp.json()

    # 返却JSONの combinedPhrases からテキストを連結
    phrases = data.get("combinedPhrases", [])
    text = "\n".join(p.get("text", "") for p in phrases if p.get("text"))
    return text, data  # 必要に応じて data 全体も利用

# ====== Blob削除 ======
def delete_blob(connection_string, container_name, blob_name):
    """
    指定した Blob を削除する（スナップショットも含む）。
    戻り値: True=削除成功, False=存在しなかった
    """
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(container_name)
    blob_client = container_client.get_blob_client(blob_name)

    try:
        if not blob_client.exists():
            print(f"Blob '{container_name}/{blob_name}' は存在しません。")
            return False
        blob_client.delete_blob(delete_snapshots="include")
        print(f"Blob '{container_name}/{blob_name}' を削除しました。")
        return True
    except Exception as e:
        print(f"Blob削除で例外が発生しました: {e}")
        raise

# ====== 3. GPT-4.1 で要約 ======

def load_prompt_template(path: str) -> str:
    """テンプレートファイルを読み込み、無ければデフォルトテンプレートを返す"""
    default = "次の文章を{max_chars}文字以内で日本語で要約してください：\n\n{text}"
    try:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    except Exception:
        pass
    return default

def summarize_text(text, max_chars=5000, max_output_tokens=2000, prompt_template_path: str = None):
    """
    要約を返し、input/output のトークン数を辞書で返す。
    戻り値: (summary_str, {"prompt_tokens":int, "completion_tokens":int, "total_tokens":int})
    """
    client = AzureOpenAI(
        api_key=OPENAI_KEY,
        azure_endpoint=OPENAI_ENDPOINT,
        api_version=OPENAI_API_VERSION ,
    )
    template = load_prompt_template(prompt_template_path)
    # テンプレートに安全に埋め込む
    try:
        #prompt = template.format(max_chars=max_chars, text=text)
        prompt = template + f"\n\n{text}\n"
        #print("prompt = ", prompt)
    except Exception:
        # フォールバック: 単純連結
        prompt = f"次の文章を{max_chars}文字以内で日本語で要約してください：\n\n{text}"

    resp = client.responses.create(
        model=OPENAI_DEPLOYMENT,
        input=prompt,
        max_output_tokens=max_output_tokens,
    )
    #return resp.output_text

    # 出力テキスト取得
    output_text = getattr(resp, "output_text", None)
    if not output_text:
        try:
            data = resp._to_dict() if hasattr(resp, "_to_dict") else dict(resp)
            # Responses API では output[0].content などの構造の場合もあるため柔軟に取得
            output_text = data.get("output_text") or ""
            if not output_text and "output" in data:
                # output が配列で text が入るケース
                try:
                    output_text = ""
                    for item in data["output"]:
                        if isinstance(item, dict):
                            if "content" in item and isinstance(item["content"], list):
                                for c in item["content"]:
                                    if c.get("type") == "output_text" and c.get("text"):
                                        output_text += c.get("text")
                            elif "text" in item:
                                output_text += item["text"]
                except Exception:
                    pass
        except Exception:
            output_text = ""

    # usage の取得（存在すれば利用）
    usage = getattr(resp, "usage", None)
    if not usage:
        try:
            data = resp._to_dict() if hasattr(resp, "_to_dict") else dict(resp)
            usage = data.get("usage")
        except Exception:
            usage = None

    prompt_tokens = completion_tokens = total_tokens = None

    if usage and isinstance(usage, dict):
        # 複数のキー名に対応
        prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("request_tokens")
        completion_tokens = usage.get("completion_tokens") or usage.get("response_tokens") or usage.get("completion")
        total_tokens = usage.get("total_tokens") or usage.get("tokens_used")
        # 型保証
        try:
            prompt_tokens = int(prompt_tokens) if prompt_tokens is not None else None
            completion_tokens = int(completion_tokens) if completion_tokens is not None else None
            total_tokens = int(total_tokens) if total_tokens is not None else None
        except Exception:
            pass
    else:
        # フォールバック: tiktoken で概算
        try:
            import tiktoken
            try:
                enc = tiktoken.encoding_for_model(OPENAI_DEPLOYMENT)
            except Exception:
                enc = tiktoken.get_encoding("cl100k_base")
            prompt_tokens = len(enc.encode(prompt))
            completion_tokens = len(enc.encode(output_text or ""))
            total_tokens = prompt_tokens + completion_tokens
        except Exception:
            prompt_tokens = completion_tokens = total_tokens = None

    tokens = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens
    }

    return (output_text or "", tokens)

# ====== メイン処理 ======
def main():

    # ===== set parameters ======
    transcription_mode = "fast" # 文字起こしモード： batch or fast mode
    movie_name = "test62m"   # MP4ファイル名（拡張子なし）
    audio_name = movie_name   # MP3ファイル名（拡張子なし）
    prompt_file = "default_prompt.txt"  # プロンプトテンプレートファイル名（PROMPT_DIR内）

    INPUT_MP4 = os.path.join(MOVIE_DIR, movie_name + MOVIE_FILE_EXT)   # 入力MP4ファイルパス
    OUTPUT_MP3 = os.path.join(AUDIO_DIR, audio_name + AUDIO_FILE_EXT)  # 出力MP3ファイルパス
    LOCAL_FILE_PATH = OUTPUT_MP3        # アップロードしたいローカルファイル
    BLOB_NAME = os.path.basename(LOCAL_FILE_PATH)  # Blob上でのファイル名
    INPUT_BLOB_FILE = os.path.join(INPUT_BLOB_DIR, BLOB_NAME)     # 例: https://xxx.blob.core.windows.net/input/output.mp3?sv=...
    INPUT_BLOB_SAS_URL = INPUT_BLOB_FILE + "?" + os.getenv("AZURE_STORAGE_SAS")  # SAS付きURL

    #print(f"===== 動画説明生成処理開始 =====\n動画ファイル: {INPUT_MP4}\n音声ファイル: {OUTPUT_MP3}\n文字起こしモード: {transcription_mode}\n")
    #print("LOCAL_FILE_PATH = ", LOCAL_FILE_PATH )
    #print("BLOB_NAME = ", BLOB_NAME )
    #print("INPUT_BLOB_SAS_URL = ", INPUT_BLOB_SAS_URL )
    #print("OUTPUT_CONTAINER_SAS_URL = ", OUTPUT_CONTAINER_SAS_URL )


    # 1. mp4 → mp3
    t10 = time.perf_counter()

    # ffmpeg が使えるか確認
    ensure_ffmpeg_available()

    convert_mp4_to_mp3(INPUT_MP4, OUTPUT_MP3)

    t11 = time.perf_counter()
    print(f"🔹 MP4→MP3変換時間: {t11 - t10:.2f}秒")

    # （このMP3を自分のAzure Blobにアップロードし、SAS URLを取得しておく）
    t12 = time.perf_counter()
    
    upload_to_blob(connection_string, BLOB_CONTAINER_NAME, LOCAL_FILE_PATH, BLOB_NAME)

    #print("🔹 MP3アップロード済みのSAS URLを使用します")
    t13 = time.perf_counter()
    print(f"🔹 upload時間: {t13 - t12:.2f}秒")


    # 2. 文字起こし
    print(f"\n===== 2. 文字起こし ({transcription_mode} 開始) =====")
    t20 = time.perf_counter()

    if transcription_mode == "batch": # batch mode
        tid = batch_transcription_job(INPUT_BLOB_SAS_URL, OUTPUT_CONTAINER_SAS_URL)
        result = wait_for_completion(tid)
        if result["status"] != "Succeeded":
            #print("result = ", result)
            print("Transcription result (詳細):", json.dumps(result, ensure_ascii=False, indent=2))
            raise RuntimeError("Transcription failed.")
        text = get_transcription_text(tid)
    else: # fast mode
        text, raw = fast_transcription(OUTPUT_MP3, locales=[LOCALE], diarization=True, max_speakers=5)

    t21 = time.perf_counter()
    print(f"🔹 speech to textの時間: {t21 - t20:.2f}秒")

        # --- 追加: 文字起こし結果をファイルに保存 ---
    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
    transcript_path = os.path.join(TRANSCRIPT_DIR, f"{movie_name}.txt")
    try:
        with open(transcript_path, "w", encoding="utf-8") as fw:
            fw.write(text or "")
        #print(f"Transcription saved: {transcript_path}")
    except Exception as e:
        print("Failed to save transcription:", repr(e))
    
    if transcription_mode == "fast":
                # --- 追加: 文字起こし結果をファイルに保存 ---
        transcript_path = os.path.join(TRANSCRIPT_DIR, f"{movie_name}.json")
        try:
            with open(transcript_path, "w", encoding="utf-8") as fw:
                if isinstance(raw, dict):
                    fw.write(json.dumps(raw, ensure_ascii=False, indent=2))
                else:
                    fw.write(str(raw))
                #print(f"Transcription raw saved: {transcript_path}")
        except Exception as e:
            print("Failed to save transcription raw:", repr(e))


    # 3. 要約
    t30 = time.perf_counter()

    # 明示的にテンプレートファイルを指定する例
    template_path = os.path.join(PROMPT_DIR, prompt_file)
    summary, tokens = summarize_text(text, SUMMARY_LENGTH, max_output_tokens=5000, prompt_template_path=template_path)

    t31 = time.perf_counter()
    print(f"🔹 動画説明要約時間: {t31 - t30:.2f}秒")

    # 4. mp3ファイル削除
    delete_blob(connection_string, BLOB_CONTAINER_NAME, BLOB_NAME)
    if transcription_mode == "batch": # batch mode
        print("")
        #delete_blob(connection_string, BLOB_CONTAINER_RESULT, BLOB_NAME)

    # 4. 表示 
    print("\n===== ✅ 要約結果 =====")
    print(summary)
    print("\n===== トークン数 =====")
    print(tokens)

if __name__ == "__main__":
    main()
