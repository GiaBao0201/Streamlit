import os
import time
import threading
from google.cloud import speech, texttospeech, vision, translate_v2 as translate
from pydub import AudioSegment
from pygame import mixer
mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
import RPi.GPIO as GPIO
import pigpio
import speech_recognition as sr
import google.generativeai as genai  # ✅ Dùng Gemini API

# ==== Cấu hình Google Cloud & Gemini ====
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/home/admin/Downloads/esp32-441714-19ff1efdb06f.json"
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"   # ⚠️ Thay bằng API key Gemini của bạn
genai.configure(api_key=GEMINI_API_KEY)

# ==== GPIO setup ====
CHAT_BUTTON_PIN = 26
OCR_BUTTON_PIN = 12
GPIO.setmode(GPIO.BCM)
GPIO.setup(CHAT_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(OCR_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# ==== Mixer setup ====
mixer.init()

# ==== Biến toàn cục ====
is_processing = False
ocr_text_global = ""
is_paused = False
pi = pigpio.pi()
if not pi.connected:
    print("❌ Không thể kết nối tới PIGPIO daemon.")
    exit()

# ==== TTS ====
def play_audio(text, lang='vi', output_file='output.mp3', speed=1.1):
    global is_paused
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)

    voice_params = {
        'vi': texttospeech.VoiceSelectionParams(language_code="vi-VN",
                                                ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL),
        'en': texttospeech.VoiceSelectionParams(language_code="en-US",
                                                ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL)
    }
    voice = voice_params.get(lang, voice_params['vi'])
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
    response = client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)

    with open(output_file, "wb") as out:
        out.write(response.audio_content)

    sound = AudioSegment.from_file(output_file)
    sound_with_speed = sound.speedup(playback_speed=speed)
    sound_with_speed.export(output_file, format="mp3")

    mixer.music.load(output_file)
    mixer.music.play()

    while mixer.music.get_busy():
        if is_paused:
            mixer.music.pause()
            while is_paused:
                time.sleep(0.1)
            mixer.music.unpause()
        time.sleep(0.1)


# ==== Phát hiện ngôn ngữ ====
def detect_language(text):
    translate_client = translate.Client()
    result = translate_client.detect_language(text)
    detected_language = result['language']
    print(f"🌐 Phát hiện ngôn ngữ: {detected_language}")
    return detected_language


# ==== Speech to Text ====
def setup_google_speech_to_text():
    recognizer = sr.Recognizer()
    microphone = sr.Microphone()
    with microphone as source:
        print("🎙️ Đang cân chỉnh micro...")
        recognizer.adjust_for_ambient_noise(source)
        print("Micro sẵn sàng, hãy nói...")
        audio = recognizer.listen(source)
    client = speech.SpeechClient()
    audio_content = audio.get_wav_data()
    audio_wav = speech.RecognitionAudio(content=audio_content)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=44100,
        language_code="vi-VN",
    )
    response = client.recognize(config=config, audio=audio_wav)
    for result in response.results:
        text = result.alternatives[0].transcript
        print(f"🗣️ Bạn nói: {text}")
        return text


# ==== Gemini Chat ====
def ask_gemini(prompt):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")  # ⚡ Model nhanh và rẻ
        response = model.generate_content(prompt)
        return response.text.strip() if response and response.text else None
    except Exception as e:
        print("❌ Lỗi khi gọi Gemini API:", e)
        return None


# ==== Xử lý Chat ====
def handle_chat_interaction():
    global ocr_text_global
    print("🧠 Bắt đầu trò chuyện với Gemini...")
    play_audio("Xin chào, tôi có thể giúp gì cho bạn?")
    try:
        speech_text = setup_google_speech_to_text()
        if not speech_text:
            play_audio("Tôi chưa nghe rõ. Bạn có thể nói lại không?")
            return
        print(f"Bạn nói: {speech_text}")
        combined_prompt = f"Nội dung OCR: {ocr_text_global}\nCâu hỏi: {speech_text}"
        response = ask_gemini(combined_prompt)
        if not response:
            play_audio("Xin lỗi, tôi chưa thể trả lời câu hỏi này.")
        else:
            print(f"🤖 Gemini trả lời: {response}")
            lang = detect_language(response)
            play_audio(response, lang)
    except Exception as e:
        print(f"⚠️ Lỗi trong quá trình chat: {e}")
        play_audio("Đã xảy ra lỗi, vui lòng thử lại.")


# ==== OCR ====
def take_picture():
    return os.system('rpicam-jpeg --output test.jpg') == 0


def perform_ocr(image_path):
    client = vision.ImageAnnotatorClient()
    with open(image_path, 'rb') as image_file:
        content = image_file.read()
    image = vision.Image(content=content)
    response = client.text_detection(image=image)
    texts = response.text_annotations
    if texts:
        return texts[0].description
    return ""


def handle_ocr_and_tts():
    global is_processing, ocr_text_global
    is_processing = True
    if take_picture():
        play_audio("Đã sẵn sàng.")
        ocr_text = perform_ocr("test.jpg")
        if ocr_text:
            print(f"📖 OCR nội dung: {ocr_text}")
            ocr_text_global = ocr_text
            lang = detect_language(ocr_text)
            play_audio(ocr_text, lang)
        else:
            play_audio("Không thể đọc được văn bản, vui lòng thử lại.")
    else:
        play_audio("Camera chưa sẵn sàng.")
    is_processing = False


# ==== Main Loop ====
def main():
    print("🚀 AI Vision Reader (Gemini Edition) đã khởi động.")
    last_chat_state = pi.read(CHAT_BUTTON_PIN)
    try:
        while True:
            chat_button_state = pi.read(CHAT_BUTTON_PIN)
            ocr_button_state = GPIO.input(OCR_BUTTON_PIN)

            if chat_button_state == 0 and last_chat_state == 1:
                handle_chat_interaction()

            if ocr_button_state == GPIO.LOW and not is_processing:
                print("🖼️ Bắt đầu OCR...")
                threading.Thread(target=handle_ocr_and_tts).start()

            last_chat_state = chat_button_state
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("🛑 Đã dừng AI Vision Reader.")
    finally:
        mixer.quit()
        GPIO.cleanup()
        pi.stop()


if __name__ == '__main__':
    main()
