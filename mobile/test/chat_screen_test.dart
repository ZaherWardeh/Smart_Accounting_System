import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:rima_mobile/chat/attachment_picker.dart';
import 'package:rima_mobile/core/api_client.dart';
import 'package:rima_mobile/core/settings.dart';
import 'package:rima_mobile/core/system_settings.dart';
import 'package:rima_mobile/screens/chat_screen.dart';
import 'package:rima_mobile/voice/voice_service.dart';

import 'helpers.dart';

Widget wrap({
  required AppSettings settings,
  required ApiClient api,
  required VoiceService voice,
  AttachmentPicker? picker,
  SystemSettingsOpener? settingsOpener,
}) {
  return MultiProvider(
    providers: [
      ChangeNotifierProvider<AppSettings>.value(value: settings),
      Provider<ApiClient>.value(value: api),
      Provider<VoiceService>.value(value: voice),
      Provider<AttachmentPicker>.value(value: picker ?? FakeAttachmentPicker()),
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
      home: ChatScreen(),
    ),
  );
}

void main() {
  testWidgets('empty state explains the voice feature', (tester) async {
    final settings = await makeSettings();
    await tester.pumpWidget(wrap(
      settings: settings,
      api: fakeApi((_) async => jsonResponse({'answer': ''})),
      voice: FakeVoiceService(),
    ));

    expect(find.textContaining('اضغط على الميكروفون'), findsOneWidget);
  });

  testWidgets('typing a question shows both bubbles and Rima reads the answer aloud', (tester) async {
    final settings = await makeSettings();
    final voice = FakeVoiceService();
    await tester.pumpWidget(wrap(
      settings: settings,
      api: fakeApi((_) async => jsonResponse({'answer': 'رصيد الصندوق 800 مدين.'})),
      voice: voice,
    ));

    await tester.enterText(find.byType(TextField), 'شو رصيد الصندوق؟');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('شو رصيد الصندوق؟'), findsOneWidget);
    expect(find.text('رصيد الصندوق 800 مدين.'), findsOneWidget);
    expect(voice.spoken, ['رصيد الصندوق 800 مدين.']);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, isEmpty);
  });

  testWidgets('voice command: tap mic, speak, Rima answers out loud', (tester) async {
    final settings = await makeSettings();
    final voice = FakeVoiceService();
    await tester.pumpWidget(wrap(
      settings: settings,
      api: fakeApi((_) async => jsonResponse({'answer': 'رصيد الصندوق 800 مدين.'})),
      voice: voice,
    ));

    await tester.tap(find.byIcon(Icons.mic));
    await tester.pump();
    expect(find.text('عم سمعك... احكي هلق'), findsOneWidget); // listening banner
    expect(find.byIcon(Icons.stop), findsOneWidget); // mic turned into a stop button

    voice.hear('شو رصيد الصندوق');
    await tester.pump();
    // the live transcript shows in the banner and the text box
    expect(find.text('شو رصيد الصندوق'), findsWidgets);

    voice.hear('شو رصيد الصندوق', isFinal: true);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.byIcon(Icons.mic), findsOneWidget); // back to a mic
    expect(find.text('عم سمعك... احكي هلق'), findsNothing);
    expect(find.text('رصيد الصندوق 800 مدين.'), findsOneWidget);
    expect(voice.spoken, ['رصيد الصندوق 800 مدين.']);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, isEmpty); // transcript box cleared
  });

  testWidgets('mic problems are shown as a dismissable notice, not a crash', (tester) async {
    final settings = await makeSettings();
    final voice = FakeVoiceService()..speechAvailable = false;
    await tester.pumpWidget(wrap(
      settings: settings,
      api: fakeApi((_) async => jsonResponse({'answer': ''})),
      voice: voice,
    ));

    await tester.tap(find.byIcon(Icons.mic));
    await tester.pump();

    expect(find.textContaining('غير متاح'), findsOneWidget);
    await tester.tap(find.text('حسناً'));
    await tester.pump();
    expect(find.textContaining('غير متاح'), findsNothing);
  });

  testWidgets('a missing Arabic language pack offers a shortcut to the phone\'s voice settings', (tester) async {
    final settings = await makeSettings();
    final voice = FakeVoiceService();
    final settingsOpener = FakeSystemSettingsOpener();
    await tester.pumpWidget(wrap(
      settings: settings,
      api: fakeApi((_) async => jsonResponse({'answer': ''})),
      voice: voice,
      settingsOpener: settingsOpener,
    ));

    await tester.tap(find.byIcon(Icons.mic));
    await tester.pump();
    voice.fail('التعرف على الصوت بالعربية غير مثبّت على هذا الجهاز');
    await tester.pump();

    expect(find.textContaining('غير مثبّت'), findsOneWidget);
    expect(find.text('فتح إعدادات الصوت'), findsOneWidget);

    await tester.tap(find.text('فتح إعدادات الصوت'));
    await tester.pump();

    expect(settingsOpener.voiceInputCalls, 1);
    expect(find.textContaining('غير مثبّت'), findsOneWidget); // still shown - the user hasn't come back yet
  });

  testWidgets('when the phone has no such settings screen, the shortcut turns into plain instructions', (tester) async {
    final settings = await makeSettings();
    final voice = FakeVoiceService();
    final settingsOpener = FakeSystemSettingsOpener()..voiceInputOpens = false;
    await tester.pumpWidget(wrap(
      settings: settings,
      api: fakeApi((_) async => jsonResponse({'answer': ''})),
      voice: voice,
      settingsOpener: settingsOpener,
    ));

    await tester.tap(find.byIcon(Icons.mic));
    await tester.pump();
    voice.fail('التعرف على الصوت بالعربية غير مثبّت على هذا الجهاز');
    await tester.pump();
    await tester.tap(find.text('فتح إعدادات الصوت'));
    await tester.pump();

    expect(find.textContaining('تعذر فتح إعدادات الصوت'), findsOneWidget);
    expect(find.text('فتح إعدادات الصوت'), findsNothing);
  });

  testWidgets('a plain no-match error does not offer the settings shortcut', (tester) async {
    final settings = await makeSettings();
    final voice = FakeVoiceService();
    await tester.pumpWidget(wrap(
      settings: settings,
      api: fakeApi((_) async => jsonResponse({'answer': ''})),
      voice: voice,
    ));

    await tester.tap(find.byIcon(Icons.mic));
    await tester.pump();
    voice.fail('error_no_match');
    await tester.pump();

    expect(find.textContaining('ما سمعت'), findsOneWidget);
    expect(find.text('فتح إعدادات الصوت'), findsNothing);
  });

  testWidgets('the mute button stops Rima mid-sentence and turns auto-speak off', (tester) async {
    final settings = await makeSettings();
    final voice = FakeVoiceService()..speakGate = Completer<void>();
    await tester.pumpWidget(wrap(
      settings: settings,
      api: fakeApi((_) async => jsonResponse({'answer': 'جواب طويل'})),
      voice: voice,
    ));

    await tester.enterText(find.byType(TextField), 'سؤال');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.text('ريما عم تحكي...'), findsOneWidget); // speaking banner

    final stopsBefore = voice.stopSpeakingCalls;
    await tester.tap(find.byIcon(Icons.volume_up).first);
    await tester.pump();

    expect(settings.autoSpeak, isFalse);
    expect(voice.stopSpeakingCalls, greaterThan(stopsBefore));
    expect(find.byIcon(Icons.volume_off), findsOneWidget);

    voice.speakGate!.complete(); // let the pending speak future finish
    await tester.pump();
  });

  testWidgets('the replay button on a Rima bubble reads that message again', (tester) async {
    final settings = await makeSettings({'autoSpeak': false});
    final voice = FakeVoiceService();
    await tester.pumpWidget(wrap(
      settings: settings,
      api: fakeApi((_) async => jsonResponse({'answer': 'رصيد الصندوق 800 مدين.'})),
      voice: voice,
    ));

    await tester.enterText(find.byType(TextField), 'شو رصيد الصندوق؟');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(voice.spoken, isEmpty); // auto-speak is off

    await tester.tap(find.byIcon(Icons.volume_up_outlined));
    await tester.pump();

    expect(voice.spoken, ['رصيد الصندوق 800 مدين.']);
  });
}
