import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rima_mobile/core/api_client.dart';
import 'package:rima_mobile/models/models.dart';

import 'helpers.dart';

void main() {
  group('normalizeBaseUrl', () {
    test('adds http:// and strips trailing slashes', () {
      expect(normalizeBaseUrl('192.168.1.5:8000'), 'http://192.168.1.5:8000');
      expect(normalizeBaseUrl('  https://rima.example.com/// '), 'https://rima.example.com');
      expect(normalizeBaseUrl(''), '');
    });
  });

  test('accounts() hits GET /accounts/ and parses code/parent', () async {
    late http.Request seen;
    final api = fakeApi((req) async {
      seen = req;
      return jsonResponse([
        {'id': 1, 'code': '001', 'name': 'الموجودات', 'closeIn': 0, 'parentAccount': null},
        {'id': 2, 'code': null, 'name': 'صندوق', 'closeIn': 0, 'parentAccount': 1},
      ]);
    });

    final list = await api.accounts();

    expect(seen.method, 'GET');
    expect(seen.url.toString(), 'http://test/accounts/');
    expect(list.length, 2);
    expect(list[0].name, 'الموجودات');
    expect(list[0].code, '001');
    expect(list[1].code, isNull);
    expect(list[1].parentAccount, 1);
  });

  test('summary() understands the "no data yet" Message shape', () async {
    final api = fakeApi((_) async => jsonResponse({'Message': 'لا يوجد بيانات لتحليلها'}));
    final s = await api.summary();
    expect(s.message, 'لا يوجد بيانات لتحليلها');
    expect(s.income, isNull);
  });

  test('summary() parses the numbers', () async {
    final api = fakeApi((_) async => jsonResponse({'Total Income': 1500, 'Total Expense': 200.5, 'Balance': 1299.5}));
    final s = await api.summary();
    expect(s.income, 1500.0);
    expect(s.expense, 200.5);
    expect(s.balance, 1299.5);
  });

  test('createTransaction sends items with a description (never null) and a UTC date', () async {
    late http.Request seen;
    final api = fakeApi((req) async {
      seen = req;
      return jsonResponse({'id': 9}, status: 201);
    });

    await api.createTransaction(TransactionInput(
      date: DateTime(2026, 9, 19),
      notes: 'بيع نقدي',
      lines: [
        TxLine(accId: 7, debit: 100),
        TxLine(accId: 18, credit: 100, description: 'مبيعات'),
      ],
    ));

    expect(seen.method, 'POST');
    expect(seen.url.path, '/transactions/');
    expect(seen.headers['Content-Type'], contains('charset=utf-8'));
    final body = jsonDecode(utf8.decode(seen.bodyBytes)) as Map<String, dynamic>;
    expect(body['date'], '2026-09-19T00:00:00.000Z');
    expect(body['notes'], 'بيع نقدي');
    final items = body['items'] as List;
    expect(items[0], {'acc_id': 7, 'debit': 100.0, 'credit': 0.0, 'description': ''});
    expect(items[1]['description'], 'مبيعات');
  });

  test('updateAccount puts the id inside the body like the web UI does', () async {
    late http.Request seen;
    final api = fakeApi((req) async {
      seen = req;
      return jsonResponse({'id': 5, 'code': '004', 'name': 'زبائن', 'closeIn': 0, 'parentAccount': 3}, status: 202);
    });

    await api.updateAccount(5, const AccountInput(code: '004', name: 'زبائن', closeIn: 0, parentAccount: 3));

    expect(seen.method, 'PUT');
    expect(seen.url.path, '/accounts/');
    final body = jsonDecode(utf8.decode(seen.bodyBytes)) as Map<String, dynamic>;
    expect(body, {'id': 5, 'code': '004', 'name': 'زبائن', 'closeIn': 0, 'parentAccount': 3});
  });

  test('deleteAccount accepts 204 with an empty body', () async {
    final api = fakeApi((req) async {
      expect(req.method, 'DELETE');
      expect(req.url.path, '/accounts/12');
      return http.Response('', 204);
    });
    await api.deleteAccount(12);
  });

  test('balance() repeats acc_ids in the query string', () async {
    late http.Request seen;
    final api = fakeApi((req) async {
      seen = req;
      return jsonResponse({
        'debit_sum': 1500,
        'credit_sum': 200,
        'net': 1300,
        'breakdown': [
          {'acc_id': 2, 'code': '002', 'acc_name': 'Cash', 'debit_sum': 1000, 'credit_sum': 200, 'net': 800},
          {'acc_id': 999, 'error': 'Account not found'},
        ],
      });
    });

    final r = await api.balance([2, 3], asOfDate: '2026-02-28');

    expect(seen.url.queryParametersAll['acc_ids'], ['2', '3']);
    expect(seen.url.queryParameters['as_of_date'], '2026-02-28');
    expect(seen.url.queryParameters.containsKey('date_from'), isFalse);
    expect(r.net, 1300);
    expect(r.breakdown[0].code, '002');
    expect(r.breakdown[1].error, 'Account not found');
  });

  test('statement() sends only the dates that were given', () async {
    late http.Request seen;
    final api = fakeApi((req) async {
      seen = req;
      return jsonResponse([
        {'transaction_id': 3, 'date': '2026-03-01', 'debit': 0, 'credit': 200, 'description': 'cash out', 'acc_id': 2, 'acc_name': 'Cash'},
      ]);
    });

    final rows = await api.statement(1, dateFrom: '2026-02-01');

    expect(seen.url.path, '/reports/statement/1');
    expect(seen.url.queryParameters, {'date_from': '2026-02-01'});
    expect(rows.single.credit, 200);
  });

  test('askRima posts conversation_id + question and returns the answer', () async {
    late http.Request seen;
    final api = fakeApi((req) async {
      seen = req;
      return jsonResponse({'answer': 'رصيد الصندوق 800 مدين.'});
    });

    final answer = await api.askRima('conv-1', 'شو رصيد الصندوق؟');

    expect(answer, 'رصيد الصندوق 800 مدين.');
    expect(seen.url.path, '/reports/ask_ai');
    expect(jsonDecode(utf8.decode(seen.bodyBytes)), {'conversation_id': 'conv-1', 'question': 'شو رصيد الصندوق؟'});
  });

  group('errors', () {
    test('a 409 surfaces the server\'s detail message and status', () async {
      final api = fakeApi((_) async => jsonResponse({'detail': 'Cannot delete a master account that has child accounts'}, status: 409));
      expect(
        () => api.deleteAccount(1),
        throwsA(isA<ApiException>()
            .having((e) => e.message, 'message', contains('child accounts'))
            .having((e) => e.status, 'status', 409)
            .having((e) => e.isConnection, 'isConnection', false)),
      );
    });

    test('a 422 validation list is joined into one message', () async {
      final api = fakeApi((_) async => jsonResponse({
            'detail': [
              {'msg': 'Field required', 'loc': ['body', 'name']},
              {'msg': 'Input should be a valid integer'},
            ],
          }, status: 422));
      expect(
        () => api.accounts(),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', 'Field required، Input should be a valid integer')),
      );
    });

    test('a transport failure is reported as a connection problem', () async {
      final api = fakeApi((_) async => throw http.ClientException('boom'));
      expect(() => api.accounts(), throwsA(isA<ApiException>().having((e) => e.isConnection, 'isConnection', true)));
    });

    test('an HTML error page from a proxy is not blindly JSON-decoded', () async {
      final api = fakeApi((_) async => http.Response('<html>502 Bad Gateway</html>', 200));
      expect(() => api.accounts(), throwsA(isA<ApiException>().having((e) => e.message, 'message', contains('غير متوقعة'))));
    });

    test('an empty server URL fails fast with a helpful connection error', () async {
      final api = fakeApi((_) async => jsonResponse([]), base: '  ');
      expect(() => api.accounts(), throwsA(isA<ApiException>().having((e) => e.isConnection, 'isConnection', true)));
    });
  });

  test('changing the base URL takes effect on the next call', () async {
    var base = 'http://one';
    final hosts = <String>[];
    final api = ApiClient(
      baseUrl: () => base,
      client: MockClient((req) async {
        hosts.add(req.url.host);
        return jsonResponse([]);
      }),
    );
    await api.accounts();
    base = 'two:9000';
    await api.accounts();
    expect(hosts, ['one', 'two']);
  });
}
