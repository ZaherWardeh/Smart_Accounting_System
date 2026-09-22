import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:rima_mobile/chat/chat_controller.dart';
import 'package:rima_mobile/core/settings.dart';
import 'package:rima_mobile/models/models.dart';

import 'helpers.dart';

Map<String, dynamic> draftJson({bool ready = false, String next = 'credit_account', String kind = 'transaction'}) => {
      'kind': kind,
      'status': ready ? 'awaiting_confirmation' : 'collecting',
      'next_step': next,
      'ready_to_confirm': ready,
      'draft': kind == 'transaction'
          ? {
              'debit_account': {'id': 7, 'code': '0010301', 'name': 'صندوق'},
              'credit_account': ready ? {'id': 16, 'code': '00301', 'name': 'المبيعات'} : null,
              'amount': ready ? 100 : null,
            }
          : {'name': 'محروقات'},
    };

/// A scriptable fake of the whole Rima backend.
class FakeServer {
  final List<http.Request> requests = [];
  List<Map<String, dynamic>> pending = [];
  String answer = 'تمام';
  int? failWith;
  Map<String, dynamic>? lastAsk;

  Future<http.Response> handle(http.Request req) async {
    requests.add(req);
    final path = req.url.path;
    if (failWith != null) return jsonResponse({'detail': 'boom'}, status: failWith!);
    if (path == '/reports/ask_ai') {
      lastAsk = jsonDecode(utf8.decode(req.bodyBytes)) as Map<String, dynamic>;
      return jsonResponse({'answer': answer, 'pending_drafts': pending});
    }
    if (req.method == 'GET' && path.startsWith('/drafts/')) return jsonResponse(pending);
    if (path.endsWith('/confirm')) {
      pending = [];
      return jsonResponse({'ok': true, 'transaction_id': 41, 'pending_drafts': pending});
    }
    if (path.endsWith('/cancel')) {
      pending = [];
      return jsonResponse({'ok': true, 'cancelled': true, 'pending_drafts': pending});
    }
    return http.Response('not found', 404);
  }

  int count(String suffix) => requests.where((r) => r.url.path.endsWith(suffix)).length;
}

Future<(ChatController, FakeServer, FakeVoiceService, FakeAttachmentPicker, AppSettings)> make({
  Duration idle = const Duration(milliseconds: 80),
  Map<String, Object> prefs = const {},
}) async {
  final settings = await makeSettings(prefs);
  final server = FakeServer();
  final voice = FakeVoiceService();
  final picker = FakeAttachmentPicker();
  final chat = ChatController(
    api: fakeApi(server.handle),
    voice: voice,
    settings: settings,
    picker: picker,
    finalResultGrace: const Duration(milliseconds: 50),
    pendingIdleAlert: idle,
  );
  return (chat, server, voice, picker, settings);
}

Future<void> settle([int ms = 20]) => Future<void>.delayed(Duration(milliseconds: ms));

void main() {
  group('document attachment', () {
    test('a picked image is held until sent, then goes out with the message and shows as a thumbnail', () async {
      final (chat, server, _, picker, _) = await make();
      picker.next = RimaAttachment(bytes: tinyPng, name: 'bill.png');

      await chat.pickAttachment();
      expect(chat.attachment?.name, 'bill.png');

      await chat.send('سجل هالفاتورة');
      await settle();

      expect(chat.attachment, isNull); // consumed
      expect(chat.messages.first.imageBytes, tinyPng);
      expect(server.lastAsk!['question'], 'سجل هالفاتورة');
      expect(server.lastAsk!['attachment']['filename'], 'bill.png');
    });

    test('an image can be sent with no text at all', () async {
      final (chat, server, _, picker, _) = await make();
      picker.next = RimaAttachment(bytes: tinyPng, name: 'a.png');
      await chat.pickAttachment();

      await chat.send('   ');
      await settle();

      expect(server.lastAsk!['question'], '');
      expect(server.lastAsk!['attachment'], isNotNull);
      expect(chat.messages.first.text, contains('a.png'));
    });

    test('no text and no image sends nothing', () async {
      final (chat, server, _, _, _) = await make();
      await chat.send('  ');
      expect(server.requests, isEmpty);
    });

    test('backing out of the gallery keeps things as they were', () async {
      final (chat, _, _, picker, _) = await make();
      picker.next = null;
      await chat.pickAttachment();
      expect(chat.attachment, isNull);
      expect(chat.notice, isNull);
    });

    test('a gallery failure is a notice, not a crash', () async {
      final (chat, _, _, picker, _) = await make();
      picker.throws = true;
      await chat.pickAttachment();
      expect(chat.notice, contains('المعرض'));
    });

    test('the attachment can be removed before sending', () async {
      final (chat, _, _, picker, _) = await make();
      picker.next = RimaAttachment(bytes: tinyPng, name: 'a.png');
      await chat.pickAttachment();
      chat.clearAttachment();
      expect(chat.attachment, isNull);
    });

    test('a failed send gives the image back so the user can retry', () async {
      final (chat, server, _, picker, _) = await make();
      picker.next = RimaAttachment(bytes: tinyPng, name: 'a.png');
      await chat.pickAttachment();
      server.failWith = 500;

      await chat.send('سجل');
      await settle();

      expect(chat.messages.last.isError, isTrue);
      expect(chat.attachment?.name, 'a.png');
    });
  });

  group('unsaved operations', () {
    test('a reply that leaves a draft open puts it in the pending list', () async {
      final (chat, server, _, _, _) = await make();
      server.pending = [draftJson()];

      await chat.send('بدي أسجل قيد');
      await settle();

      expect(chat.pending.single.kind, 'transaction');
      expect(chat.pending.single.readyToConfirm, isFalse);
      chat.dispose();
    });

    test('opening the chat picks up a draft left from before (refreshPending)', () async {
      final (chat, server, _, _, _) = await make();
      server.pending = [draftJson(ready: true, next: 'confirmation')];
      await chat.refreshPending();
      expect(chat.pending.single.readyToConfirm, isTrue);
      expect(server.requests.single.url.path, startsWith('/drafts/'));
      chat.dispose();
    });

    test('refreshPending failing is silent (offline is not an error here)', () async {
      final (chat, server, _, _, _) = await make();
      server.failWith = 500;
      await chat.refreshPending();
      expect(chat.pending, isEmpty);
      expect(chat.notice, isNull);
    });

    test('after the idle period the alert fires once and Rima says it aloud', () async {
      final (chat, server, voice, _, _) = await make();
      server.pending = [draftJson()];
      await chat.send('بدي أسجل قيد');
      await settle(10);
      voice.spoken.clear();
      expect(chat.pendingAlert, isFalse);

      await settle(200);

      expect(chat.pendingAlert, isTrue);
      expect(voice.spoken.single, contains('عملية غير محفوظة'));
      expect(voice.spoken.single, contains('صندوق'));
      await settle(200);
      expect(voice.spoken.length, 1); // once, not a nag loop
      chat.dispose();
    });

    test('the alert is silent when auto-speak is off, but still shown', () async {
      final (chat, server, voice, _, _) = await make(prefs: {'autoSpeak': false});
      server.pending = [draftJson()];
      await chat.send('بدي أسجل قيد');
      await settle(200);
      expect(chat.pendingAlert, isTrue);
      expect(voice.spoken, isEmpty);
      chat.dispose();
    });

    test('typing keeps pushing the alert away, and hides it if it was showing', () async {
      final (chat, server, _, _, _) = await make(idle: const Duration(milliseconds: 120));
      server.pending = [draftJson()];
      await chat.send('بدي أسجل قيد');
      for (var i = 0; i < 4; i++) {
        await settle(60);
        chat.userActivity(); // still typing
      }
      expect(chat.pendingAlert, isFalse);

      await settle(250);
      expect(chat.pendingAlert, isTrue);
      chat.userActivity();
      expect(chat.pendingAlert, isFalse);
      chat.dispose();
    });

    test('no alert when nothing is pending', () async {
      final (chat, _, voice, _, _) = await make();
      await chat.send('مرحبا');
      await settle(200);
      expect(chat.pendingAlert, isFalse);
      expect(voice.spoken, ['تمام']); // only Rima's answer
    });

    test('no alert while a message is in flight or the mic is open', () async {
      final (chat, server, voice, _, _) = await make();
      server.pending = [draftJson()];
      await chat.send('x');
      await settle(10);
      await chat.toggleListening(); // mic open: the user is actively talking
      await settle(200);
      expect(chat.pendingAlert, isFalse);
      voice.finish();
      chat.dispose();
    });

    test('Confirm calls the server, reports what was saved, and clears the pending list', () async {
      final (chat, server, voice, _, _) = await make();
      server.pending = [draftJson(ready: true, next: 'confirmation')];
      await chat.send('سجل');
      await settle();
      voice.spoken.clear();

      await chat.confirmPending('transaction');
      await settle();

      expect(server.count('/transaction/confirm'), 1);
      expect(chat.messages.last.text, 'تم حفظ القيد رقم 41.');
      expect(chat.pending, isEmpty);
      expect(chat.pendingAlert, isFalse);
      expect(voice.spoken, ['تم حفظ القيد رقم 41.']);
      chat.dispose();
    });

    test('Confirm refused by the server shows why and re-reads the pending list', () async {
      final (chat, server, _, _, _) = await make();
      server.pending = [draftJson()];
      await chat.send('سجل');
      await settle();
      server.failWith = 409;

      await chat.confirmPending('transaction');

      expect(chat.notice, isNotNull);
      expect(chat.sending, isFalse);
      chat.dispose();
    });

    test('Abort cancels the draft on the server', () async {
      final (chat, server, _, _, _) = await make();
      server.pending = [draftJson()];
      await chat.send('سجل');
      await settle();

      await chat.cancelPending('transaction');

      expect(server.count('/transaction/cancel'), 1);
      expect(chat.pending, isEmpty);
      expect(chat.messages.last.text, contains('تم إلغاء'));
      chat.dispose();
    });

    test('Modify hands the operation back to Rima as a chat message', () async {
      final (chat, server, _, _, _) = await make();
      server.pending = [draftJson(ready: true, next: 'confirmation')];
      await chat.send('سجل');
      await settle();

      await chat.modifyPending();
      await settle();

      expect(server.lastAsk!['question'], contains('أعدّل'));
      expect(chat.messages.where((m) => m.fromUser).length, 2);
      chat.dispose();
    });

    test('a new conversation can discard the pending operations first', () async {
      final (chat, server, _, _, settings) = await make();
      server.pending = [draftJson(), draftJson(kind: 'account', next: 'parent_account')];
      await chat.send('سجل');
      await settle();
      final oldId = settings.conversationId;

      await chat.newConversation(discardPending: true);

      expect(server.count('/transaction/cancel'), 1);
      expect(server.count('/account/cancel'), 1);
      expect(chat.pending, isEmpty);
      expect(chat.messages, isEmpty);
      expect(settings.conversationId, isNot(oldId));
      chat.dispose();
    });

    test('a plain new conversation leaves the server alone', () async {
      final (chat, server, _, _, _) = await make();
      server.pending = [draftJson()];
      await chat.send('سجل');
      await settle();
      final before = server.requests.length;

      await chat.newConversation();

      expect(server.requests.length, before);
      chat.dispose();
    });

    test('a pending draft does not stop a normal question from being sent', () async {
      final (chat, server, _, _, _) = await make();
      server.pending = [draftJson()];
      await chat.send('سجل');
      await settle();

      await chat.send('شو رصيد الصندوق؟');
      await settle();

      expect(server.lastAsk!['question'], 'شو رصيد الصندوق؟');
      chat.dispose();
    });
  });
}
