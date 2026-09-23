import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';
import 'package:rima_mobile/chat/attachment_picker.dart';
import 'package:rima_mobile/core/api_client.dart';
import 'package:rima_mobile/core/settings.dart';
import 'package:rima_mobile/core/system_settings.dart';
import 'package:rima_mobile/models/models.dart';
import 'package:rima_mobile/screens/chat_screen.dart';
import 'package:rima_mobile/screens/transactions_screen.dart';
import 'package:rima_mobile/voice/voice_service.dart';

import 'chat_pending_test.dart' show FakeServer, draftJson;
import 'helpers.dart';

Widget wrap({
  required AppSettings settings,
  required ApiClient api,
  required VoiceService voice,
  required AttachmentPicker picker,
  SystemSettingsOpener? settingsOpener,
  Widget home = const ChatScreen(),
}) {
  return MultiProvider(
    providers: [
      ChangeNotifierProvider<AppSettings>.value(value: settings),
      Provider<ApiClient>.value(value: api),
      Provider<VoiceService>.value(value: voice),
      Provider<AttachmentPicker>.value(value: picker),
      Provider<SystemSettingsOpener>.value(value: settingsOpener ?? FakeSystemSettingsOpener()),
    ],
    child: MaterialApp(
      locale: const Locale('ar'),
      supportedLocales: const [Locale('ar')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: home,
    ),
  );
}

Future<(FakeServer, FakeVoiceService, FakeAttachmentPicker)> pumpChat(WidgetTester tester, {List<Map<String, dynamic>> pending = const []}) async {
  tester.view.physicalSize = const Size(900, 2200);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  final settings = await makeSettings({'autoSpeak': false});
  final server = FakeServer()..pending = List.of(pending);
  final voice = FakeVoiceService();
  final picker = FakeAttachmentPicker();
  await tester.pumpWidget(wrap(settings: settings, api: fakeApi(server.handle), voice: voice, picker: picker));
  await tester.pumpAndSettle();
  return (server, voice, picker);
}

void main() {
  group('pending operation card', () {
    testWidgets('a draft left open from before is shown when the chat opens, with what is missing', (tester) async {
      await pumpChat(tester, pending: [draftJson()]);

      expect(find.byKey(const Key('pending-card')), findsOneWidget);
      expect(find.textContaining('قيد: مدين 0010301 - صندوق'), findsOneWidget);
      expect(find.text('ناقص: حساب الدائن'), findsOneWidget);
      expect(find.byKey(const Key('confirm-transaction')), findsNothing); // can't confirm what is incomplete
      expect(find.byKey(const Key('modify-transaction')), findsOneWidget);
      expect(find.byKey(const Key('cancel-transaction')), findsOneWidget);
    });

    testWidgets('a complete draft offers Confirm', (tester) async {
      await pumpChat(tester, pending: [draftJson(ready: true, next: 'confirmation')]);
      expect(find.text('جاهزة للتأكيد'), findsOneWidget);
      expect(find.byKey(const Key('confirm-transaction')), findsOneWidget);
    });

    testWidgets('no card when nothing is pending', (tester) async {
      await pumpChat(tester);
      expect(find.byKey(const Key('pending-card')), findsNothing);
    });

    testWidgets('Confirm saves it: server called, card gone, result shown in the chat', (tester) async {
      final (server, _, _) = await pumpChat(tester, pending: [draftJson(ready: true, next: 'confirmation')]);

      await tester.tap(find.byKey(const Key('confirm-transaction')));
      await tester.pumpAndSettle();

      expect(server.count('/transaction/confirm'), 1);
      expect(find.byKey(const Key('pending-card')), findsNothing);
      expect(find.text('تم حفظ القيد رقم 41.'), findsOneWidget);
    });

    testWidgets('Abort cancels it', (tester) async {
      final (server, _, _) = await pumpChat(tester, pending: [draftJson()]);

      await tester.tap(find.byKey(const Key('cancel-transaction')));
      await tester.pumpAndSettle();

      expect(server.count('/transaction/cancel'), 1);
      expect(find.byKey(const Key('pending-card')), findsNothing);
      expect(find.textContaining('تم إلغاء'), findsOneWidget);
    });

    testWidgets('Modify sends the request through the chat', (tester) async {
      final (server, _, _) = await pumpChat(tester, pending: [draftJson(ready: true, next: 'confirmation')]);

      await tester.tap(find.byKey(const Key('modify-transaction')));
      await tester.pumpAndSettle();

      expect(server.lastAsk!['question'], contains('أعدّل'));
    });

    testWidgets('after a minute of silence the card turns into an alert', (tester) async {
      await pumpChat(tester, pending: [draftJson()]);
      expect(find.text('عملية غير محفوظة'), findsOneWidget);

      await tester.pump(const Duration(seconds: 61));

      expect(find.text('لسا عندك عملية غير محفوظة!'), findsOneWidget);
    });

    testWidgets('typing keeps the alert away', (tester) async {
      await pumpChat(tester, pending: [draftJson()]);
      await tester.pump(const Duration(seconds: 50));
      await tester.enterText(find.byType(TextField), 'ط');
      await tester.pump(const Duration(seconds: 50));

      expect(find.text('عملية غير محفوظة'), findsOneWidget); // still the calm card, not the alert
      await tester.pump(const Duration(seconds: 20));
      expect(find.text('لسا عندك عملية غير محفوظة!'), findsOneWidget);
    });

    testWidgets('a new conversation with something unsaved asks first; going back changes nothing', (tester) async {
      final (server, _, _) = await pumpChat(tester, pending: [draftJson()]);

      await tester.tap(find.byTooltip('محادثة جديدة'));
      await tester.pumpAndSettle();
      expect(find.text('عندك عملية غير محفوظة'), findsOneWidget);

      await tester.tap(find.text('رجوع'));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('pending-card')), findsOneWidget);
      expect(server.count('/cancel'), 0);
    });

    testWidgets('...and confirming the dialog aborts the operation and starts fresh', (tester) async {
      final (server, _, _) = await pumpChat(tester, pending: [draftJson()]);

      await tester.tap(find.byTooltip('محادثة جديدة'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('إلغاء العملية وبدء محادثة جديدة'));
      await tester.pumpAndSettle();

      expect(server.count('/transaction/cancel'), 1);
      expect(find.byKey(const Key('pending-card')), findsNothing);
    });

    testWidgets('a new conversation with nothing pending needs no confirmation', (tester) async {
      await pumpChat(tester);
      await tester.tap(find.byTooltip('محادثة جديدة'));
      await tester.pumpAndSettle();
      expect(find.text('عندك عملية غير محفوظة'), findsNothing);
    });
  });

  group('attaching a document', () {
    testWidgets('pick -> preview -> send with no text -> thumbnail in the chat and image in the request', (tester) async {
      final (server, _, picker) = await pumpChat(tester);
      picker.next = RimaAttachment(bytes: tinyPng, name: 'bill.png');

      await tester.tap(find.byTooltip('إرفاق صورة مستند'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('attachment-preview')), findsOneWidget);
      expect(find.text('bill.png'), findsOneWidget);

      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();

      expect(server.lastAsk!['attachment']['filename'], 'bill.png');
      expect(find.byKey(const Key('attachment-preview')), findsNothing);
      expect(find.byKey(const Key('message-image')), findsOneWidget);
    });

    testWidgets('the preview can be dismissed and nothing is sent', (tester) async {
      final (server, _, picker) = await pumpChat(tester);
      picker.next = RimaAttachment(bytes: tinyPng, name: 'bill.png');

      await tester.tap(find.byTooltip('إرفاق صورة مستند'));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('إزالة المرفق'));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('attachment-preview')), findsNothing);
      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();
      expect(server.requests.where((r) => r.url.path == '/reports/ask_ai'), isEmpty);
    });

    testWidgets('a gallery error shows a notice', (tester) async {
      final (_, _, picker) = await pumpChat(tester);
      picker.throws = true;
      await tester.tap(find.byTooltip('إرفاق صورة مستند'));
      await tester.pumpAndSettle();
      expect(find.textContaining('المعرض'), findsOneWidget);
    });
  });

  group('documents saved with entries', () {
    Future<void> pumpTransactions(WidgetTester tester, {required bool documentOk}) async {
      tester.view.physicalSize = const Size(900, 2200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      final settings = await makeSettings();
      final api = fakeApi((req) async {
        if (req.url.path == '/transactions/') {
          return jsonResponse([
            {'id': 1, 'date': '2026-01-01T00:00:00', 'notes': 'بدون مستند', 'has_document': false, 'details': []},
            {'id': 2, 'date': '2026-01-02T00:00:00', 'notes': 'فاتورة كهرباء', 'has_document': true, 'details': []},
          ]);
        }
        if (req.url.path == '/transactions/2/document') {
          return documentOk ? http.Response.bytes(tinyPng, 200) : jsonResponse({'detail': 'nope'}, status: 404);
        }
        return http.Response('nf', 404);
      });
      await tester.pumpWidget(wrap(
        settings: settings,
        api: api,
        voice: FakeVoiceService(),
        picker: FakeAttachmentPicker(),
        home: const TransactionsScreen(),
      ));
      await tester.pumpAndSettle();
    }

    testWidgets('only entries with a document get a paperclip, and it opens the image', (tester) async {
      await pumpTransactions(tester, documentOk: true);

      expect(find.byKey(const Key('document-1')), findsNothing);
      expect(find.byKey(const Key('document-2')), findsOneWidget);

      await tester.tap(find.byKey(const Key('document-2')));
      await tester.pumpAndSettle();

      expect(find.text('مستند القيد 2'), findsOneWidget);
      expect(find.byKey(const Key('document-viewer')), findsOneWidget);
    });

    testWidgets('a missing document shows a message with retry, not a crash', (tester) async {
      await pumpTransactions(tester, documentOk: false);
      await tester.tap(find.byKey(const Key('document-2')));
      await tester.pumpAndSettle();
      expect(find.textContaining('ما في مستند'), findsOneWidget);
      expect(find.text('إعادة المحاولة'), findsOneWidget);
    });
  });
}
