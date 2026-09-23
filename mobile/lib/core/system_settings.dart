import 'package:flutter/services.dart';

/// Deep-links into the phone's own voice settings — Android only. There is no
/// bundling a recognizer's offline language models inside this app: Android's
/// speech recognition is a system service, and the Arabic model is downloaded
/// through the phone's own "Voice input" settings, not shipped in any APK. The
/// best this app can do is jump straight to that screen instead of leaving the
/// user to find it. Behind an interface so tests don't need a real platform channel.
abstract class SystemSettingsOpener {
  /// Opens "Voice input" settings (speech-to-text recognition language packs).
  /// True if a settings screen was opened.
  Future<bool> openVoiceInputSettings();

  /// Opens the text-to-speech engine's own "install voice data" screen.
  Future<bool> openTtsInstallSettings();
}

class PlatformSystemSettingsOpener implements SystemSettingsOpener {
  const PlatformSystemSettingsOpener();

  static const _channel = MethodChannel('rima/system_settings');

  @override
  Future<bool> openVoiceInputSettings() => _invoke('openVoiceInputSettings');

  @override
  Future<bool> openTtsInstallSettings() => _invoke('openTtsInstallSettings');

  Future<bool> _invoke(String method) async {
    try {
      return (await _channel.invokeMethod<bool>(method)) ?? false;
    } on PlatformException {
      return false;
    } on MissingPluginException {
      return false; // iOS: no native handler registered - there is no equivalent deep link there
    }
  }
}
