import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:rima_mobile/chat/attachment_picker.dart';
import 'package:rima_mobile/core/api_client.dart';
import 'package:rima_mobile/core/settings.dart';
import 'package:rima_mobile/core/system_settings.dart';
import 'package:rima_mobile/screens/settings_screen.dart';
import 'package:rima_mobile/voice/voice_service.dart';

import 'helpers.dart';

Widget wrap({
  required AppSettings settings,
  ApiClient? api,
  VoiceService? voice,
  SystemSettingsOpener? settingsOpener,
}) {
  return MultiProvider(
    providers: [
      ChangeNotifierProvider<AppSettings>.value(value: settings),
      Provider<ApiClient>.value(value: api ?? fakeApi((_) async => jsonResponse({'status': 'ok'}))),
      Provider<VoiceService>.value(value: voice ?? FakeVoiceService()),
      Provider<AttachmentPicker>.value(value: FakeAttachmentPicker()),
      Provider<SystemSettingsOpener>.value(value: settingsOpener ?? FakeSystemSettingsOpener()),
    ],
    child: const MaterialApp(
      locale: Locale('ar'),
      supportedLocales: [Locale('ar')],
      localizationsDelegates: [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: SettingsScreen(),
    ),
  );
}

/// The settings list is taller than the default 800x600 test viewport, which
/// makes tap() miss real (but off-screen) widgets - see the Flutter test note
/// on hitTestWarningShouldBeFatal. Every test here needs the taller viewport.
Future<void> tallScreen(WidgetTester tester) async {
  tester.view.physicalSize = const Size(900, 3000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

void main() {
  testWidgets('offers a shortcut to the device\'s voice-input settings on Android', (tester) async {
    await tallScreen(tester);
    final opener = FakeSystemSettingsOpener();
    await tester.pumpWidget(wrap(settings: await makeSettings(), settingsOpener: opener));

    expect(find.text('إعدادات الإدخال الصوتي بالجهاز'), findsOneWidget);
    await tester.tap(find.text('إعدادات الإدخال الصوتي بالجهاز'));
    await tester.pump();

    expect(opener.voiceInputCalls, 1);
  });

  testWidgets('no such deep link on iOS, so the shortcut is not shown', (tester) async {
    await tallScreen(tester);
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;

    await tester.pumpWidget(wrap(settings: await makeSettings()));

    expect(find.text('إعدادات الإدخال الصوتي بالجهاز'), findsNothing);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('when nothing could be opened, a plain-instructions message is shown instead', (tester) async {
    await tallScreen(tester);
    final opener = FakeSystemSettingsOpener()..voiceInputOpens = false;
    await tester.pumpWidget(wrap(settings: await makeSettings(), settingsOpener: opener));

    await tester.tap(find.text('إعدادات الإدخال الصوتي بالجهاز'));
    await tester.pump(); // the async openVoiceInputSettings() call completes
    await tester.pump(const Duration(milliseconds: 300)); // SnackBar entrance animation

    expect(find.textContaining('تعذر فتح الإعدادات'), findsOneWidget);
  });

  testWidgets('trying Rima\'s voice when no Arabic voice is installed offers to open TTS settings', (tester) async {
    final opener = FakeSystemSettingsOpener();
    final voice = FakeVoiceService()..arabicAvailable = false;
    await tester.pumpWidget(wrap(settings: await makeSettings(), voice: voice, settingsOpener: opener));

    await tester.tap(find.text('جرّب صوت ريما'));
    await tester.pump();

    expect(find.textContaining('صوت عربي غير مثبّت'), findsOneWidget);
    // The SnackBar floats at the Scaffold's bottom edge; invoking its action directly
    // sidesteps hit-test geometry that a custom test viewport doesn't model reliably.
    final action = tester.widget<SnackBarAction>(find.byType(SnackBarAction));
    action.onPressed();
    await tester.pump();

    expect(opener.ttsInstallCalls, 1);
  });

  testWidgets('when an Arabic voice IS installed, no snackbar is shown at all', (tester) async {
    await tallScreen(tester);
    await tester.pumpWidget(wrap(settings: await makeSettings()));

    await tester.tap(find.text('جرّب صوت ريما'));
    await tester.pump();

    expect(find.textContaining('غير مثبّت'), findsNothing);
  });
}
