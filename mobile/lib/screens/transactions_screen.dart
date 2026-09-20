import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../core/format.dart';
import '../models/models.dart';
import '../widgets/common.dart';

class TransactionsScreen extends StatefulWidget {
  const TransactionsScreen({super.key});

  @override
  State<TransactionsScreen> createState() => _TransactionsScreenState();
}

class _TransactionsScreenState extends State<TransactionsScreen> {
  late Future<List<Transaction>> _future;

  @override
  void initState() {
    super.initState();
    _future = _fetch();
  }

  Future<List<Transaction>> _fetch() async {
    final list = await context.read<ApiClient>().transactions();
    // newest first, like a bank statement
    list.sort((a, b) {
      final byDate = (b.date ?? DateTime(0)).compareTo(a.date ?? DateTime(0));
      return byDate != 0 ? byDate : b.id.compareTo(a.id);
    });
    return list;
  }

  void _reload() {
    final next = _fetch();
    next.ignore(); // a fast failure must not be reported as unhandled before FutureBuilder subscribes
    setState(() {
      _future = next;
    });
  }

  Future<void> _openForm({int? editingId}) async {
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => TransactionFormPage(editingId: editingId)),
    );
    if (saved == true) _reload();
  }

  Future<void> _delete(Transaction t) async {
    if (!await confirmDialog(context, 'متأكد من حذف القيد رقم ${t.id}؟')) return;
    if (!mounted) return;
    try {
      await context.read<ApiClient>().deleteTransaction(t.id);
      _reload();
    } on ApiException catch (e) {
      if (mounted) showSnack(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('القيود المحاسبية'),
        actions: [
          IconButton(tooltip: 'تحديث', icon: const Icon(Icons.refresh), onPressed: _reload),
          IconButton(tooltip: 'الإعدادات', icon: const Icon(Icons.settings), onPressed: () => openSettings(context)),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _openForm(),
        icon: const Icon(Icons.add),
        label: const Text('قيد جديد'),
      ),
      body: FutureBuilder<List<Transaction>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            final err = snap.error;
            return ErrorView(
              message: err is ApiException ? err.message : 'حدث خطأ غير متوقع',
              onRetry: _reload,
              showSettings: err is ApiException && err.isConnection,
            );
          }
          final list = snap.data!;
          if (list.isEmpty) return const Center(child: Text('لا يوجد قيود بعد.'));
          return RefreshIndicator(
            onRefresh: () async => _reload(),
            child: ListView.builder(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 96),
              itemCount: list.length,
              itemBuilder: (context, i) {
                final t = list[i];
                return Card(
                  child: ListTile(
                    onTap: () => _openForm(editingId: t.id),
                    title: Text(
                      (t.notes == null || t.notes!.isEmpty) ? 'قيد رقم ${t.id}' : t.notes!,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    subtitle: Text('${fmtDate(t.date)}  ·  مدين ${fmtNum(t.totalDebit)}  ·  دائن ${fmtNum(t.totalCredit)}'),
                    trailing: IconButton(
                      tooltip: 'حذف',
                      icon: Icon(Icons.delete_outline, color: Theme.of(context).colorScheme.error),
                      onPressed: () => _delete(t),
                    ),
                  ),
                );
              },
            ),
          );
        },
      ),
    );
  }
}

/// One editable debit/credit row in the form.
class _LineEditor {
  _LineEditor({this.accId, String debit = '', String credit = '', String description = ''})
      : debit = TextEditingController(text: debit),
        credit = TextEditingController(text: credit),
        description = TextEditingController(text: description);

  int? accId;
  final TextEditingController debit;
  final TextEditingController credit;
  final TextEditingController description;

  double get debitValue => parseAmount(debit.text) ?? 0;
  double get creditValue => parseAmount(credit.text) ?? 0;
  bool get isEmpty => accId == null && debitValue == 0 && creditValue == 0;

  TxLine toLine() => TxLine(
        accId: accId,
        debit: roundCents(debitValue),
        credit: roundCents(creditValue),
        description: description.text.trim(),
      );

  void dispose() {
    debit.dispose();
    credit.dispose();
    description.dispose();
  }
}

class TransactionFormPage extends StatefulWidget {
  const TransactionFormPage({super.key, this.editingId});

  final int? editingId;

  @override
  State<TransactionFormPage> createState() => _TransactionFormPageState();
}

class _TransactionFormPageState extends State<TransactionFormPage> {
  final _notes = TextEditingController();
  DateTime _date = DateTime.now();
  final List<_LineEditor> _lines = [];
  List<ChartAccount> _bookAccounts = [];
  bool _loading = true;
  bool _saving = false;
  String? _loadError;
  String? _saveError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final api = context.read<ApiClient>();
      final chart = await api.chartOfAccounts();
      Transaction? existing;
      if (widget.editingId != null) existing = await api.transaction(widget.editingId!);
      if (!mounted) return;
      setState(() {
        // only postable (leaf) accounts - never the master/header ones
        _bookAccounts = chart.where((a) => a.isBook).toList();
        if (existing != null) {
          _date = existing.date ?? DateTime.now();
          _notes.text = existing.notes ?? '';
          _lines
            ..clear()
            ..addAll(existing.lines.map((l) => _LineEditor(
                  accId: l.accId,
                  debit: l.debit == 0 ? '' : '${l.debit}',
                  credit: l.credit == 0 ? '' : '${l.credit}',
                  description: l.description,
                )));
        } else if (_lines.isEmpty) {
          _lines.addAll([_LineEditor(), _LineEditor()]);
        }
        _loading = false;
      });
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _loadError = e.message;
        });
      }
    }
  }

  @override
  void dispose() {
    _notes.dispose();
    for (final l in _lines) {
      l.dispose();
    }
    super.dispose();
  }

  List<TxLine> get _filledLines => _lines.where((l) => !l.isEmpty).map((l) => l.toLine()).toList();

  bool get _canSave {
    final filled = _filledLines;
    return filled.length >= 2 &&
        filled.every((l) => l.accId != null && (l.debit > 0 || l.credit > 0)) &&
        computeTotals(filled).balanced;
  }

  Future<void> _save() async {
    setState(() {
      _saving = true;
      _saveError = null;
    });
    final input = TransactionInput(
      date: _date,
      notes: _notes.text.trim(),
      lines: _filledLines,
    );
    try {
      final api = context.read<ApiClient>();
      if (widget.editingId != null) {
        await api.updateTransaction(widget.editingId!, input);
      } else {
        await api.createTransaction(input);
      }
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _saving = false;
          _saveError = e.message;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final totals = computeTotals(_lines.map((l) => l.toLine()));
    final scheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(title: Text(widget.editingId == null ? 'قيد جديد' : 'تعديل القيد ${widget.editingId}')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _loadError != null
              ? ErrorView(message: _loadError!, onRetry: _load, showSettings: true)
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Row(
                      children: [
                        Expanded(
                          flex: 3,
                          child: DateButton(
                            label: 'التاريخ',
                            value: _date,
                            onChanged: (d) => setState(() => _date = d ?? _date),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          flex: 2,
                          child: TextField(
                            controller: _notes,
                            decoration: const InputDecoration(labelText: 'ملاحظات', border: OutlineInputBorder(), isDense: true),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    for (var i = 0; i < _lines.length; i++) _lineCard(i),
                    Align(
                      alignment: AlignmentDirectional.centerStart,
                      child: TextButton.icon(
                        onPressed: () => setState(() => _lines.add(_LineEditor())),
                        icon: const Icon(Icons.add),
                        label: const Text('إضافة سطر'),
                      ),
                    ),
                    const Divider(),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text('مدين: ${fmtNum(totals.debit)}'),
                        Text('دائن: ${fmtNum(totals.credit)}'),
                        Text(
                          totals.balanced ? '✓ متوازن' : '✗ غير متوازن',
                          style: TextStyle(
                            fontWeight: FontWeight.w600,
                            color: totals.balanced ? Colors.green.shade700 : scheme.error,
                          ),
                        ),
                      ],
                    ),
                    if (_saveError != null) ...[
                      const SizedBox(height: 10),
                      Text(_saveError!, style: TextStyle(color: scheme.error)),
                    ],
                    const SizedBox(height: 16),
                    FilledButton(
                      onPressed: (_saving || !_canSave) ? null : _save,
                      child: _saving
                          ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                          : const Text('حفظ'),
                    ),
                  ],
                ),
    );
  }

  Widget _lineCard(int i) {
    final line = _lines[i];
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          children: [
            Row(
              children: [
                Expanded(
                  child: DropdownButtonFormField<int>(
                    value: _bookAccounts.any((a) => a.id == line.accId) ? line.accId : null,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: 'الحساب', isDense: true, border: OutlineInputBorder()),
                    items: [
                      for (final a in _bookAccounts)
                        DropdownMenuItem(value: a.id, child: Text(a.label, overflow: TextOverflow.ellipsis)),
                    ],
                    onChanged: (v) => setState(() => line.accId = v),
                  ),
                ),
                if (_lines.length > 2)
                  IconButton(
                    tooltip: 'حذف السطر',
                    icon: const Icon(Icons.close),
                    onPressed: () => setState(() => _lines.removeAt(i).dispose()),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(child: _amountField(line.debit, 'مدين')),
                const SizedBox(width: 8),
                Expanded(child: _amountField(line.credit, 'دائن')),
              ],
            ),
            const SizedBox(height: 8),
            TextField(
              controller: line.description,
              decoration: const InputDecoration(labelText: 'الوصف', isDense: true, border: OutlineInputBorder()),
            ),
          ],
        ),
      ),
    );
  }

  Widget _amountField(TextEditingController c, String label) => TextField(
        controller: c,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        onChanged: (_) => setState(() {}),
        decoration: InputDecoration(labelText: label, isDense: true, border: const OutlineInputBorder()),
      );
}
