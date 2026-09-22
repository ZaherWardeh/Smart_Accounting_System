import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:rima_mobile/core/api_client.dart';
import 'package:rima_mobile/models/models.dart';

import 'helpers.dart';

Map<String, dynamic> txDraft({
  String status = 'collecting',
  String next = 'credit_account',
  bool ready = false,
  Object? amount,
}) =>
    {
      'kind': 'transaction',
      'status': status,
      'next_step': next,
      'ready_to_confirm': ready,
      'draft': {
        'debit_account': {'id': 7, 'code': '0010301', 'name': 'صندوق'},
        'credit_account': ready ? {'id': 16, 'code': '00301', 'name': 'المبيعات'} : null,
        'amount': amount,
        'date': '2026-09-21',
      },
    };

void main() {
  group('PendingDraft', () {
    test('parses the server shape', () {
      final d = PendingDraft.fromJson(txDraft());
      expect(d.kind, 'transaction');
      expect(d.isTransaction, isTrue);
      expect(d.nextStep, 'credit_account');
      expect(d.nextStepLabelAr, 'حساب الدائن');
      expect(d.readyToConfirm, isFalse);
    });

    test('summaryAr describes a transaction with its accounts and amount', () {
      final d = PendingDraft.fromJson(txDraft(status: 'awaiting_confirmation', next: 'confirmation', ready: true, amount: 750.5));
      expect(d.summaryAr, 'قيد: مدين 0010301 - صندوق / دائن 00301 - المبيعات بمبلغ 750.5');
    });

    test('summaryAr shows a dash for what is still missing', () {
      expect(PendingDraft.fromJson(txDraft()).summaryAr, 'قيد: مدين 0010301 - صندوق / دائن —');
    });

    test('summaryAr for a new account', () {
      final d = PendingDraft.fromJson({
        'kind': 'account',
        'status': 'collecting',
        'next_step': 'close_in',
        'ready_to_confirm': false,
        'draft': {
          'name': 'محروقات',
          'parent_account': {'id': 6, 'code': '004', 'name': 'المصاريف'},
        },
      });
      expect(d.summaryAr, 'حساب جديد: محروقات تحت 004 - المصاريف');
      expect(d.nextStepLabelAr, 'نوع الإغلاق');
    });

    test('tolerates missing fields', () {
      final d = PendingDraft.fromJson(const {});
      expect(d.kind, 'transaction');
      expect(d.draft, isEmpty);
    });
  });

  group('RimaReply / Transaction', () {
    test('an old server reply without pending_drafts still parses', () {
      final r = RimaReply.fromJson({'answer': 'مرحبا'});
      expect(r.answer, 'مرحبا');
      expect(r.pendingDrafts, isEmpty);
    });

    test('pending drafts are parsed from the reply', () {
      final r = RimaReply.fromJson({
        'answer': 'x',
        'pending_drafts': [txDraft()],
      });
      expect(r.pendingDrafts.single.nextStep, 'credit_account');
    });

    test('Transaction.hasDocument follows has_document', () {
      Transaction t(Map<String, dynamic> extra) => Transaction.fromJson({'id': 1, 'details': [], ...extra});
      expect(t({'has_document': true}).hasDocument, isTrue);
      expect(t({'has_document': false}).hasDocument, isFalse);
      expect(t({}).hasDocument, isFalse);
    });
  });

  group('ApiClient: Rima with attachments and drafts', () {
    test('askRimaFull sends the image as base64 with its file name and parses pending drafts', () async {
      late Map<String, dynamic> sent;
      final api = fakeApi((req) async {
        sent = jsonDecode(utf8.decode(req.bodyBytes)) as Map<String, dynamic>;
        return jsonResponse({'answer': 'قرأت الفاتورة', 'pending_drafts': [txDraft()]});
      });

      final reply = await api.askRimaFull(
        'c1',
        '',
        attachment: RimaAttachment(bytes: Uint8List.fromList([1, 2, 3, 255]), name: 'bill.jpg'),
      );

      expect(sent['conversation_id'], 'c1');
      expect(sent['question'], '');
      expect(sent['attachment']['filename'], 'bill.jpg');
      expect(base64Decode(sent['attachment']['data_base64'] as String), [1, 2, 3, 255]);
      expect(reply.answer, 'قرأت الفاتورة');
      expect(reply.pendingDrafts, hasLength(1));
    });

    test('without an attachment the request body has no attachment key (old servers stay happy)', () async {
      late Map<String, dynamic> sent;
      final api = fakeApi((req) async {
        sent = jsonDecode(utf8.decode(req.bodyBytes)) as Map<String, dynamic>;
        return jsonResponse({'answer': 'ok'});
      });
      await api.askRimaFull('c1', 'مرحبا');
      expect(sent.containsKey('attachment'), isFalse);
    });

    test('askRima still returns just the text', () async {
      final api = fakeApi((_) async => jsonResponse({'answer': 'جواب'}));
      expect(await api.askRima('c', 'q'), 'جواب');
    });

    test('pendingDrafts lists the open operations of a conversation', () async {
      late http.Request seen;
      final api = fakeApi((req) async {
        seen = req;
        return jsonResponse([txDraft()]);
      });
      final list = await api.pendingDrafts('c1');
      expect(seen.url.path, '/drafts/c1');
      expect(list.single.kind, 'transaction');
    });

    test('confirmDraft posts to the confirm route and words the result', () async {
      late http.Request seen;
      final api = fakeApi((req) async {
        seen = req;
        return jsonResponse({'ok': true, 'transaction_id': 12, 'pending_drafts': []});
      });
      final done = await api.confirmDraft('c1', 'transaction');
      expect(seen.method, 'POST');
      expect(seen.url.path, '/drafts/c1/transaction/confirm');
      expect(done.messageAr, 'تم حفظ القيد رقم 12.');
      expect(done.pendingDrafts, isEmpty);
    });

    test('confirming an account words the result with its code and name', () async {
      final api = fakeApi((_) async => jsonResponse({
            'ok': true,
            'account': {'id': 30, 'code': '00203', 'name': 'محروقات'},
            'pending_drafts': [txDraft(status: 'awaiting_confirmation', next: 'confirmation', ready: true, amount: 5)],
          }));
      final done = await api.confirmDraft('c1', 'account');
      expect(done.messageAr, 'تم إنشاء الحساب 00203 - محروقات.');
      expect(done.pendingDrafts.single.readyToConfirm, isTrue);
    });

    test('an incomplete draft (409 with a dict detail) becomes a readable message', () async {
      final api = fakeApi((_) async => jsonResponse({
            'detail': {'ok': false, 'error': 'incomplete', 'next_step': 'amount'},
          }, status: 409));
      expect(
        () => api.confirmDraft('c1', 'transaction'),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', contains('غير مكتملة')).having((e) => e.status, 'status', 409)),
      );
    });

    test('cancelDraft returns what is still pending', () async {
      late http.Request seen;
      final api = fakeApi((req) async {
        seen = req;
        return jsonResponse({'ok': true, 'cancelled': true, 'pending_drafts': []});
      });
      expect(await api.cancelDraft('c1', 'account'), isEmpty);
      expect(seen.url.path, '/drafts/c1/account/cancel');
    });

    test('transactionDocument returns the image bytes', () async {
      final api = fakeApi((req) async {
        expect(req.url.path, '/transactions/9/document');
        return http.Response.bytes(tinyPng, 200, headers: {'content-type': 'image/png'});
      });
      expect(await api.transactionDocument(9), tinyPng);
    });

    test('a 404 document is reported as "no document"', () async {
      final api = fakeApi((_) async => jsonResponse({'detail': 'This transaction has no document'}, status: 404));
      expect(() => api.transactionDocument(9), throwsA(isA<ApiException>().having((e) => e.message, 'message', contains('مستند'))));
    });

    test('an unreachable server while fetching a document is a connection error', () async {
      final api = fakeApi((_) async => throw http.ClientException('no route'));
      expect(() => api.transactionDocument(9), throwsA(isA<ApiException>().having((e) => e.isConnection, 'isConnection', isTrue)));
    });
  });
}
