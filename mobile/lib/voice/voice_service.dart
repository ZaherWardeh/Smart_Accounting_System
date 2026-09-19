import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;

import 'speech_text.dart';

typedef SpeechResultCallback = void Function(String text, bool isFinal);

/// Everything the chat screen needs from the device's speech engines, behind
/// an interface so tests (and any future server-side STT/TTS) can swap in.
abstract class VoiceService {
  bool get isListening;

  /// Asks for the microphone / speech-recognition permission and checks the
  /// device can recognise speech. False means voice input is unavailable.
  Future<bool> initSpeech();

  /// [language] is a two-letter code ("ar" / "en"). [onResult] fires with the
  /// running transcript (isFinal=false) and once more when it's final.
  /// [onDone] fires whenever the engine stops listening for any reason.
  Future<void> startListening({
    required String language,
    required SpeechResultCallback onResult,
    required void Function(String message) onError,
    VoidCallback? onDone,
  });

  Future<void> stopListening();

  /// Reads [text] aloud, picking an Arabic or English voice from its content.
  /// Completes when speech finishes or is stopped.
  Future<void> speak(String text);

  Future<void> stopSpeaking();

  /// Whether the device has a text-to-speech voice for [bcp47] ("ar-SA").
  Future<bool> isLanguageAvailable(String bcp47);

  void dispose();
}

class RealVoiceService implements VoiceService {
  final stt.SpeechToText _stt = stt.SpeechToText();
  final FlutterTts _tts = FlutterTts();

  bool _sttReady = false;
  bool _ttsConfigured = false;
  bool _listening = false;
  bool _speaking = false;
  void Function(String)? _onError;
  VoidCallback? _onDone;

  @override
  bool get isListening => _listening;

  @override
  Future<bool> initSpeech() async {
    if (_sttReady) return true;
    _sttReady = await _stt.initialize(
      onError: (e) {
        _listening = false;
        _onError?.call(e.errorMsg);
      },
      onStatus: (status) {
        if (status == 'done' || status == 'notListening') {
          _listening = false;
          _onDone?.call();
        }
      },
    );
    return _sttReady;
  }

  /// Picks the device's locale id for a language, e.g. "ar" -> "ar_SA" or "ar-EG",
  /// preferring the common variants. Null when the device has none.
  Future<String?> _resolveLocale(String language) async {
    final locales = await _stt.locales();
    final matches = locales
        .where((l) => l.localeId.toLowerCase().replaceAll('_', '-').startsWith('$language-') ||
            l.localeId.toLowerCase() == language)
        .toList();
    if (matches.isEmpty) return null;
    const preferred = {'ar': 'ar-sa', 'en': 'en-us'};
    for (final l in matches) {
      if (l.localeId.toLowerCase().replaceAll('_', '-') == preferred[language]) return l.localeId;
    }
    return matches.first.localeId;
  }

  @override
  Future<void> startListening({
    required String language,
    required SpeechResultCallback onResult,
    required void Function(String message) onError,
    VoidCallback? onDone,
  }) async {
    await stopSpeaking(); // so Rima doesn't hear herself
    _onError = onError;
    _onDone = onDone;
    final localeId = await _resolveLocale(language);
    if (localeId == null) {
      onError(language == 'ar'
          ? 'التعرف على الصوت بالعربية غير مثبّت على هذا الجهاز'
          : 'Speech recognition for this language is not installed on this device');
      return;
    }
    _listening = true;
    await _stt.listen(
      onResult: (r) => onResult(r.recognizedWords, r.finalResult),
      listenOptions: stt.SpeechListenOptions(
        localeId: localeId,
        listenFor: const Duration(seconds: 60),
        pauseFor: const Duration(seconds: 4),
        partialResults: true,
        cancelOnError: true,
        listenMode: stt.ListenMode.dictation,
      ),
    );
  }

  @override
  Future<void> stopListening() async {
    if (_stt.isListening) await _stt.stop();
  }

  Future<void> _ensureTts() async {
    if (_ttsConfigured) return;
    await _tts.awaitSpeakCompletion(true);
    await _tts.setSpeechRate(0.5);
    await _tts.setPitch(1.0);
    if (Platform.isIOS) {
      await _tts.setSharedInstance(true);
      await _tts.setIosAudioCategory(
        IosTextToSpeechAudioCategory.playAndRecord,
        [
          IosTextToSpeechAudioCategoryOptions.allowBluetooth,
          IosTextToSpeechAudioCategoryOptions.defaultToSpeaker,
        ],
        IosTextToSpeechAudioMode.defaultMode,
      );
    }
    _ttsConfigured = true;
  }

  @override
  Future<void> speak(String text) async {
    final cleaned = cleanForSpeech(text);
    if (cleaned.isEmpty) return;
    await _ensureTts();
    await _tts.stop();
    await _tts.setLanguage(isArabicText(cleaned) ? 'ar-SA' : 'en-US');
    _speaking = true;
    try {
      for (final chunk in chunkForSpeech(cleaned)) {
        if (!_speaking) break; // stopSpeaking() was called
        await _tts.speak(chunk).timeout(const Duration(minutes: 3), onTimeout: () => 0);
      }
    } finally {
      _speaking = false;
    }
  }

  @override
  Future<void> stopSpeaking() async {
    _speaking = false;
    await _tts.stop();
  }

  @override
  Future<bool> isLanguageAvailable(String bcp47) async {
    final r = await _tts.isLanguageAvailable(bcp47);
    return r == true || r == 1;
  }

  @override
  void dispose() {
    _stt.cancel();
    _tts.stop();
  }
}
