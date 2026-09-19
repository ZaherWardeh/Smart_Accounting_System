import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

class AppSettings extends ChangeNotifier {
  AppSettings(this._prefs);

  static Future<AppSettings> load() async => AppSettings(await SharedPreferences.getInstance());

  /// Android emulator's alias for the host machine's localhost.
  static const defaultBaseUrl = 'http://10.0.2.2:8000';

  final SharedPreferences _prefs;

  String get baseUrl => _prefs.getString('baseUrl') ?? defaultBaseUrl;

  Future<void> setBaseUrl(String v) async {
    await _prefs.setString('baseUrl', v.trim());
    notifyListeners();
  }

  /// Whether Rima reads every reply out loud. On by default.
  bool get autoSpeak => _prefs.getBool('autoSpeak') ?? true;

  Future<void> setAutoSpeak(bool v) async {
    await _prefs.setBool('autoSpeak', v);
    notifyListeners();
  }

  /// Language used for speech recognition: "ar" or "en".
  String get speechLang => _prefs.getString('speechLang') ?? 'ar';

  Future<void> setSpeechLang(String v) async {
    await _prefs.setString('speechLang', v);
    notifyListeners();
  }

  /// Identifies this chat to the server's per-conversation memory. Stable
  /// across app restarts until the user starts a new conversation.
  String get conversationId {
    var id = _prefs.getString('conversationId');
    if (id == null) {
      id = const Uuid().v4();
      _prefs.setString('conversationId', id);
    }
    return id;
  }

  Future<void> newConversation() async {
    await _prefs.setString('conversationId', const Uuid().v4());
    notifyListeners();
  }
}
