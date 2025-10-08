import os
import time
import threading
import base64
import requests
from pydub import AudioSegment
from pygame import mixer
import google.generativeai as genai
import RPi.GPIO as GPIO
import pigpio
import speech_recognition as sr

# ========================== CẤU HÌNH API KEY ==========================
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"  
GOOGLE_TTS_API_KEY = "YOUR_TTS_API_KEY"  

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# ========================== CẤU HÌNH GPIO ==========================
CHAT_BUTTON_PIN = 26
OCR_BUTTON_PIN = 12
PAUSE_BUTTON_PIN = 25

GPIO.setmode(GPIO.BCM)
GPIO.setup(CHAT_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(OCR_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PAUSE_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

pi = pigpio.pi()
if not pi.connected:
    print("Không thể kết nối PIGPIO DAEMON. Thoát!")
    exit()

# ========================== KHỞI TẠO ÂM THANH ==========================
mixer.init(frequency=44100, size=-16, channels=1, buffer=512)

# ========================== BIẾN TOÀN CỤC ==========================
is_processing = False
ocr_text_global = ""
is_paused = False
stop_current_read = False

# ========================== TEXT TO SPEECH ==========================
def play_audio(text, lang='vi', output_file='output.mp3', speed=1.2):
    global is_paused, stop_current_read
    stop_current_read = False
    try:
        print(f"[TTS] Đọc nội dung: {text[:60]}...")
        url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_TTS_API_KEY}"
        voice = {"languageCode": "vi-VN" if lang == "vi" else "en-US", "ssmlGender": "NEUTRAL"}
        audio_config = {"audioEncoding": "MP3"}
        data = {"input": {"text": text}, "voice": voice, "audioConfig": audio_config}

        response = requests.post(url, json=data)
        response.raise_for_status()
        audio_content = response.json()["audioContent"]

        with open(output_file, "wb") as out:
            out.write(base64.b64decode(audio_content))

        sound = AudioSegment.from_file(output_file)
        sound_with_speed = sound.speedup(playback_speed=speed)
        sound_with_speed.export(output_file, format="mp3")

        mixer.music.load(output_file)
        mixer.music.play()

        while mixer.music.get_busy():
            if stop_current_read:
                mixer.music.stop()
                break
            if is_paused:
                mixer.music.pause()
                while is_paused:
                    time.sleep(0.1)
                mixer.music.unpause()
            time.sleep(0.1)

    except Exception as e:
        print(f"[Lỗi TTS]: {e}")
        try:
            if "invalid" not in str(e):
                play_audio("Đã xảy ra lỗi trong quá trình đọc văn bản.", lang)
        except:
            pass

# ========================== SPEECH TO TEXT ==========================
def setup_google_speech_to_text():
    recognizer = sr.Recognizer()
    microphone = sr.Microphone()
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source)
        print("[STT] Đang nghe bạn nói...")
        audio = recognizer.listen(source)
    client = sr.Recognizer()
    try:
        text = recognizer.recognize_google(audio, language="vi-VN")
        print(f"[Bạn nói]: {text}")
        return text
    except sr.UnknownValueError:
        play_audio("Tôi không nghe rõ, bạn có thể nói lại không?")
        return ""
    except Exception as e:
        print(f"[Lỗi STT]: {e}")
        return ""

# ========================== OCR BẰNG GEMINI ==========================
def take_picture():
    print("[Camera] Đang chụp ảnh...")
    result = os.system('rpicam-jpeg --output test.jpg')
    return result == 0

def perform_ocr_with_gemini(image_path):
    try:
        print("[OCR] Gửi ảnh đến Gemini để trích xuất văn bản...")
        with open(image_path, "rb") as f:
            image_data = f.read()
        image_base64 = base64.b64encode(image_data).decode("utf-8")

        prompt = "Hãy đọc toàn bộ chữ có trong bức ảnh này và trả về chính xác nội dung văn bản."
        response = model.generate_content([
            {"role": "user", "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_base64}}
            ]}
        ])

        text_output = response.text.strip() if response.text else ""
        if text_output:
            print(f"[OCR] Văn bản nhận được: {text_output[:80]}...")
            return text_output
        else:
            print("[OCR] Không phát hiện văn bản.")
            return ""
    except Exception as e:
        print(f"[Lỗi OCR Gemini]: {e}")
        return ""

# ========================== GEMINI CHAT ==========================
def ask_gemini(prompt):
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"[Lỗi Gemini]: {e}")
        return None

# ========================== XỬ LÝ CHAT ==========================
def handle_chat_interaction():
    global ocr_text_global, stop_current_read, is_processing
    is_processing = True
    stop_current_read = True
    print("[Chat] Bắt đầu trò chuyện...")
    play_audio("Xin chào, tôi có thể giúp gì cho bạn?")
    speech_text = setup_google_speech_to_text()
    if not speech_text:
        is_processing = False
        return
    combined_prompt = f"Nội dung OCR: {ocr_text_global}\nNgười dùng hỏi: {speech_text}"
    response = ask_gemini(combined_prompt)
    if response:
        play_audio(response)
    else:
        play_audio("Xin lỗi, tôi chưa thể trả lời câu hỏi này.")
    is_processing = False
# ========================== XỬ LÝ OCR ==========================
def handle_ocr():
    global ocr_text_global, stop_current_read, is_processing
    is_processing = True
    stop_current_read = True
    if take_picture():
        play_audio("Đang quét văn bản, vui lòng chờ...")
        ocr_text = perform_ocr_with_gemini("test.jpg")
        if ocr_text:
            ocr_text_global = ocr_text
            play_audio(ocr_text)
        else:
            play_audio("Không phát hiện được văn bản, vui lòng thử lại.")
    else:
        play_audio("Camera chưa sẵn sàng.")
    is_processing = False

# ========================== VÒNG LẶP CHÍNH ==========================
def main():
    global is_paused, stop_current_read, is_processing
    print("Chào mừng đến với AI Vision Reader (Gemini-only version)")
    chat_last = GPIO.input(CHAT_BUTTON_PIN)
    ocr_last = GPIO.input(OCR_BUTTON_PIN)
    pause_last = GPIO.input(PAUSE_BUTTON_PIN)

    while True:
        chat_state = GPIO.input(CHAT_BUTTON_PIN)
        ocr_state = GPIO.input(OCR_BUTTON_PIN)
        pause_state = GPIO.input(PAUSE_BUTTON_PIN)

        if pause_state == GPIO.LOW and pause_last == GPIO.HIGH:
            is_paused = not is_paused
            print("Tạm dừng" if is_paused else "Tiếp tục đọc")
        pause_last = pause_state

        if chat_state == GPIO.LOW and chat_last == GPIO.HIGH and not is_processing:
            threading.Thread(target=handle_chat_interaction).start()
        chat_last = chat_state

        if ocr_state == GPIO.LOW and ocr_last == GPIO.HIGH and not is_processing:
            threading.Thread(target=handle_ocr).start()
        ocr_last = ocr_state

        time.sleep(0.05)

# ========================== CHẠY CHÍNH ==========================
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Ngắt chương trình AI Vision Reader.")
    finally:
        mixer.quit()
        GPIO.cleanup()
        pi.stop()
