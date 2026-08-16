import os
from openai import AzureOpenAI
from dotenv import load_dotenv

# .envのファイルを読み込む
load_dotenv()

# ====== 環境変数読み込み ======
OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
OPENAI_ENDPOINT = "https://test-ej-ml-openai.openai.azure.com/" # ：Visuamallで利用のAzure OpenAIリソースのエンドポイント
OPENAI_DEPLOYMENT = "gpt-4.1"           # AOAIのモデル(Deployment)名
OPENAI_API_VERSION = "2025-03-01-preview"   # 例：AOAIのAPIバージョン


OPENAI_ENDPOINT = OPENAI_ENDPOINT.rstrip('/')
print("DEBUG: endpoint =", OPENAI_ENDPOINT)
print("DEBUG: deployment =", OPENAI_DEPLOYMENT)
print("DEBUG: api_version =", OPENAI_API_VERSION)
print("DEBUG: key set? ", bool(OPENAI_KEY))

client = AzureOpenAI(
    api_key=OPENAI_KEY,
    azure_endpoint=OPENAI_ENDPOINT,
    api_version=OPENAI_API_VERSION ,
)
prompt = f"横浜の観光名所を100文字以内で教えてください。"

try:
    response = client.responses.create(
        model=OPENAI_DEPLOYMENT,
        input=prompt,
        max_output_tokens=100,
    )
    print("ok:", response)
except Exception as e:
    print("responses.create error:", repr(e))
    # SDK内部のHTTPレスポンス情報があれば出力
    if hasattr(e, "response"):
        try:
            print("HTTP status:", getattr(e.response, "status_code", None))
            print("HTTP response body:", e.response.text)
        except Exception:
            pass
    raise