import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:rima_mobile/chat/chat_controller.dart';
import 'package:rima_mobile/core/settings.dart';

import 'helpers.dart';

class Harness {
  Harness(this.chat, this.voice, this.settings, this.asked);

  final ChatController chat;
  final FakeVoiceService voice;
  final AppSettings settings;

  /// (conversation_id, question) for every /reports/ask_ai request.
  final List<(String, String)> asked;
}

Future<Harness> harness({
  Map<String, Object> prefs = const {},
  String answer = 'رصيد الصندوق 800 مدين.',
  Future<http.Response> Function(http.Request)? handler,
}) async {
  final settings = await makeSettings(prefs);
  final voice = FakeVoiceService();
  final asked = <(String, String)>[];
  final api = fakeApi(handler ??
      (req) async {
        final body = jsonDecode(utf8.decode(req.bodyBytes)) as Map<String, dynamic>;
        asked.add((body['conversation_id'] as String, body['question'] as String));
        return jsonResponse({'answer': answer});
      });
  return Harness(ChatController(api: api, voice: voice, settings: settings), voice, settings, asked);
}

/// Lets fire-and-forget futures (auto-speak, the send after a voice result) run.
Future<void> settle() => Future<void>.delayed(Duration.zero);

void main() {
  group('typed messages', () {
    test('sends the question with this conversation\'s id and shows Rima\'s answer', () async {
      final h = await harness();

      await h.chat.send('  شو رصيد الصندوق؟  ');

      expect(h.asked.single.$2, 'شو رصيد الصندوق؟'); // trimmed
      expect(h.asked.single.$1, h.settings.conversationId);
      expect(h.chat.messages.map((m) => (m.text, m.fromUser)), [
        ('شو رصيد الصندوق؟', true),
        ('رصيد الصندوق 800 مدين.', false),
      ]);
      expect(h.chat.sending, isFalse);
    });

    test('blank input sends nothing', () async {
      final h = await harness();
      await h.chat.send('   ');
      expect(h.asked, isEmpty);
      expect(h.chat.messages, isEmpty);
    });

    test('a second send while one is in flight is ignored', () async {
      final gate = Completer<http.Response>();
      final h = await harness(handler: (_) => gate.future);

      final first = h.chat.send('أول');
      await settle();
      await h.chat.send('ثاني');
      gate.complete(jsonResponse({'answer': 'x'}));
      await first;

      expect(h.chat.messages.where((m) => m.fromUser).map((m) => m.text), ['أول']);
    });

    test('a server failure shows up as an error bubble and Rima says nothing', () async {
      final h = await harness(handler: (_) async => jsonResponse({'detail': 'boom'}, status: 400));

      await h.chat.send('مرحبا');
      await settle();

      expect(h.chat.messages.last.isError, isTrue);
      expect(h.chat.messages.last.text, 'boom');
      expect(h.voice.spoken, isEmpty);
      expect(h.chat.sending, isFalse);
    });
  });

  group('Rima speaking', () {
    test('reads the reply aloud by default', () async {
      final h = await harness();
      await h.chat.send('شو رصيد الصندوق؟');
      await settle();
      expect(h.voice.spoken, ['رصيد الصندوق 800 مدين.']);
    });

    test('stays quiet when auto-speak is off', () async {
      final h = await harness(prefs: {'autoSpeak': false});
      await h.chat.send('مرحبا');
      await settle();
      expect(h.voice.spoken, isEmpty);
    });

    test('the replay button can still read a message when auto-speak is off', () async {
      final h = await harness(prefs: {'autoSpeak': false});
      await h.chat.send('مرحبا');
      await h.chat.speak('رصيد الصندوق 800 مدين.');
      expect(h.voice.spoken, ['رصيد الصندوق 800 مدين.']);
    });

    test('speaking flag is on while speaking and off after', () async {
      final h = await harness();
      h.voice.speakGate = Completer<void>();

      await h.chat.send('مرحبا');
      await settle();
      expect(h.chat.speaking, isTrue);

      h.voice.speakGate!.complete();
      await settle();
      await settle();
      expect(h.chat.speaking, isFalse);
    });

    test('sending a new message cuts off whatever Rima is still saying', () async {
      final h = await harness();
      final before = h.voice.stopSpeakingCalls;
      await h.chat.send('سؤال');
      expect(h.voice.stopSpeakingCalls, greaterThan(before));
    });
  });

  group('voice commands', () {
    test('mic -> live transcript -> final result is sent automatically -> Rima answers out loud', () async {
      final h = await harness();

      await h.chat.toggleListening();
      expect(h.chat.listening, isTrue);
      expect(h.voice.startedLanguage, 'ar'); // default speech language

      h.voice.hear('شو رصيد');
      expect(h.chat.partial, 'شو رصيد');
      expect(h.asked, isEmpty); // not sent until the recogniser is done

      h.voice.hear('شو رصيد الصندوق', isFinal: true);
      await settle();
      await settle();

      expect(h.chat.listening, isFalse);
      expect(h.chat.partial, '');
      expect(h.asked.single.$2, 'شو رصيد الصندوق');
      expect(h.chat.messages.first.text, 'شو رصيد الصندوق');
      expect(h.chat.messages.first.fromUser, isTrue);
      expect(h.voice.spoken, ['رصيد الصندوق 800 مدين.']);
    });

    test('a final result followed by the engine\'s "done" status sends exactly once', () async {
      final h = await harness();
      await h.chat.toggleListening();

      h.voice.hear('مرحبا', isFinal: true);
      h.voice.finish();
      await settle();
      await settle();

      expect(h.asked.length, 1);
    });

    test('uses the language chosen in settings', () async {
      final h = await harness(prefs: {'speechLang': 'en'});
      await h.chat.toggleListening();
      expect(h.voice.startedLanguage, 'en');
    });

    test('tapping the mic again while listening stops and sends what was heard so far', () async {
      final h = await harness();
      await h.chat.toggleListening();
      h.voice.hear('كشف حساب الصندوق');

      await h.chat.toggleListening(); // stop
      await settle();
      await settle();

      expect(h.chat.listening, isFalse);
      expect(h.asked.single.$2, 'كشف حساب الصندوق');
    });

    test('the engine ending with nothing heard gives a hint instead of sending', () async {
      final h = await harness();
      await h.chat.toggleListening();

      h.voice.finish();
      await settle();

      expect(h.chat.listening, isFalse);
      expect(h.chat.notice, contains('ما سمعت'));
      expect(h.asked, isEmpty);
    });

    test('the engine ending after a partial-only transcript still sends that text', () async {
      final h = await harness();
      await h.chat.toggleListening();
      h.voice.hear('مرحبا ريما');

      h.voice.finish();
      await settle();
      await settle();

      expect(h.asked.single.$2, 'مرحبا ريما');
    });

    test('a no-match engine error becomes a friendly hint', () async {
      final h = await harness();
      await h.chat.toggleListening();

      h.voice.fail('error_no_match');

      expect(h.chat.listening, isFalse);
      expect(h.chat.notice, contains('ما سمعت'));
      expect(h.asked, isEmpty);
    });

    test('unavailable speech recognition reports it and never starts listening', () async {
      final h = await harness();
      h.voice.speechAvailable = false;

      await h.chat.toggleListening();

      expect(h.chat.listening, isFalse);
      expect(h.chat.notice, contains('غير متاح'));
      expect(h.voice.startListeningCalls, 0);
    });

    test('starting to listen first silences Rima so she does not hear herself', () async {
      final h = await harness();
      final before = h.voice.stopSpeakingCalls;
      await h.chat.toggleListening();
      expect(h.voice.stopSpeakingCalls, greaterThan(before));
    });
  });

  test('newConversation clears the chat and rotates the server-side conversation id', () async {
    final h = await harness();
    final oldId = h.settings.conversationId;
    await h.chat.send('مرحبا');

    await h.chat.newConversation();

    expect(h.chat.messages, isEmpty);
    expect(h.settings.conversationId, isNot(oldId));

    await h.chat.send('سؤال جديد');
    expect(h.asked.last.$1, h.settings.conversationId);
    expect(h.asked.last.$1, isNot(oldId));
  });

  test('the conversation id survives across ChatController instances (same settings)', () async {
    final h = await harness();
    final id1 = h.settings.conversationId;
    final id2 = h.settings.conversationId;
    expect(id1, id2);
  });
}
