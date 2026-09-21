import 'dart:async';

import 'package:flutter/foundation.dart';

import '../core/api_client.dart';
import '../core/settings.dart';
import '../voice/voice_service.dart';

class ChatMessage {
  const ChatMessage(this.text, {required this.fromUser, this.isError = false});

  final String text;
  final bool fromUser;
  final bool isError;
}

class ChatController extends ChangeNotifier {
  ChatController({required this.api, required this.voice, required this.settings, this.finalResultGrace = const Duration(seconds: 3)});

  final ApiClient api;
  final VoiceService voice;
  final AppSettings settings;

  /// How long to wait for the recogniser's final transcript after it reports
  /// that it stopped listening (see [toggleListening]).
  final Duration finalResultGrace;

  final List<ChatMessage> messages = [];
  bool sending = false;
  bool listening = false;
  bool speaking = false;

  /// Live transcript while the mic is open.
  String partial = '';

  /// A short, dismissable hint for the user (mic unavailable, nothing heard...).
  String? notice;

  bool _disposed = false;
  Timer? _finalWait;

  @override
  void notifyListeners() {
    if (!_disposed) super.notifyListeners();
  }

  /// Sends [raw] to Rima and, if auto-speak is on, reads her reply aloud.
  Future<void> send(String raw) async {
    final text = raw.trim();
    if (text.isEmpty || sending) return;

    await _stopSpeakingQuietly();
    messages.add(ChatMessage(text, fromUser: true));
    sending = true;
    notice = null;
    notifyListeners();

    try {
      final answer = await api.askRima(settings.conversationId, text);
      messages.add(ChatMessage(answer, fromUser: false));
      sending = false;
      notifyListeners();
      if (settings.autoSpeak) unawaited(speak(answer));
    } on ApiException catch (e) {
      messages.add(ChatMessage(e.message, fromUser: false, isError: true));
      sending = false;
      notifyListeners();
    }
  }

  /// Reads [text] aloud (also used by the per-message replay button).
  Future<void> speak(String text) async {
    speaking = true;
    notifyListeners();
    try {
      await voice.speak(text);
    } catch (_) {
      notice = 'تعذر تشغيل الصوت على هذا الجهاز';
    } finally {
      speaking = false;
      notifyListeners();
    }
  }

  Future<void> stopSpeaking() async {
    await _stopSpeakingQuietly();
    notifyListeners();
  }

  Future<void> _stopSpeakingQuietly() async {
    speaking = false;
    try {
      await voice.stopSpeaking();
    } catch (_) {}
  }

  /// Mic button: starts listening, or stops early if already listening. When
  /// the recogniser finishes, whatever it heard is sent to Rima automatically.
  Future<void> toggleListening() async {
    if (listening) {
      await voice.stopListening();
      return;
    }
    await _stopSpeakingQuietly();

    final ready = await voice.initSpeech();
    if (!ready) {
      notice = 'التعرف على الصوت غير متاح. تأكد من السماح للتطبيق باستخدام الميكروفون';
      notifyListeners();
      return;
    }

    partial = '';
    listening = true;
    notice = null;
    notifyListeners();

    await voice.startListening(
      language: settings.speechLang,
      onResult: (text, isFinal) {
        if (!listening) return; // a late result after we already gave up waiting
        partial = text;
        if (isFinal) {
          _finishListening(text);
        } else {
          notifyListeners();
        }
      },
      onError: (message) {
        if (!listening) return;
        _finalWait?.cancel();
        listening = false;
        partial = '';
        notice = _friendlyError(message);
        notifyListeners();
      },
      // "Stopped listening" does NOT mean "finished transcribing": on Android the
      // engine reports it first and delivers the final transcript a moment later.
      // Sending the running partial here dropped the last word, so wait for the
      // final result and only fall back to the partial if it never comes.
      onDone: () {
        if (!listening) return;
        _finalWait?.cancel();
        _finalWait = Timer(finalResultGrace, () => _finishListening(partial));
      },
    );
  }

  String _friendlyError(String message) {
    final m = message.toLowerCase();
    if (m.contains('no_match') || m.contains('speech_timeout')) {
      return 'ما سمعت شي، جرّب مرة ثانية';
    }
    return message; // already user-facing for our own messages, raw for engine errors
  }

  void _finishListening(String text) {
    if (!listening) return; // the final result and the "done" status both land here
    _finalWait?.cancel();
    listening = false;
    partial = '';
    final heard = text.trim();
    if (heard.isEmpty) {
      notice = 'ما سمعت شي، جرّب مرة ثانية';
      notifyListeners();
      return;
    }
    notifyListeners();
    unawaited(send(heard));
  }

  void dismissNotice() {
    notice = null;
    notifyListeners();
  }

  Future<void> newConversation() async {
    await _stopSpeakingQuietly();
    if (listening) {
      _finalWait?.cancel();
      listening = false;
      partial = '';
      try {
        await voice.stopListening();
      } catch (_) {}
    }
    messages.clear();
    notice = null;
    await settings.newConversation();
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _finalWait?.cancel();
    unawaited(voice.stopSpeaking());
    unawaited(voice.stopListening());
    super.dispose();
  }
}
