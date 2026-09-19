import 'dart:async';

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:rima_mobile/app.dart';

import 'helpers.dart';

const _accounts = [
  {'id': 1, 'code': '001', 'name': 'الموجودات', 'closeIn': 0, 'parentAccount': null},
  {'id': 4, 'code': '00103', 'name': 'موجودات جاهزة', 'closeIn': 0, 'parentAccount': 1},
  {'id': 7, 'code': '0010301', 'name': 'صندوق', 'closeIn': 0, 'parentAccount': 4},
  {'id': 14, 'code': '003', 'name': 'الإيرادات', 'closeIn': 1, 'parentAccount': null},
  {'id': 16, 'code': '00301', 'name': 'المبيعات', 'closeIn': 2, 'parentAccount': 14},
];

const _chart = [
  {'id': 1, 'code': '001', 'name': 'الموجودات', 'closeIn': 'Balance Sheet', 'parentAccount': null, 'account_type': 'master'},
  {'id': 4, 'code': '00103', 'name': 'موجودات جاهزة', 'closeIn': 'Balance Sheet', 'parentAccount': 1, 'account_type': 'master'},
  {'id': 7, 'code': '0010301', 'name': 'صندوق', 'closeIn': 'Balance Sheet', 'parentAccount': 4, 'account_type': 'book'},
  {'id': 14, 'code': '003', 'name': 'الإيرادات', 'closeIn': 'P&L', 'parentAccount': null, 'account_type': 'master'},
  {'id': 16, 'code': '00301', 'name': 'المبيعات', 'closeIn': 'Trading', 'parentAccount': 14, 'account_type': 'book'},
];

class FakeServer {
  final List<http.Request> requests = [];

  Future<http.Response> handle(http.Request req) async {
    requests.add(req);
    switch ('${req.method} ${req.url.path}') {
      case 'GET /reports/summery':
        return jsonResponse({'Total Income': 1500, 'Total Expense': 200, 'Balance': 1300});
      case 'GET /accounts/':
        return jsonResponse(_accounts);
      case 'GET /reports/chart-of-accounts':
        return jsonResponse(_chart);
      case 'GET /transactions/':
        return jsonResponse([
          {
            'id': 3,
            'date': '2026-03-01T00:00:00',
            'notes': 'بيع نقدي',
            'details': [
              {'id': 1, 'debit': 200, 'credit': 0, 'acc_id': 7, 'acc_name': 'صندوق', 'description': ''},
              {'id': 2, 'debit': 0, 'credit': 200, 'acc_id': 16, 'acc_name': 'المبيعات', 'description': ''},
            ],
          },
        ]);
      case 'POST /transactions/':
        return jsonResponse({'id': 4}, status: 201);
      case 'DELETE /accounts/7':
        return http.Response('', 204);
      case 'POST /reports/ask_ai':
        return jsonResponse({'answer': 'رصيد الصندوق 800 مدين.'});
      default:
        return jsonResponse({'detail': 'unexpected ${req.method} ${req.url.path}'}, status: 500);
    }
  }
}

Future<(FakeServer, FakeVoiceService)> pumpApp(WidgetTester tester) async {
  tester.view.physicalSize = const Size(800, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);

  final server = FakeServer();
  final voice = FakeVoiceService();
  final settings = await makeSettings({'baseUrl': 'http://test'});
  await tester.pumpWidget(RimaApp(settings: settings, api: fakeApi(server.handle), voice: voice));
  await tester.pumpAndSettle();
  return (server, voice);
}

Finder navItem(String label) =>
    find.descendant(of: find.byType(NavigationBar), matching: find.text(label));

void main() {
  testWidgets('boots into an RTL Arabic UI with the dashboard summary', (tester) async {
    await pumpApp(tester);

    expect(Directionality.of(tester.element(find.byType(NavigationBar))), TextDirection.rtl);
    expect(find.text('ملخص مالي'), findsOneWidget);
    expect(find.text('1,500'), findsOneWidget);
    expect(find.text('200'), findsOneWidget);
    expect(find.text('1,300'), findsOneWidget);
  });

  testWidgets('accounts tab renders the tree with codes, master/book tags, in code order', (tester) async {
    await pumpApp(tester);

    await tester.tap(navItem('الحسابات'));
    await tester.pumpAndSettle();

    expect(find.text('دليل الحسابات'), findsOneWidget);
    for (final code in ['001', '00103', '0010301', '003', '00301']) {
      expect(find.text(code), findsOneWidget, reason: 'code $code');
    }
    expect(find.text('رئيسي'), findsNWidgets(3)); // الموجودات, موجودات جاهزة, الإيرادات
    expect(find.text('فرعي'), findsNWidgets(2)); // صندوق, المبيعات

    // depth-first: Assets subtree is fully listed before the Revenue root
    double y(String name) => tester.getTopLeft(find.text(name)).dy;
    expect(y('الموجودات'), lessThan(y('موجودات جاهزة')));
    expect(y('موجودات جاهزة'), lessThan(y('صندوق')));
    expect(y('صندوق'), lessThan(y('الإيرادات')));
    expect(y('الإيرادات'), lessThan(y('المبيعات')));
  });

  testWidgets('transactions tab lists entries with totals', (tester) async {
    await pumpApp(tester);

    await tester.tap(navItem('القيود'));
    await tester.pumpAndSettle();

    expect(find.text('بيع نقدي'), findsOneWidget);
    expect(find.textContaining('2026-03-01'), findsOneWidget);
    expect(find.textContaining('مدين 200'), findsOneWidget);
  });

  testWidgets('new transaction: save stays disabled until debits == credits, then posts the entry', (tester) async {
    final (server, _) = await pumpApp(tester);

    await tester.tap(navItem('القيود'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('قيد جديد'));
    await tester.pumpAndSettle();

    bool saveEnabled() => tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'حفظ')).onPressed != null;
    expect(saveEnabled(), isFalse);
    expect(find.text('✗ غير متوازن'), findsOneWidget);

    // line 1: صندوق debit 100
    await tester.tap(find.byType(DropdownButtonFormField<int>).at(0));
    await tester.pumpAndSettle();
    await tester.tap(find.text('0010301 — صندوق').last); // only postable (book) accounts are offered
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'مدين').at(0), '100');
    await tester.pump();
    expect(saveEnabled(), isFalse); // one-sided

    // line 2: المبيعات credit 100
    await tester.tap(find.byType(DropdownButtonFormField<int>).at(1));
    await tester.pumpAndSettle();
    await tester.tap(find.text('00301 — المبيعات').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'دائن').at(1), '100');
    await tester.pump();

    expect(find.text('✓ متوازن'), findsOneWidget);
    expect(saveEnabled(), isTrue);

    // master accounts must not be selectable for posting
    await tester.tap(find.byType(DropdownButtonFormField<int>).at(0));
    await tester.pumpAndSettle();
    expect(find.text('001 — الموجودات'), findsNothing);
    await tester.tap(find.text('0010301 — صندوق').last);
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'حفظ'));
    await tester.pumpAndSettle();

    final post = server.requests.singleWhere((r) => r.method == 'POST' && r.url.path == '/transactions/');
    final body = jsonDecode(utf8.decode(post.bodyBytes)) as Map<String, dynamic>;
    final items = (body['items'] as List).cast<Map<String, dynamic>>();
    expect(items.map((i) => (i['acc_id'], i['debit'], i['credit'])), [(7, 100.0, 0.0), (16, 0.0, 100.0)]);
    expect(items.every((i) => i['description'] is String), isTrue);
    expect(find.text('القيود المحاسبية'), findsOneWidget); // popped back to the list
  });

  testWidgets('reports tab loads the account pickers', (tester) async {
    await pumpApp(tester);

    await tester.tap(navItem('التقارير'));
    await tester.pumpAndSettle();

    expect(find.text('كشف حساب'), findsWidgets);
    expect(find.text('رصيد الحسابات'), findsOneWidget);
    expect(find.text('عرض الكشف'), findsOneWidget);
  });

  testWidgets('a server that is unreachable shows an error with a shortcut to the server setting', (tester) async {
    tester.view.physicalSize = const Size(800, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final settings = await makeSettings({'baseUrl': 'http://test'});
    await tester.pumpWidget(RimaApp(
      settings: settings,
      api: fakeApi((_) async => throw http.ClientException('no route to host')),
      voice: FakeVoiceService(),
    ));
    await tester.pumpAndSettle();

    expect(find.textContaining('تعذر الاتصال'), findsOneWidget);
    await tester.tap(find.text('إعادة المحاولة')); // retry path must not blow up either
    await tester.pumpAndSettle();
    expect(find.textContaining('تعذر الاتصال'), findsOneWidget);
    await tester.tap(find.text('إعدادات الخادم'));
    await tester.pumpAndSettle();
    expect(find.text('عنوان الخادم'), findsOneWidget);
  });

  testWidgets('every reload path works (regression: setState must not be handed a Future)', (tester) async {
    final (server, _) = await pumpApp(tester);
    int gets(String path) => server.requests.where((r) => r.method == 'GET' && r.url.path == path).length;

    // Home: pull-to-refresh (drive the indicator directly; the drag gesture itself is the framework's job)
    final before = gets('/reports/summery');
    final refresh = tester.state<RefreshIndicatorState>(find.byType(RefreshIndicator));
    unawaited(refresh.show());
    await tester.pumpAndSettle();
    expect(gets('/reports/summery'), before + 1);

    // Accounts: refresh button
    await tester.tap(navItem('الحسابات'));
    await tester.pumpAndSettle();
    final accBefore = gets('/accounts/');
    await tester.tap(find.byIcon(Icons.refresh));
    await tester.pumpAndSettle();
    expect(gets('/accounts/'), accBefore + 1);

    // Transactions: refresh button
    await tester.tap(navItem('القيود'));
    await tester.pumpAndSettle();
    final txBefore = gets('/transactions/');
    await tester.tap(find.byIcon(Icons.refresh));
    await tester.pumpAndSettle();
    expect(gets('/transactions/'), txBefore + 1);
    expect(tester.takeException(), isNull);
  });

  testWidgets('deleting an account asks first, calls DELETE, and reloads the tree', (tester) async {
    final (server, _) = await pumpApp(tester);
    await tester.tap(navItem('الحسابات'));
    await tester.pumpAndSettle();
    final loadsBefore = server.requests.where((r) => r.method == 'GET' && r.url.path == '/accounts/').length;

    // صندوق's row menu is the third PopupMenuButton (الموجودات, موجودات جاهزة, صندوق, ...)
    await tester.tap(find.byType(PopupMenuButton<String>).at(2));
    await tester.pumpAndSettle();
    await tester.tap(find.text('حذف').last);
    await tester.pumpAndSettle();
    expect(find.textContaining('متأكد من حذف الحساب'), findsOneWidget);
    expect(server.requests.where((r) => r.method == 'DELETE'), isEmpty); // nothing yet

    await tester.tap(find.widgetWithText(FilledButton, 'حذف'));
    await tester.pumpAndSettle();

    expect(server.requests.where((r) => r.method == 'DELETE').single.url.path, '/accounts/7');
    expect(server.requests.where((r) => r.method == 'GET' && r.url.path == '/accounts/').length, loadsBefore + 1);
  });

  testWidgets('chat tab keeps the conversation when you switch away and back', (tester) async {
    final (_, voice) = await pumpApp(tester);

    await tester.tap(navItem('ريما'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'شو رصيد الصندوق؟');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();
    expect(find.text('رصيد الصندوق 800 مدين.'), findsOneWidget);
    expect(voice.spoken.length, 1);

    await tester.tap(navItem('الرئيسية'));
    await tester.pumpAndSettle();
    await tester.tap(navItem('ريما'));
    await tester.pumpAndSettle();

    // same conversation still on screen - the tab wasn't rebuilt from scratch
    expect(find.text('شو رصيد الصندوق؟'), findsOneWidget);
    expect(find.text('رصيد الصندوق 800 مدين.'), findsOneWidget);
    expect(voice.spoken.length, 1); // and Rima didn't re-read it on return
  });
}
