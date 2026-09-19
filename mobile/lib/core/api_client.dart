import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/models.dart';

class ApiException implements Exception {
  ApiException(this.message, {this.status, this.isConnection = false});

  final String message;
  final int? status;

  /// True for "couldn't reach the server at all" (wrong URL, offline, timeout)
  /// as opposed to the server answering with an error.
  final bool isConnection;

  @override
  String toString() => message;
}

/// "192.168.1.5:8000" -> "http://192.168.1.5:8000"; strips trailing slashes.
String normalizeBaseUrl(String raw) {
  var s = raw.trim();
  if (s.isEmpty) return '';
  if (!s.contains('://')) s = 'http://$s';
  while (s.endsWith('/')) {
    s = s.substring(0, s.length - 1);
  }
  return s;
}

class ApiClient {
  ApiClient({required this.baseUrl, http.Client? client}) : _http = client ?? http.Client();

  /// Read on every call so changing the server URL in Settings takes effect
  /// immediately, without rebuilding anything.
  final String Function() baseUrl;
  final http.Client _http;

  Uri _uri(String path, [Map<String, dynamic>? query]) {
    final base = normalizeBaseUrl(baseUrl());
    if (base.isEmpty) {
      throw ApiException('لم يتم ضبط عنوان الخادم بعد', isConnection: true);
    }
    final uri = Uri.parse('$base$path');
    if (query == null || query.isEmpty) return uri;
    return uri.replace(queryParameters: query);
  }

  Future<dynamic> _send(
    String method,
    String path, {
    Map<String, dynamic>? query,
    Object? body,
    Duration timeout = const Duration(seconds: 30),
  }) async {
    final uri = _uri(path, query);
    final headers = {
      'Content-Type': 'application/json; charset=utf-8',
      'Accept': 'application/json',
    };

    http.Response res;
    try {
      final encoded = body == null ? null : jsonEncode(body);
      switch (method) {
        case 'POST':
          res = await _http.post(uri, headers: headers, body: encoded).timeout(timeout);
        case 'PUT':
          res = await _http.put(uri, headers: headers, body: encoded).timeout(timeout);
        case 'DELETE':
          res = await _http.delete(uri, headers: headers).timeout(timeout);
        default:
          res = await _http.get(uri, headers: headers).timeout(timeout);
      }
    } on TimeoutException {
      throw ApiException('انتهت مهلة الاتصال بالخادم', isConnection: true);
    } catch (_) {
      throw ApiException('تعذر الاتصال بالخادم. تأكد من العنوان وأن الخادم شغّال', isConnection: true);
    }

    if (res.statusCode >= 200 && res.statusCode < 300) {
      if (res.statusCode == 204 || res.bodyBytes.isEmpty) return null;
      try {
        return jsonDecode(utf8.decode(res.bodyBytes));
      } on FormatException {
        throw ApiException('استجابة غير متوقعة من الخادم', status: res.statusCode);
      }
    }
    throw ApiException(_errorMessage(res), status: res.statusCode);
  }

  String _errorMessage(http.Response res) {
    try {
      final decoded = jsonDecode(utf8.decode(res.bodyBytes));
      if (decoded is Map && decoded['detail'] != null) {
        final detail = decoded['detail'];
        if (detail is String) return detail;
        if (detail is List) {
          final msgs = detail.map((e) => e is Map ? e['msg'] : e).whereType<Object>();
          if (msgs.isNotEmpty) return msgs.join('، ');
        }
      }
    } catch (_) {
      // fall through to the generic message
    }
    return 'خطأ من الخادم (${res.statusCode})';
  }

  // ---- health -----------------------------------------------------------

  Future<Map<String, dynamic>> health() async =>
      (await _send('GET', '/health', timeout: const Duration(seconds: 10))) as Map<String, dynamic>;

  // ---- accounts ---------------------------------------------------------

  Future<List<Account>> accounts() async {
    final data = await _send('GET', '/accounts/') as List;
    return data.map((e) => Account.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Account> createAccount(AccountInput input) async => Account.fromJson(
      await _send('POST', '/accounts/', body: input.toJson()) as Map<String, dynamic>);

  Future<Account> updateAccount(int id, AccountInput input) async => Account.fromJson(
      await _send('PUT', '/accounts/', body: {'id': id, ...input.toJson()}) as Map<String, dynamic>);

  Future<void> deleteAccount(int id) => _send('DELETE', '/accounts/$id');

  // ---- transactions -----------------------------------------------------

  Future<List<Transaction>> transactions() async {
    final data = await _send('GET', '/transactions/') as List;
    return data.map((e) => Transaction.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Transaction> transaction(int id) async =>
      Transaction.fromJson(await _send('GET', '/transactions/$id') as Map<String, dynamic>);

  Future<void> createTransaction(TransactionInput input) =>
      _send('POST', '/transactions/', body: input.toJson());

  Future<void> updateTransaction(int id, TransactionInput input) =>
      _send('PUT', '/transactions/', body: {'id': id, ...input.toJson()});

  Future<void> deleteTransaction(int id) => _send('DELETE', '/transactions/$id');

  // ---- reports ----------------------------------------------------------

  Future<Summary> summary() async =>
      Summary.fromJson(await _send('GET', '/reports/summery') as Map<String, dynamic>);

  Future<List<ChartAccount>> chartOfAccounts() async {
    final data = await _send('GET', '/reports/chart-of-accounts') as List;
    return data.map((e) => ChartAccount.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<StatementRow>> statement(int accId, {String? dateFrom, String? dateTo}) async {
    final data = await _send('GET', '/reports/statement/$accId', query: {
      if (dateFrom != null) 'date_from': dateFrom,
      if (dateTo != null) 'date_to': dateTo,
    }) as List;
    return data.map((e) => StatementRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<BalanceResult> balance(
    List<int> accIds, {
    String? asOfDate,
    String? dateFrom,
    String? dateTo,
  }) async {
    final data = await _send('GET', '/reports/balance', query: {
      'acc_ids': accIds.map((e) => '$e').toList(), // repeated ?acc_ids=1&acc_ids=2
      if (asOfDate != null) 'as_of_date': asOfDate,
      if (dateFrom != null) 'date_from': dateFrom,
      if (dateTo != null) 'date_to': dateTo,
    });
    return BalanceResult.fromJson(data as Map<String, dynamic>);
  }

  // ---- Rima -------------------------------------------------------------

  Future<String> askRima(String conversationId, String question) async {
    final data = await _send(
      'POST',
      '/reports/ask_ai',
      body: {'conversation_id': conversationId, 'question': question},
      timeout: const Duration(seconds: 120), // the agent may make several Gemini round trips
    ) as Map<String, dynamic>;
    return (data['answer'] as String?) ?? '';
  }
}
