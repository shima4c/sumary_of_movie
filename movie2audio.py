import subprocess
import os
import math

def convert_video_to_low_bitrate_audio(input_file: str, output_prefix: str, max_duration_sec: int = 1800, bitrate: str = "56k"):
    """
    動画ファイルを指定されたビットレートの音声ファイルに変換し、
    指定された最大長を超える場合はファイルを分割します。

    Args:
        input_file (str): 入力動画ファイルのパス。
        output_prefix (str): 出力音声ファイルのファイル名プレフィックス (例: 'output_audio')。
        max_duration_sec (int): 分割する最大時間（秒）。デフォルトは30分 (1800秒)。
        bitrate (str): 出力音声ファイルのビットレート (例: '56k')。
    """
    if not os.path.exists(input_file):
        print(f"エラー: 入力ファイルが見つかりません: {input_file}")
        return

    # 1. 動画の長さを取得
    print(f"[{input_file}]の長さを取得中...")
    try:
        # ffprobeを使用して動画のdurationを取得
        cmd_duration = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0', # ビデオストリームの情報を取得（durationはビデオのものを使うことが一般的）
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            input_file
        ]
        
        # subprocess.runでffprobeを実行し、出力を取得
        result = subprocess.run(cmd_duration, capture_output=True, text=True, check=True)
        duration = float(result.stdout.strip())
        print(f"動画の長さ: {duration:.2f} 秒")

    except subprocess.CalledProcessError as e:
        print(f"エラー: ffprobeの実行中に問題が発生しました。ffmpeg/ffprobeがインストールされ、PATHが通っているか確認してください。")
        print(f"詳細: {e.stderr}")
        return
    except ValueError:
        print("エラー: 動画の長さを正しく取得できませんでした。")
        return
    except FileNotFoundError:
        print("エラー: ffprobeが見つかりません。ffmpeg/ffprobeがインストールされ、PATHが通っているか確認してください。")
        return

    # 2. ファイルの分割処理
    if duration > max_duration_sec:
        num_splits = math.ceil(duration / max_duration_sec)
        print(f"動画が{max_duration_sec}秒を超えています。{num_splits}個のファイルに分割します。")

        for i in range(num_splits):
            start_time = i * max_duration_sec
            segment_duration = max_duration_sec
            output_file = f"{output_prefix}_part_{i+1}.mp3"

            # 最後のセグメントの長さの調整
            if i == num_splits - 1:
                segment_duration = duration - start_time
                if segment_duration <= 0:
                     continue # 処理する必要なし

            print(f"\n--- {i+1}/{num_splits} の処理を開始: 開始時刻 {start_time}秒, 長さ {segment_duration:.2f}秒 -> {output_file} ---")

            # ffmpegコマンドの構築（分割用）
            # -ss (seek) は入力オプション(-iの前)に置くことで高速になりますが、正確性では入力オプションの後の方が優れます。
            # 今回は正確な分割が必要なため、入力オプションの後に置きます。
            ffmpeg_command = [
                'ffmpeg',
                '-i', input_file,        # 入力ファイル
                '-ss', str(start_time),  # 開始シーク時間
                '-t', str(segment_duration), # 処理する長さ
                '-vn',                   # ビデオストリームを除外
                '-acodec', 'libmp3lame', # MP3エンコーダ
                '-b:a', bitrate,         # 音声ビットレート (例: 56k)
                '-ar', '22050',           # サンプルレートを低く設定し、ファイルサイズを削減 (オプション)
                '-y',                    # 出力ファイルを上書き
                output_file
            ]
            
            # コマンド実行
            try:
                subprocess.run(ffmpeg_command, check=True)
                print(f"✅ 変換成功: {output_file}")
            except subprocess.CalledProcessError as e:
                print(f"❌ エラー: ffmpegの実行中に問題が発生しました。")
                print(f"詳細: {e.stderr}")
                return

    # 3. 分割が不要な場合 (30分未満)
    else:
        output_file = f"{output_prefix}.mp3"
        print(f"動画は{max_duration_sec}秒未満です。単一ファイルに変換します -> {output_file}")
        
        # ffmpegコマンドの構築（単一ファイル用）
        ffmpeg_command = [
            'ffmpeg',
            '-i', input_file,        # 入力ファイル
            '-vn',                   # ビデオストリームを除外
            '-acodec', 'libmp3lame', # MP3エンコーダ
            '-b:a', bitrate,         # 音声ビットレート (例: 56k)
            '-ar', '22050',           # サンプルレートを低く設定し、ファイルサイズを削減 (オプション)
            '-y',                    # 出力ファイルを上書き
            output_file
        ]

        # コマンド実行
        try:
            subprocess.run(ffmpeg_command, check=True)
            print(f"✅ 変換成功: {output_file}")
        except subprocess.CalledProcessError as e:
            print(f"❌ エラー: ffmpegの実行中に問題が発生しました。")
            print(f"詳細: {e.stderr}")


# --- 実行例 ---
if __name__ == '__main__':
    # この部分を実際のファイル名に置き換えてください
    input_video = "movies/test.mp4" # 👈 変換したい動画ファイル名
    output_base_name = "audios/test_audio" # 👈 出力音声ファイルのベース名

    # テスト用のダミーファイルを作成するか、実際のファイルを準備してください。
    # このスクリプトは、your_video_file.mp4が存在することを前提としています。

    # 関数を呼び出して実行
    convert_video_to_low_bitrate_audio(
        input_file=input_video,
        output_prefix=output_base_name,
        max_duration_sec=1800,  # 30分 (30 * 60)
        bitrate="56k"           # 56kbps
    )