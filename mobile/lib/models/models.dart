double _num(dynamic v) => v == null ? 0 : (v as num).toDouble();

DateTime? _date(dynamic v) => v is String ? DateTime.tryParse(v) : null;

class Account {
  const Account({
    required this.id,
    this.code,
    required this.name,
    required this.closeIn,
    this.parentAccount,
  });

  final int id;
  final String? code;
  final String name;
  final int closeIn;
  final int? parentAccount;

  factory Account.fromJson(Map<String, dynamic> j) => Account(
        id: (j['id'] as num).toInt(),
        code: j['code'] as String?,
        name: j['name'] as String,
        closeIn: (j['closeIn'] as num?)?.toInt() ?? 0,
        parentAccount: (j['parentAccount'] as num?)?.toInt(),
      );
}

class AccountInput {
  const AccountInput({this.code, required this.name, required this.closeIn, this.parentAccount});

  final String? code;
  final String name;
  final int closeIn;
  final int? parentAccount;

  Map<String, dynamic> toJson() => {
        'code': code,
        'name': name,
        'closeIn': closeIn,
        'parentAccount': parentAccount,
      };
}

const closeInLabelsAr = {0: 'ميزانية عمومية', 1: 'أرباح وخسائر', 2: 'متاجرة'};

/// One row of GET /reports/chart-of-accounts (already sorted by code by the backend).
class ChartAccount {
  const ChartAccount({
    required this.id,
    this.code,
    required this.name,
    required this.closeIn,
    this.parentAccount,
    required this.accountType,
  });

  final int id;
  final String? code;
  final String name;
  final String closeIn; // "Balance Sheet" / "P&L" / "Trading"
  final int? parentAccount;
  final String accountType; // "master" | "book"

  bool get isBook => accountType == 'book';

  String get label => (code == null || code!.isEmpty) ? name : '$code — $name';

  factory ChartAccount.fromJson(Map<String, dynamic> j) => ChartAccount(
        id: (j['id'] as num).toInt(),
        code: j['code'] as String?,
        name: j['name'] as String,
        closeIn: '${j['closeIn']}',
        parentAccount: (j['parentAccount'] as num?)?.toInt(),
        accountType: j['account_type'] as String? ?? 'book',
      );
}

class TxLine {
  TxLine({this.accId, this.accName, this.debit = 0, this.credit = 0, this.description = ''});

  int? accId;
  String? accName;
  double debit;
  double credit;
  String description;

  factory TxLine.fromJson(Map<String, dynamic> j) => TxLine(
        accId: (j['acc_id'] as num?)?.toInt(),
        accName: j['acc_name'] as String?,
        debit: _num(j['debit']),
        credit: _num(j['credit']),
        description: (j['description'] as String?) ?? '',
      );

  Map<String, dynamic> toJson() => {
        'acc_id': accId,
        'debit': debit,
        'credit': credit,
        'description': description,
      };
}

class Transaction {
  const Transaction({required this.id, this.date, this.notes, required this.lines});

  final int id;
  final DateTime? date;
  final String? notes;
  final List<TxLine> lines;

  double get totalDebit => lines.fold(0.0, (s, l) => s + l.debit);
  double get totalCredit => lines.fold(0.0, (s, l) => s + l.credit);

  factory Transaction.fromJson(Map<String, dynamic> j) {
    final raw = (j['details'] ?? j['items'] ?? const []) as List;
    return Transaction(
      id: (j['id'] as num).toInt(),
      date: _date(j['date']),
      notes: j['notes'] as String?,
      lines: raw.map((e) => TxLine.fromJson(e as Map<String, dynamic>)).toList(),
    );
  }
}

class TransactionInput {
  const TransactionInput({required this.date, this.notes, required this.lines});

  final DateTime date;
  final String? notes;
  final List<TxLine> lines;

  Map<String, dynamic> toJson() => {
        'date': DateTime.utc(date.year, date.month, date.day).toIso8601String(),
        'notes': notes,
        'items': lines.map((l) => l.toJson()).toList(),
      };
}

class Summary {
  const Summary({this.income, this.expense, this.balance, this.message});

  final double? income;
  final double? expense;
  final double? balance;
  final String? message; // set instead of the numbers when there's no data yet

  factory Summary.fromJson(Map<String, dynamic> j) {
    if (j.containsKey('Message')) return Summary(message: j['Message'] as String?);
    return Summary(
      income: _num(j['Total Income']),
      expense: _num(j['Total Expense']),
      balance: _num(j['Balance']),
    );
  }
}

class StatementRow {
  const StatementRow({
    this.transactionId,
    this.date,
    required this.debit,
    required this.credit,
    this.description,
    this.accName,
  });

  final int? transactionId;
  final String? date;
  final double debit;
  final double credit;
  final String? description;
  final String? accName;

  factory StatementRow.fromJson(Map<String, dynamic> j) => StatementRow(
        transactionId: (j['transaction_id'] as num?)?.toInt(),
        date: j['date'] as String?,
        debit: _num(j['debit']),
        credit: _num(j['credit']),
        description: j['description'] as String?,
        accName: j['acc_name'] as String?,
      );
}

class BalanceEntry {
  const BalanceEntry({
    required this.accId,
    this.code,
    this.accName,
    required this.debit,
    required this.credit,
    required this.net,
    this.error,
  });

  final int accId;
  final String? code;
  final String? accName;
  final double debit;
  final double credit;
  final double net;
  final String? error;

  factory BalanceEntry.fromJson(Map<String, dynamic> j) => BalanceEntry(
        accId: (j['acc_id'] as num).toInt(),
        code: j['code'] as String?,
        accName: j['acc_name'] as String?,
        debit: _num(j['debit_sum']),
        credit: _num(j['credit_sum']),
        net: _num(j['net']),
        error: j['error'] as String?,
      );
}

class BalanceResult {
  const BalanceResult({
    required this.debit,
    required this.credit,
    required this.net,
    required this.breakdown,
  });

  final double debit;
  final double credit;
  final double net;
  final List<BalanceEntry> breakdown;

  factory BalanceResult.fromJson(Map<String, dynamic> j) => BalanceResult(
        debit: _num(j['debit_sum']),
        credit: _num(j['credit_sum']),
        net: _num(j['net']),
        breakdown: ((j['breakdown'] ?? const []) as List)
            .map((e) => BalanceEntry.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}
