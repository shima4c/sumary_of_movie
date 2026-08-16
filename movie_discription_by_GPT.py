import os
import math
import shutil
import subprocess
from pathlib import Path
from typing import List
from dotenv import load_dotenv
from tqdm import tqdm
from pydub.utils import mediainfo_json
from openai import OpenAI
from dotenv import load_dotenv

# ========== 設定 ==========
TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"  # or "gpt-4o-transcribe"
SUMMARY_MODEL = "gpt-4.1-mini"
# 安全側に 25分（1500秒）以下でチャンク化
CHUNK_SEC = 20 * 60           # 20分
TARGET_BITRATE = "48k"        # 32k〜64k程度でOK（mono推奨）
TARGET_CHANNELS = 1
TARGET_SAMPLE_RATE = 16000    # 16kHzで十分

# 要約の最大文字数
SUMMARY_CHAR_LIMIT = 500

# .envのファイルを読み込む
load_dotenv()


# ========== ユーティリティ ==========
def run_ffmpeg(cmd: List[str]):
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg error:\n{res.stderr}")
    return res

def get_duration_sec(path: Path) -> float:
    info = mediainfo_json(str(path))
    return float(info["format"]["duration"])

def ensure_small_enough(input_mp4: Path, out_dir: Path) -> List[Path]:
    """
    1) ビデオをオーディオのみ取り出して再エンコード
    2) ビットレート/チャンネル/サンプリングレートを落として再エンコード
    3) 長い場合は CHUNK_SEC ごとに分割
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_normalized = out_dir / "normalized.mp3"

    # 正規化（mono/低ビットレート/16kHz）
    run_ffmpeg([
        "ffmpeg",  
        "-i", str(input_mp4),           # 入力を動画ファイルに変更
        "-vn",                          # ビデオストリームを除外
        "-acodec", "libmp3lame",        # MP3エンコーダ
        "-ac", str(TARGET_CHANNELS),    # チャンネル数を調整
        "-ar", str(TARGET_SAMPLE_RATE), # サンプルレートを低く設定し、ファイルサイズを削減 (オプション)
        "-b:a", TARGET_BITRATE,         # 音声ビットレート (例: 56k)
        "-y",                           # 出力ファイルを上書き
        str(tmp_normalized)             # 出力ファイル
    ])

    dur = get_duration_sec(tmp_normalized)

    # そのまま行ける場合はチャンクなし
    if dur <= CHUNK_SEC:
        one = out_dir / f"chunk_000.mp3"
        shutil.move(tmp_normalized, one)
        return [one]

    # 分割
    total_chunks = math.ceil(dur / CHUNK_SEC)
    chunk_paths = []
    for i in range(total_chunks):
        start = i * CHUNK_SEC
        out = out_dir / f"chunk_{i:03d}.mp3"
        cmd = [
            "ffmpeg", 
            "-y", # 出力ファイルを上書き
            "-ss", str(start), "-t", str(CHUNK_SEC), # 開始シーク時間
            "-i", str(tmp_normalized), # 入力ファイル
            "-ac", str(TARGET_CHANNELS), # チャンネル数を調整
            "-ar", str(TARGET_SAMPLE_RATE), # サンプルレートを低く設定し、ファイルサイズを削減 (オプション)
            "-b:a", TARGET_BITRATE, # 音声ビットレート (例: 56k)
            str(out) # 出力ファイル
        ]
        run_ffmpeg(cmd)
        chunk_paths.append(out)

    tmp_normalized.unlink(missing_ok=True)
    return chunk_paths

# ========== OpenAI クライアント ==========
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def transcribe_file(mp3_path: Path) -> str:
    """
    gpt-4o-mini-transcribe で1ファイルを文字起こし
    """
    with open(mp3_path, "rb") as f:
        # Audio API: transcriptions
        tr = client.audio.transcriptions.create(
            model=TRANSCRIBE_MODEL,
            file=f,
            # response_format は現状 text/json のみ（仕様に基づく）。text を使うとプレーンテキスト返却。
            # temperature等は提供されない/限定的。
        )
    # SDKは text フィールド or 全文 string を返すケースがあるため両対応
    return getattr(tr, "text", str(tr))

def summarize_ja_500chars(text: str) -> str:
    """
    日本語・500文字以内の要約を生成（厳格な制約を明示）
    """
    rules = (
        f"あなたは会議や講演の要約者です。日本語で出力してください。"
        f"必ず{SUMMARY_CHAR_LIMIT}文字以内に収め、文体は簡潔明瞭、重要ポイントを網羅。"
        "話者名や個人情報は可能な限り一般化し、推測はしない。箇条書き不可、1段落。"
    )
    resp = client.responses.create(
        model=SUMMARY_MODEL,
        input=[
            {"role": "system", "content": rules},
            {
                "role": "user",
                "content": (
                    "次の文字起こし全体を要約してください。"
                    f"最大{SUMMARY_CHAR_LIMIT}文字以内。:\n\n" + text
                ),
            },
        ],
    )
    return resp.output_text.strip()

def transcribe_and_summarize(input_mp4: str, workdir: str = "work"):
    src = Path(input_mp4)
    outd = Path(workdir) / src.stem
    outd.mkdir(parents=True, exist_ok=True)

    # 1) 分割/正規化
    chunks = ensure_small_enough(src, outd)

    # 2) 逐次文字起こし
    texts = []
    for c in tqdm(chunks, desc="Transcribing"):
        t = transcribe_file(c)
        texts.append(t)

    full_transcript = "\n".join(texts)

    # 3) 500文字要約
    summary = summarize_ja_500chars(full_transcript)

    # 4) 保存
    (outd / "transcript.txt").write_text(full_transcript, encoding="utf-8")
    (outd / "summary_ja_500.txt").write_text(summary, encoding="utf-8")

    print(f"[OK] Transcript: {outd/'transcript.txt'}")
    print(f"[OK] Summary  : {outd/'summary_ja_500.txt'}")
    return summary

if __name__ == "__main__":
    # 使い方: python app.py /path/to/video.mp4
    #import sys
    #if len(sys.argv) < 2:
    #    print("Usage: python app.py INPUT.mp4")
    #    sys.exit(1)
    #print(transcribe_and_summarize(sys.argv[1]))

    input_video = "movies/test.mp4" # 👈 変換したい動画ファイル名
    print(transcribe_and_summarize(input_video))
