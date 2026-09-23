import 'dart:async';

import 'package:flutter/foundation.dart';

import '../core/api_client.dart';
import '../core/settings.dart';
import '../core/system_settings.dart';
import '../models/models.dart';
import '../voice/voice_service.dart';
import 'attachment_picker.dart';

class ChatMessage {
  const ChatMessage(this.text, {required this.fromUser, this.isError = false, this.imageBytes});

  final String text;
  final bool fromUser;
  final bool isError;

  /// The document image the user sent with this message (shown as a thumbnail).
  final Uint8List? imageBytes;
}

class ChatController extends ChangeNotifier {
  ChatController({
    required this.api,
    required this.voice,
    required this.settings,
    AttachmentPicker? picker,
    SystemSettingsOpener? settingsOpener,
    this.finalResultGrace = const Duration(seconds: 3),
    this.pendingIdleAlert = const Duration(seconds: 60),
  })  : picker = picker ?? const GalleryAttachmentPicker(),
        settingsOpener = settingsOpener ?? const PlatformSystemSettingsOpener();

  final ApiClient api;
  final VoiceService voice;
  final AppSettings settings;
  final AttachmentPicker picker;
  final SystemSettingsOpener settingsOpener;

  /// How long to wait for the recogniser's final transcript after it reports
  /// that it stopped listening (see [toggleListening]).
  final Duration finalResultGrace;

  /// Silence after which an unsaved operation triggers the "you have an
  /// unsaved operation" alert (see [pendingAlert]).
  final Duration pendingIdleAlert;

  final List<ChatMessage> messages = [];
  bool sending = false;
  bool listening = false;
  bool speaking = false;

  /// Live transcript while the mic is open.
  String partial = '';

  /// A short, dismissable hint for the user (mic unavailable, nothing heard...).
  String? notice;

  /// True when [notice] is specifically "this language isn't installed on the
  /// device" - the notice bar then offers a shortcut to the phone's own voice
  /// settings (see [openVoiceSettings]). There is no bundling the recognizer's
  /// language model inside the app: Android's speech recognition is a system
  /// service, so the best this app can do is jump straight to where the phone
  /// downloads it.
  bool voiceSetupNeeded = false;

  /// The document image picked but not sent yet.
  RimaAttachment? attachment;

  /// Operations Rima is still collecting (a transaction / a new account) that
  /// haven't been saved. The server owns them; this mirrors its last answer.
  List<PendingDraft> pending = const [];

  /// True once the user has been silent for [pendingIdleAlert] while something
  /// is unsaved: the chat shows the alert and Rima says it out loud.
  bool pendingAlert = false;

  bool _disposed = false;
  Timer? _finalWait;
  Timer? _idle;

  @override
  void notifyListeners() {
    if (!_disposed) super.notifyListeners();
  }

  // ---- sending ------------------------------------------------------------

  /// Sends [raw] (and the picked document, if any) to Rima and, if auto-speak
  /// is on, reads her reply aloud. A document can be sent with no text.
  Future<void> send(String raw) async {
    final text = raw.trim();
    final doc = attachment;
    if ((text.isEmpty && doc == null) || sending) return;

    _idle?.cancel();
    pendingAlert = false;
    await _stopSpeakingQuietly();
    messages.add(ChatMessage(text.isEmpty ? '📎 ${doc!.name}' : text, fromUser: true, imageBytes: doc?.bytes));
    attachment = null;
    sending = true;
    notice = null;
    voiceSetupNeeded = false;
    notifyListeners();

    try {
      final reply = await api.askRimaFull(settings.conversationId, text, attachment: doc);
      messages.add(ChatMessage(reply.answer, fromUser: false));
      pending = reply.pendingDrafts;
      sending = false;
      notifyListeners();
      _armIdle();
      if (settings.autoSpeak) unawaited(speak(reply.answer));
    } on ApiException catch (e) {
      messages.add(ChatMessage(e.message, fromUser: false, isError: true));
      attachment = doc; // let the user retry without picking the image again
      sending = false;
      notifyListeners();
    }
  }

  // ---- document attachment ------------------------------------------------

  Future<void> pickAttachment() async {
    try {
      final picked = await picker.pickFromGallery();
      if (picked == null) return;
      attachment = picked;
      notice = null;
      voiceSetupNeeded = false;
      userActivity();
      notifyListeners();
    } catch (_) {
      notice = 'تعذر فتح المعرض. تأكد من السماح للتطبيق بالوصول إلى الصور';
      notifyListeners();
    }
  }

  void clearAttachment() {
    attachment = null;
    notifyListeners();
  }

  // ---- unsaved operations -------------------------------------------------

  /// Asks the server what is still open in this conversation (used when the
  /// chat opens, so an unsaved operation is never forgotten across restarts).
  Future<void> refreshPending() async {
    try {
      pending = await api.pendingDrafts(settings.conversationId);
      notifyListeners();
      _armIdle();
    } catch (_) {
      // best effort: the next reply carries the list anyway
    }
  }

  String get pendingAlertText =>
      'لسا عندك عملية غير محفوظة: ${pending.map((p) => p.summaryAr).join('، ')}. بدك تأكدها، تعدلها، أو تلغيها؟';

  void _armIdle() {
    _idle?.cancel();
    if (pending.isEmpty || _disposed) return;
    _idle = Timer(pendingIdleAlert, _onIdle);
  }

  void _onIdle() {
    if (_disposed || pending.isEmpty || sending || listening) return;
    pendingAlert = true;
    notifyListeners();
    if (settings.autoSpeak) unawaited(speak(pendingAlertText));
  }

  /// The user is doing something (typing, picking a file, talking): push the
  /// idle alert further away, and hide it if it was showing.
  void userActivity() {
    if (pending.isEmpty) return;
    if (pendingAlert) {
      pendingAlert = false;
      notifyListeners();
    }
    _armIdle();
  }

  /// A real Confirm press: the server saves exactly what the draft says.
  Future<void> confirmPending(String kind) async {
    if (sending) return;
    _idle?.cancel();
    pendingAlert = false;
    sending = true;
    notice = null;
    voiceSetupNeeded = false;
    notifyListeners();
    try {
      final done = await api.confirmDraft(settings.conversationId, kind);
      messages.add(ChatMessage(done.messageAr, fromUser: false));
      pending = done.pendingDrafts;
      sending = false;
      notifyListeners();
      _armIdle();
      if (settings.autoSpeak) unawaited(speak(done.messageAr));
    } on ApiException catch (e) {
      sending = false;
      notice = e.message;
      voiceSetupNeeded = false;
      notifyListeners();
      await refreshPending();
    }
  }

  Future<void> cancelPending(String kind) async {
    if (sending) return;
    _idle?.cancel();
    pendingAlert = false;
    sending = true;
    notice = null;
    voiceSetupNeeded = false;
    notifyListeners();
    try {
      pending = await api.cancelDraft(settings.conversationId, kind);
      messages.add(const ChatMessage('تم إلغاء العملية غير المحفوظة.', fromUser: false));
      sending = false;
      notifyListeners();
      _armIdle();
    } on ApiException catch (e) {
      sending = false;
      notice = e.message;
      voiceSetupNeeded = false;
      notifyListeners();
    }
  }

  /// "Modify": hand it back to Rima, who re-opens the draft and asks what to change.
  Future<void> modifyPending() => send('بدي أعدّل على العملية غير المحفوظة');

  // ---- speaking -----------------------------------------------------------

  /// Reads [text] aloud (also used by the per-message replay button).
  Future<void> speak(String text) async {
    speaking = true;
    notifyListeners();
    try {
      await voice.speak(text);
    } catch (_) {
      notice = 'تعذر تشغيل الصوت على هذا الجهاز';
      voiceSetupNeeded = false;
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

  // ---- voice input --------------------------------------------------------

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
      voiceSetupNeeded = false;
      notifyListeners();
      return;
    }

    partial = '';
    listening = true;
    notice = null;
    voiceSetupNeeded = false;
    if (pendingAlert) pendingAlert = false;
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
        voiceSetupNeeded = _isMissingLanguagePack(message);
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

  bool _isMissingLanguagePack(String message) => message.contains('غير مثبّت') || message.contains('not installed');

  /// Jumps to the phone's own "Voice input" settings, where the missing
  /// language pack is downloaded (see [voiceSetupNeeded]).
  Future<void> openVoiceSettings() async {
    final opened = await settingsOpener.openVoiceInputSettings();
    if (!opened) {
      notice = 'تعذر فتح إعدادات الصوت تلقائياً. جرّب من إعدادات الجهاز ← اللغات والإدخال ← الإدخال الصوتي';
      voiceSetupNeeded = false;
      notifyListeners();
    }
  }

  void _finishListening(String text) {
    if (!listening) return; // the final result and the "done" status both land here
    _finalWait?.cancel();
    listening = false;
    partial = '';
    final heard = text.trim();
    if (heard.isEmpty) {
      notice = 'ما سمعت شي، جرّب مرة ثانية';
      voiceSetupNeeded = false;
      notifyListeners();
      return;
    }
    notifyListeners();
    unawaited(send(heard));
  }

  void dismissNotice() {
    notice = null;
    voiceSetupNeeded = false;
    notifyListeners();
  }

  // ---- conversation -------------------------------------------------------

  /// Starts a fresh conversation. Unsaved operations belong to the old one, so
  /// the caller decides what happens to them: [discardPending] cancels them on
  /// the server first (the screen asks the user before passing true).
  Future<void> newConversation({bool discardPending = false}) async {
    await _stopSpeakingQuietly();
    if (listening) {
      _finalWait?.cancel();
      listening = false;
      partial = '';
      try {
        await voice.stopListening();
      } catch (_) {}
    }
    if (discardPending) {
      for (final p in pending) {
        try {
          await api.cancelDraft(settings.conversationId, p.kind);
        } catch (_) {}
      }
    }
    _idle?.cancel();
    pending = const [];
    pendingAlert = false;
    attachment = null;
    messages.clear();
    notice = null;
    voiceSetupNeeded = false;
    await settings.newConversation();
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _finalWait?.cancel();
    _idle?.cancel();
    unawaited(voice.stopSpeaking());
    unawaited(voice.stopListening());
    super.dispose();
  }
}
