# app.py
import os
from dotenv import load_dotenv
import tempfile
import requests
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from openai import AzureOpenAI

# .envのファイルを読み込む
load_dotenv()

# ========== 設定 ==========
SPEECH_KEY = os.environ["AZURE_SPEECH_KEY"]
SPEECH_REGION = "japaneast"          # Bach Transcription対応リージョンを使用
#SPEECH_FAST_URL = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version=2024-11-15"
SPEECH_FAST_URL = "https://japaneast.api.cognitive.microsoft.com/" 

AOAI_ENDPOINT = "https://test-ej-ml-openai.openai.azure.com/" # ：Visuamallで利用のAzure OpenAIリソースのエンドポイント
AOAI_API_KEY = os.environ["AZURE_OPENAI_API_KEY"]
AOAI_API_VERSION = "2025-01-01-preview"   # 例：ご利用のデプロイに合わせて
AOAI_DEPLOYMENT = "gpt-4.1"           # 例：要約用に軽量・高速

client = AzureOpenAI(
    api_key=AOAI_API_KEY,
    api_version=AOAI_API_VERSION,
    azure_endpoint=AOAI_ENDPOINT,
)

app = FastAPI(title="Speech2Text + Summary (JA)")

def summarize_text_ja(text: str, limit_chars: int = 500) -> str:
    """日本語で500文字以内に要約（重要論点・結論・アクションを優先）。"""
    system = (
       "あなたは日本語の要約アシスタントです。"
       f"出力は{limit_chars}文字以内。敬体。話者名や決定事項があれば簡潔に含めてください。"
       "冗長な言い換えは避け、固有名詞は保持してください。"
    )
    user = (
       "次の会話文字起こしを要約してください：\n"
       f"{text}"
    )
    resp = client.chat.completions.create(
        model=AOAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        max_tokens=600,   # 出力を十分に確保（日本語500文字≒300〜500トークン未満が多い）
    )
    return resp.choices[0].message.content.strip()

def parse_fast_transcription(json_obj: dict) -> str:
    """
    Fast Transcriptionの戻りから可読テキストを抽出。
    優先: combinedPhrases[].text → なければ phrases[].text を連結。
    """
    texts = []
    combined = json_obj.get("combinedPhrases") or []
    if combined:
        for p in combined:
            t = p.get("text")
            if t:
                texts.append(t)
    else:
        phrases = json_obj.get("phrases") or []
        for p in phrases:
            t = p.get("text")
            if t:
                texts.append(t)
    return "\n".join(texts).strip()

@app.post("/transcribe-and-summarize")
def transcribe_and_summarize(
    file: UploadFile = File(...),
    diarization: bool = False,
):
    # 受け取りチェック
    if not file.filename.lower().endswith((".mp3", ".wav", ".m4a", ".mp4", ".ogg", ".opus", ".wma", ".aac", ".webm")):
        raise HTTPException(400, "対応拡張子ではありません。mp3/wav等を指定してください。")

    # 一時保存（Fast Transcriptionはファイルをそのままmultipartで送れる）
    with tempfile.NamedTemporaryFile(delete=True) as tmp:
        content = file.file.read()
        if len(content) > 300 * 1024 * 1024:
            raise HTTPException(400, "ファイルサイズが300MBを超えています（Fast Transcription上限）。")
        tmp.write(content)
        tmp.flush()

        # Fast Transcription へ送信
        headers = {
            "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        }
        # 日本語固定の場合は locales を指定。言語混在があり得るなら言語識別を有効化可。
        data = {
            'locales': '["ja-JP"]',
        }
        if diarization:
            data['diarizationEnabled'] = "true"

        files = {
            'audio': (file.filename, open(tmp.name, "rb"), file.content_type or "audio/mpeg")
        }
        r = requests.post(SPEECH_FAST_URL, headers=headers, data=data, files=files, timeout=900)
        if r.status_code >= 300:
            raise HTTPException(r.status_code, f"Speech API error: {r.text}")

        stt_json = r.json()
        transcript = parse_fast_transcription(stt_json)
        if not transcript:
            raise HTTPException(502, "文字起こし結果が空でした。")

        # 500文字以内に要約
        summary = summarize_text_ja(transcript, limit_chars=500)

        return JSONResponse({
            "transcript": transcript,
            "summary": summary
        })
