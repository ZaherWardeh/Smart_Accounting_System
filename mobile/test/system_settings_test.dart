import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rima_mobile/core/system_settings.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('rima/system_settings');
  const opener = PlatformSystemSettingsOpener();
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  tearDown(() => messenger.setMockMethodCallHandler(channel, null));

  test('openVoiceInputSettings calls the native method and returns what it reports', () async {
    String? calledMethod;
    messenger.setMockMethodCallHandler(channel, (call) async {
      calledMethod = call.method;
      return true;
    });

    expect(await opener.openVoiceInputSettings(), isTrue);
    expect(calledMethod, 'openVoiceInputSettings');
  });

  test('openTtsInstallSettings calls its own native method', () async {
    String? calledMethod;
    messenger.setMockMethodCallHandler(channel, (call) async {
      calledMethod = call.method;
      return false;
    });

    expect(await opener.openTtsInstallSettings(), isFalse);
    expect(calledMethod, 'openTtsInstallSettings');
  });

  test('a platform failure (no matching Activity) is reported as false, not thrown', () async {
    messenger.setMockMethodCallHandler(channel, (call) async {
      throw PlatformException(code: 'error');
    });

    expect(await opener.openVoiceInputSettings(), isFalse);
  });

  test('no native handler at all (iOS: nothing registered) is also just false', () async {
    messenger.setMockMethodCallHandler(channel, null);
    expect(await opener.openVoiceInputSettings(), isFalse);
  });

  test('a null result is treated as false', () async {
    messenger.setMockMethodCallHandler(channel, (call) async => null);
    expect(await opener.openVoiceInputSettings(), isFalse);
  });
}
